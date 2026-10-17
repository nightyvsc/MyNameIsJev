"""Interfaz de evaluación JEV y clientes con timeout/reintentos.

El transporte de JevClient es inyectado hasta recibir la especificación oficial
del API; este módulo no inventa endpoints ni envelopes de petición/respuesta.
"""
from __future__ import annotations

import asyncio
import json
import math
import time
from dataclasses import dataclass
from typing import Any, Protocol

from jev_gate.models.contracts import Action


class JEVError(RuntimeError):
    """Error controlado al evaluar con JEV."""


class JEVUnavailable(JEVError):
    """JEV agotó timeout/reintentos o devolvió una respuesta inválida."""

    def __init__(self, message: str, latency_ms: float = 0.0):
        super().__init__(message)
        self.latency_ms = latency_ms


@dataclass
class Evaluation:
    answers: dict[str, dict[str, Any]]
    latency_ms: float
    cost_usd: float
    source: str = "jev"


class DecisionModel(Protocol):
    async def evaluate(self, action: Action, features: dict[str, Any], questions: list[dict[str, Any]]) -> Evaluation: ...


class Transport(Protocol):
    async def __call__(self, action: Action, features: dict[str, Any], questions: list[dict[str, Any]]) -> dict[str, Any]: ...


class JevClient:
    """Cliente de la capa JEV; transport implementa el protocolo oficial al integrarlo."""

    def __init__(self, transport: Transport | None, timeout_seconds: float = 0.5, retries: int = 2, input_cost_per_million: float = 0.042, retry_base_delay_seconds: float = 0.1, retry_backoff: str = "exponential"):
        self.transport = transport
        self.timeout_seconds = timeout_seconds
        self.retries = retries
        self.input_cost_per_million = input_cost_per_million
        self.retry_base_delay_seconds = retry_base_delay_seconds
        self.retry_backoff = retry_backoff

    async def evaluate(self, action: Action, features: dict[str, Any], questions: list[dict[str, Any]]) -> Evaluation:
        if self.transport is None:
            raise JEVUnavailable("Falta documentación/protocolo oficial para configurar el transporte JEV")
        start = time.perf_counter()
        last_error: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                result = await asyncio.wait_for(self.transport(action, features, questions), timeout=self.timeout_seconds)
                answers = validate_answers(result, questions)
                serialized = json.dumps({"action": action.model_dump(mode="json"), "features": features, "questions": questions}, ensure_ascii=False)
                estimated_tokens = math.ceil(len(serialized) / 4)
                estimated_cost = estimated_tokens * self.input_cost_per_million / 1_000_000
                return Evaluation(answers, (time.perf_counter() - start) * 1000, estimated_cost, "jev")
            except Exception as exc:
                last_error = exc
                if attempt < self.retries:
                    multiplier = 2**attempt if self.retry_backoff == "exponential" else attempt + 1 if self.retry_backoff == "linear" else 0
                    await asyncio.sleep(self.retry_base_delay_seconds * multiplier)
        elapsed_ms = (time.perf_counter() - start) * 1000
        raise JEVUnavailable(f"JEV no respondió tras {self.retries + 1} intentos: {last_error}", elapsed_ms) from last_error


class MockJev:
    """Evaluador determinista solo para desarrollo/tests, no usar en producción."""

    async def evaluate(self, action: Action, features: dict[str, Any], questions: list[dict[str, Any]]) -> Evaluation:
        return self.evaluate_sync(action, features, questions)

    def evaluate_sync(self, action: Action, features: dict[str, Any], questions: list[dict[str, Any]]) -> Evaluation:
        start = time.perf_counter()
        text = str(action.payload).lower()
        answers: dict[str, dict[str, Any]] = {}
        for question in questions:
            qid, qtype = question["id"], question["type"]
            positive = _heuristic(qid, text, features, action)
            if qtype == "boolean":
                p = 0.9 if positive else 0.08
                answers[qid] = {"type": qtype, "probs": {"true": p, "false": 1 - p}}
            elif qtype == "choice":
                options = question.get("options", ["other"])
                if qid == "risk_level":
                    label = features.get("computed_risk_level", options[0])
                elif qid == "review_action" and features.get("has_secret_pattern"):
                    label = "flag_for_security_team"
                elif qid == "review_action" and positive:
                    label = "request_changes"
                elif qid == "code_quality_tier" and positive:
                    label = "refactor_required"
                else:
                    label = "critical" if positive and "critical" in options else options[0]
                if label not in options:
                    label = "other" if "other" in options else options[0]
                answers[qid] = {"type": qtype, "probs": {option: 0.9 if option == label else 0.1 / max(1, len(options) - 1) for option in options}}
            else:
                levels = question.get("levels", ["None", "Low", "Medium", "High", "Critical"])
                label = levels[-1] if positive or features.get("computed_risk_level") in {"high", "critical"} else levels[0]
                answers[qid] = {"type": qtype, "probs": {level: 0.9 if level == label else 0.1 / max(1, len(levels) - 1) for level in levels}}
        return Evaluation(answers, (time.perf_counter() - start) * 1000, 0.0, "mock")


def validate_answers(raw: dict[str, Any], questions: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    if not isinstance(raw, dict):
        raise JEVError("La respuesta JEV debe ser objeto question_id -> respuesta")
    expected = {q["id"]: q for q in questions}
    if set(raw) != set(expected):
        raise JEVError("La respuesta JEV no contiene exactamente las preguntas del lote")
    normalized: dict[str, dict[str, Any]] = {}
    for qid, q in expected.items():
        answer = raw[qid]
        if not isinstance(answer, dict) or answer.get("type") != q["type"] or not isinstance(answer.get("probs"), dict):
            raise JEVError(f"Respuesta inválida para {qid}")
        probs = answer["probs"]
        options = q.get("options") or q.get("levels")
        if q["type"] == "boolean" and set(probs) != {"true", "false"}:
            raise JEVError(f"Boolean {qid} debe reportar true y false")
        if options and set(probs) != set(options):
            raise JEVError(f"Etiquetas de probabilidad inválidas para {qid}")
        if not probs or any(not isinstance(v, (int, float)) or v < 0 or v > 1 for v in probs.values()):
            raise JEVError(f"Probabilidades inválidas para {qid}")
        if abs(sum(probs.values()) - 1) > 0.02:
            raise JEVError(f"Probabilidades de {qid} deben sumar 1")
        normalized[qid] = {"type": q["type"], "probs": {k: float(v) for k, v in probs.items()}}
    return normalized


def _heuristic(qid: str, text: str, features: dict[str, Any], action: Action) -> bool:
    if qid == "action_is_irreversible":
        return action.action_class.value == "email_bulk" or action.subtype in {"merge", "push_main", "touch_secrets", "delete_files"}
    if qid == "adds_unreviewed_dependency":
        return bool(features.get("adds_dependency"))
    if "pii" in qid or "sensitive" in qid:
        return bool(features.get("has_pii_regex"))
    if "secret" in qid:
        return bool(features.get("has_secret_pattern"))
    if "vulnerability" in qid:
        return any(word in text for word in ("exploit", "insecure", "vulnerability"))
    if "misleading" in qid:
        return any(word in text for word in ("garantizado", "100% seguro", "sin riesgo", "falso"))
    if "inflammatory" in qid:
        return any(word in text for word in ("odiar", "atacar", "violencia"))
    if "off_brand" in qid:
        return any(word in text for word in ("insulto", "amenaza", "estafa"))
    if "unintentional" in qid:
        return bool(features.get("has_secret_pattern"))
    return False
