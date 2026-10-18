"""Cliente TypeSafe System One y adaptadores de evaluación."""
from __future__ import annotations

import asyncio
import json
import math
import time
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import urlparse

import httpx

from jev_gate.models.contracts import Action

DEFAULT_ENDPOINT = "https://api.typesafe.ai/v1/systemone"
MAX_RESPONSE_BYTES = 2 * 1024 * 1024


class JEVError(RuntimeError):
    """Error controlado al evaluar con JEV."""


class JEVRetryableError(JEVError):
    """Fallo temporal del proveedor que puede reintentarse."""


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
    model: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None


@dataclass
class ProviderResponse:
    answers: dict[str, dict[str, Any]]
    model: str
    input_tokens: int
    output_tokens: int


class DecisionModel(Protocol):
    async def evaluate(
        self, action: Action, features: dict[str, Any], questions: list[dict[str, Any]]
    ) -> Evaluation: ...


class Transport(Protocol):
    async def __call__(
        self, action: Action, features: dict[str, Any], questions: list[dict[str, Any]]
    ) -> dict[str, Any] | ProviderResponse: ...


def validate_endpoint(endpoint: str) -> str:
    parsed = urlparse(endpoint)
    if (
        parsed.scheme != "https"
        or parsed.hostname != "api.typesafe.ai"
        or parsed.path.rstrip("/") != "/v1/systemone"
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("JEV_BASE_URL debe usar el endpoint HTTPS oficial de TypeSafe.")
    return endpoint.rstrip("/")


def build_typesafe_request(
    action: Action,
    features: dict[str, Any],
    questions: list[dict[str, Any]],
    model: str,
) -> dict[str, Any]:
    api_questions: dict[str, dict[str, Any]] = {}
    for question in questions:
        question_type = question["type"]
        api_question: dict[str, Any] = {"instructions": question["text"]}
        if question_type == "boolean":
            api_question["type"] = "noul"
            if "criteria" in question:
                api_question["criteria"] = question["criteria"]
        elif question_type == "choice":
            api_question["type"] = "choice"
            api_question["criteria"] = question.get(
                "criteria", {option: option for option in question["options"]}
            )
        elif question_type == "score":
            api_question["type"] = "score"
            api_question["criteria"] = question["levels"]
        else:
            raise JEVError(f"Tipo de pregunta no soportado: {question_type}")
        api_questions[question["id"]] = api_question

    return {
        "model": model,
        "state": {
            "action": action.model_dump(mode="json", exclude_none=True),
            "deterministic_features": features,
        },
        "questions": api_questions,
    }


def normalize_typesafe_response(
    body: Any, questions: list[dict[str, Any]]
) -> ProviderResponse:
    if not isinstance(body, dict):
        raise JEVError("Respuesta TypeSafe inválida: se esperaba un objeto JSON.")
    model = body.get("model")
    raw_answers = body.get("answers")
    usage = body.get("usage")
    if not isinstance(model, str) or not model or not isinstance(raw_answers, dict):
        raise JEVError("Respuesta TypeSafe sin modelo o respuestas.")
    if not isinstance(usage, dict):
        raise JEVError("Respuesta TypeSafe sin datos de uso.")
    token_counts: dict[str, int] = {}
    for name in ("input_tokens", "output_tokens"):
        value = usage.get(name)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise JEVError(f"Uso TypeSafe inválido: {name}.")
        token_counts[name] = value

    expected = {question["id"]: question for question in questions}
    if set(raw_answers) != set(expected):
        raise JEVError("Respuesta TypeSafe no coincide con las preguntas enviadas.")

    normalized: dict[str, dict[str, Any]] = {}
    for question_id, question in expected.items():
        answer = raw_answers[question_id]
        if not isinstance(answer, dict):
            raise JEVError(f"Respuesta TypeSafe inválida para {question_id}.")
        question_type = question["type"]
        api_type = {"boolean": "noul", "choice": "choice", "score": "score"}[question_type]
        if answer.get("type") != api_type:
            raise JEVError(f"Tipo de respuesta TypeSafe inválido para {question_id}.")

        if question_type == "boolean":
            probability = answer.get("noul")
            _validate_probability(probability, question_id)
            normalized[question_id] = {
                "type": question_type,
                "probs": {"true": float(probability), "false": 1 - float(probability)},
                "value": float(probability),
            }
        elif question_type == "choice":
            options = question["options"]
            probabilities = answer.get("probabilities")
            if (
                answer.get("choice") not in options
                or not isinstance(probabilities, dict)
                or set(probabilities) != set(options)
            ):
                raise JEVError(f"Opciones TypeSafe inválidas para {question_id}.")
            _validate_distribution(probabilities, question_id)
            normalized[question_id] = {
                "type": question_type,
                "probs": {name: float(probabilities[name]) for name in options},
                "value": answer["choice"],
                "confidence": _validate_confidence(answer.get("confidence"), question_id),
            }
        else:
            levels = question["levels"]
            probabilities = answer.get("probabilities")
            expected_indices = {str(index) for index in range(len(levels))}
            score = answer.get("score")
            if (
                not isinstance(probabilities, dict)
                or set(probabilities) != expected_indices
                or isinstance(score, bool)
                or not isinstance(score, (int, float))
                or not math.isfinite(score)
                or score < 0
                or score > len(levels) - 1
            ):
                raise JEVError(f"Score TypeSafe inválido para {question_id}.")
            _validate_distribution(probabilities, question_id)
            normalized[question_id] = {
                "type": question_type,
                "probs": {
                    level: float(probabilities[str(index)])
                    for index, level in enumerate(levels)
                },
                "value": float(score),
                "confidence": _validate_confidence(answer.get("confidence"), question_id),
            }

    return ProviderResponse(
        answers=normalized,
        model=model,
        input_tokens=token_counts["input_tokens"],
        output_tokens=token_counts["output_tokens"],
    )


def _validate_probability(value: Any, question_id: str) -> None:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value < 0
        or value > 1
    ):
        raise JEVError(f"Probabilidad TypeSafe inválida para {question_id}.")


def _validate_distribution(probabilities: dict[str, Any], question_id: str) -> None:
    for value in probabilities.values():
        _validate_probability(value, question_id)
    if not probabilities or abs(sum(probabilities.values()) - 1) > 0.02:
        raise JEVError(f"Probabilidades TypeSafe inválidas para {question_id}.")


def _validate_confidence(value: Any, question_id: str) -> float:
    _validate_probability(value, question_id)
    return float(value)


class TypeSafeTransport:
    def __init__(self, api_key: str, endpoint: str, model: str, timeout_seconds: float):
        if not api_key:
            raise ValueError("TYPESAFE_API_KEY no está configurada.")
        if not model:
            raise ValueError("JEV_MODEL no está configurado.")
        self.api_key = api_key
        self.endpoint = validate_endpoint(endpoint)
        self.model = model
        self.timeout_seconds = timeout_seconds

    async def __call__(
        self, action: Action, features: dict[str, Any], questions: list[dict[str, Any]]
    ) -> ProviderResponse:
        payload = build_typesafe_request(action, features, questions, self.model)
        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                response = await client.post(
                    self.endpoint,
                    json=payload,
                    headers={"Authorization": f"Bearer {self.api_key}"},
                )
        except httpx.TimeoutException as exc:
            raise JEVRetryableError("Timeout al consultar TypeSafe.") from exc
        except httpx.RequestError as exc:
            raise JEVRetryableError(
                f"Fallo de conexión TypeSafe ({type(exc).__name__})."
            ) from exc

        if response.status_code in {408, 429} or response.status_code >= 500:
            raise JEVRetryableError(f"TypeSafe respondió HTTP {response.status_code}.")
        if response.is_error:
            raise JEVError(f"TypeSafe respondió HTTP {response.status_code}.")
        if len(response.content) > MAX_RESPONSE_BYTES:
            raise JEVError("La respuesta TypeSafe excedió el límite de 2 MiB.")
        try:
            body = response.json()
        except (json.JSONDecodeError, ValueError) as exc:
            raise JEVError("TypeSafe devolvió JSON inválido.") from exc
        return normalize_typesafe_response(body, questions)


class JevClient:
    """Cliente JEV con timeout, reintentos transitorios y costo por uso informado."""

    def __init__(self, transport: Transport | None, timeout_seconds: float = 0.5, retries: int = 2, input_cost_per_million: float = 0.042, retry_base_delay_seconds: float = 0.1, retry_backoff: str = "exponential"):
        self.transport = transport
        self.timeout_seconds = timeout_seconds
        self.retries = retries
        self.input_cost_per_million = input_cost_per_million
        self.retry_base_delay_seconds = retry_base_delay_seconds
        self.retry_backoff = retry_backoff

    async def evaluate(
        self, action: Action, features: dict[str, Any], questions: list[dict[str, Any]]
    ) -> Evaluation:
        if self.transport is None:
            raise JEVUnavailable("TYPESAFE_API_KEY no está configurada.")
        start = time.perf_counter()
        last_error: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                result = await asyncio.wait_for(
                    self.transport(action, features, questions), timeout=self.timeout_seconds
                )
                if isinstance(result, ProviderResponse):
                    answers = validate_answers(result.answers, questions)
                    cost_usd = (
                        result.input_tokens * self.input_cost_per_million / 1_000_000
                    )
                    return Evaluation(
                        answers=answers,
                        latency_ms=(time.perf_counter() - start) * 1000,
                        cost_usd=cost_usd,
                        source="jev",
                        model=result.model,
                        input_tokens=result.input_tokens,
                        output_tokens=result.output_tokens,
                    )
                answers = validate_answers(result, questions)
                serialized = json.dumps(
                    {
                        "action": action.model_dump(mode="json"),
                        "features": features,
                        "questions": questions,
                    },
                    ensure_ascii=False,
                )
                estimated_tokens = math.ceil(len(serialized) / 4)
                estimated_cost = estimated_tokens * self.input_cost_per_million / 1_000_000
                return Evaluation(
                    answers, (time.perf_counter() - start) * 1000, estimated_cost, "jev"
                )
            except JEVError as exc:
                last_error = exc
                if not isinstance(exc, JEVRetryableError) or attempt >= self.retries:
                    break
            except Exception as exc:
                last_error = exc
                if attempt >= self.retries:
                    break
            multiplier = (
                2**attempt
                if self.retry_backoff == "exponential"
                else attempt + 1
                if self.retry_backoff == "linear"
                else 0
            )
            await asyncio.sleep(self.retry_base_delay_seconds * multiplier)
        elapsed_ms = (time.perf_counter() - start) * 1000
        error_summary = (
            str(last_error)
            if isinstance(last_error, JEVError)
            else type(last_error).__name__
        )
        raise JEVUnavailable(
            f"JEV no respondió tras {attempt + 1} intento(s): {error_summary}", elapsed_ms
        ) from last_error


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
        normalized_answer: dict[str, Any] = {
            "type": q["type"],
            "probs": {k: float(v) for k, v in probs.items()},
        }
        if "value" in answer:
            normalized_answer["value"] = answer["value"]
        if "confidence" in answer:
            normalized_answer["confidence"] = answer["confidence"]
        normalized[qid] = normalized_answer
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
