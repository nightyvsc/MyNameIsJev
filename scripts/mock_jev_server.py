#!/usr/bin/env python3
"""Deterministic local mock for the official TypeSafe System One HTTP API."""

from __future__ import annotations

import argparse
import json
import logging
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

LOGGER = logging.getLogger("mock_jev")
EMAIL_PATTERN = re.compile(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b")
PHONE_PATTERN = re.compile(r"(?<!\w)(?:\+?\d[\d ().-]{7,}\d)(?!\w)")
SECRET_PATTERN = re.compile(
    r"\b(?:secret|password|token|api[_ -]?key|credential|private key)\b", re.IGNORECASE
)


def _state_text(state: Any) -> str:
    if isinstance(state, str):
        return state
    return json.dumps(state, ensure_ascii=False, sort_keys=True)


def _contains_any(state: str, terms: tuple[str, ...]) -> bool:
    state_lower = state.lower()
    return any(term in state_lower for term in terms)


def _noul_value(question_name: str, state: str) -> float:
    signals = {
        "contains_secret_leak": bool(SECRET_PATTERN.search(state)),
        "contains_secret": bool(SECRET_PATTERN.search(state)),
        "introduces_security_vulnerability": _contains_any(
            state, ("sql injection", "cross-site scripting", "xss", "vulnerability")
        ),
        "content_contains_pii": bool(EMAIL_PATTERN.search(state) or PHONE_PATTERN.search(state)),
        "contains_email": bool(EMAIL_PATTERN.search(state)),
        "contains_phone": bool(PHONE_PATTERN.search(state)),
        "content_is_misleading": _contains_any(
            state, ("misleading", "false claim", "fake", "fabricated", "exaggerated")
        ),
        "content_is_off_brand": _contains_any(state, ("off-brand", "unprofessional", "off brand")),
        "content_is_inflammatory": _contains_any(
            state, ("inflammatory", "offensive", "inciting", "hostile")
        ),
        "action_is_irreversible": _contains_any(
            state, ("send email", "send_email", "merge", "publish", "delete")
        ),
        "has_breaking_api_change": _contains_any(
            state, ("breaking change", "breaking api", "incompatible api")
        ),
        "adds_unreviewed_dependency": _contains_any(
            state, ("unreviewed dependency", "new dependency", "adds dependency")
        ),
    }
    return 0.94 if signals.get(question_name, False) else 0.06


def _selected_choice(question_name: str, options: list[str], state: str) -> tuple[str, float]:
    lowered = state.lower()
    preferred: str | None = None
    confidence = 0.9
    if question_name in ("risk_level", "severity"):
        if SECRET_PATTERN.search(state) or _contains_any(lowered, ("critical", "massive", "1500")):
            preferred, confidence = "critical", 0.96
        elif _contains_any(lowered, ("high risk", "misleading", "pii", "inflammatory")):
            preferred, confidence = "high", 0.92
        elif _contains_any(lowered, ("medium risk", "review", "300 recipients")):
            preferred, confidence = "medium", 0.88
        else:
            preferred, confidence = "low", 0.9
    elif question_name == "code_quality_tier":
        if _contains_any(lowered, ("refactor", "poor quality", "unmaintainable")):
            preferred = "refactor_required"
        elif _contains_any(lowered, ("acceptable", "minor issue")):
            preferred = "acceptable"
        else:
            preferred = "clean"
    elif question_name == "review_action":
        if SECRET_PATTERN.search(state):
            preferred = "flag_for_security_team"
        elif _contains_any(lowered, ("breaking change", "vulnerability", "request changes")):
            preferred = "request_changes"
        else:
            preferred = "approve"
    elif question_name == "routing_team":
        if _contains_any(lowered, ("payment", "billing", "payout")):
            preferred = "billing"
        elif _contains_any(lowered, ("bug", "outage", "technical")):
            preferred = "technical"
        else:
            preferred = "sales"

    selected = preferred if preferred in options else options[0]
    return selected, confidence


def evaluate_question(question_name: str, question: dict[str, Any], state: Any) -> dict[str, Any]:
    """Return an answer using TypeSafe's documented answer field names."""
    question_type = question.get("type")
    text = _state_text(state)
    if question_type == "noul":
        return {"type": "noul", "noul": _noul_value(question_name, text)}

    if question_type == "choice":
        criteria = question.get("criteria")
        if (
            not isinstance(criteria, dict)
            or not criteria
            or not all(isinstance(option, str) for option in criteria)
        ):
            raise ValueError(f"Choice question {question_name!r} requires a criteria object.")
        options = list(criteria)
        selected, confidence = _selected_choice(question_name, options, text)
        residual = (1 - confidence) / max(1, len(options) - 1)
        probabilities = {option: residual for option in options}
        probabilities[selected] = confidence
        return {
            "type": "choice",
            "choice": selected,
            "probabilities": probabilities,
            "confidence": confidence,
        }

    if question_type == "score":
        criteria = question.get("criteria")
        if not isinstance(criteria, list) or not 2 <= len(criteria) <= 10:
            raise ValueError(f"Score question {question_name!r} requires 2 to 10 criteria.")
        lowered = text.lower()
        if SECRET_PATTERN.search(text) or _contains_any(lowered, ("critical", "massive")):
            level_index, confidence = len(criteria) - 1, 0.96
        elif _contains_any(lowered, ("high risk", "vulnerability", "misleading", "pii")):
            level_index, confidence = min(2, len(criteria) - 1), 0.91
        elif _contains_any(lowered, ("medium risk", "review")):
            level_index, confidence = min(1, len(criteria) - 1), 0.88
        else:
            level_index, confidence = 0, 0.92
        residual = (1 - confidence) / max(1, len(criteria) - 1)
        probabilities = {str(index): residual for index in range(len(criteria))}
        probabilities[str(level_index)] = confidence
        score = sum(
            index * probability
            for index, probability in (
                (index, probabilities[str(index)]) for index in range(len(criteria))
            )
        )
        legend = {str(index): str(level) for index, level in enumerate(criteria)}
        return {
            "type": "score",
            "score": score,
            "legend": legend,
            "probabilities": probabilities,
            "confidence": confidence,
        }

    raise ValueError(f"Unsupported question type for {question_name!r}: {question_type!r}.")


def _validate_request(request: Any) -> tuple[str, Any, dict[str, dict[str, Any]]]:
    if not isinstance(request, dict):
        raise ValueError("Request body must be a JSON object.")
    model, state, questions = request.get("model"), request.get("state"), request.get("questions")
    if not isinstance(model, str) or not model:
        raise ValueError("'model' must be a non-empty string.")
    if not isinstance(state, (str, dict, list)):
        raise ValueError("'state' must be a string, object, or array.")
    if not isinstance(questions, dict) or not questions:
        raise ValueError("'questions' must be a non-empty object.")
    if not all(
        isinstance(name, str) and isinstance(question, dict) for name, question in questions.items()
    ):
        raise ValueError("Each question must have a string name and an object definition.")
    for name, question in questions.items():
        if not isinstance(question.get("instructions"), (str, dict, list)):
            raise ValueError(f"Question {name!r} requires string, object, or array instructions.")
    return model, state, questions


def create_handler() -> type[BaseHTTPRequestHandler]:
    class JEVRequestHandler(BaseHTTPRequestHandler):
        server_version = "MockJEV/1.0"

        def do_POST(self) -> None:
            if self.path != "/v1/systemone" and self.path != "/":
                self._send_json(404, {"error": "not_found", "message": "Use POST /v1/systemone."})
                return
            try:
                content_length = int(self.headers.get("Content-Length", "0"))
                if not 0 < content_length <= 32 * 1024 * 1024:
                    raise ValueError("Request body must be between 1 byte and 32 MiB.")
                request = json.loads(self.rfile.read(content_length))
                model, state, questions = _validate_request(request)
                answers = {
                    name: evaluate_question(name, question, state)
                    for name, question in questions.items()
                }
            except (ValueError, TypeError, json.JSONDecodeError) as error:
                self._send_json(400, {"error": "invalid_request", "message": str(error)})
                return

            LOGGER.info("model=%s questions=%s answers=%s", model, list(questions), answers)
            self._send_json(
                200,
                {
                    "model": model,
                    "answers": answers,
                    "usage": {"input_tokens": 0, "output_tokens": 0},
                },
            )

        def do_GET(self) -> None:
            if self.path == "/health":
                self._send_json(200, {"status": "ok"})
            else:
                self._send_json(404, {"error": "not_found", "message": "Use GET /health."})

        def _send_json(self, status: int, payload: dict[str, Any]) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format_string: str, *args: Any) -> None:
            LOGGER.info("%s - %s", self.address_string(), format_string % args)

    return JEVRequestHandler


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--host", default="127.0.0.1", help="Interface to bind (default: loopback)."
    )
    parser.add_argument("--port", type=int, default=9000, help="Port to listen on.")
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("--port must be between 1 and 65535.")

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    server = ThreadingHTTPServer((args.host, args.port), create_handler())
    LOGGER.info("Mock JEV listening on http://%s:%d/v1/systemone", args.host, args.port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        LOGGER.info("Shutting down.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
