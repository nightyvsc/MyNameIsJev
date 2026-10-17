#!/usr/bin/env python3
"""Send one explicitly confirmed, synthetic request to the real TypeSafe Jev API."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ENDPOINT = "https://api.typesafe.ai/v1/systemone"

TEST_STATE = (
    "Synthetic API connectivity check. A fictional customer reports that a test payment "
    "is delayed. No real names, email addresses, credentials, or customer data are included."
)

TEST_QUESTIONS: dict[str, dict[str, Any]] = {
    "is_payment_issue": {
        "type": "noul",
        "instructions": "Does the synthetic report concern a payment issue?",
        "criteria": {
            "true": "The report is about a payment or payout.",
            "false": "The report is not about a payment or payout.",
        },
    },
    "routing_team": {
        "type": "choice",
        "instructions": "Which team should handle the synthetic report?",
        "criteria": {
            "billing": "Payments, billing, or payout delays.",
            "technical": "Software bugs, outages, or technical integrations.",
            "sales": "Pricing, upgrades, or new accounts.",
        },
    },
    "urgency": {
        "type": "score",
        "instructions": "How urgent is the synthetic report?",
        "criteria": [
            "Not urgent; no time-sensitive impact.",
            "Somewhat urgent; follow up soon.",
            "Urgent; immediate attention is needed.",
        ],
    },
}


class NoRedirectHandler(HTTPRedirectHandler):
    def redirect_request(
        self,
        request: Request,
        fp: Any,
        code: int,
        message: str,
        headers: Any,
        new_url: str,
    ) -> None:
        return None


def load_env_file(path: Path) -> None:
    """Read simple KEY=value entries without printing or overriding process env."""
    if not path.is_file():
        return
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ValueError(f"Invalid .env syntax on line {line_number}.")
        name, value = line.split("=", 1)
        name = name.strip()
        value = value.strip()
        if not name or not name.replace("_", "").isalnum():
            raise ValueError(f"Invalid environment variable name on line {line_number}.")
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        os.environ.setdefault(name, value)


def validate_endpoint(endpoint: str) -> str:
    parsed = urlparse(endpoint)
    if parsed.scheme != "https" or parsed.hostname != "api.typesafe.ai":
        raise ValueError("JEV_BASE_URL must use HTTPS and the official api.typesafe.ai host.")
    if parsed.path.rstrip("/") != "/v1/systemone" or parsed.query or parsed.fragment:
        raise ValueError("JEV_BASE_URL must point to /v1/systemone.")
    return endpoint.rstrip("/")


def validate_response(body: Any) -> tuple[str, dict[str, Any], dict[str, int]]:
    if not isinstance(body, dict):
        raise ValueError("JEV response must be a JSON object.")
    model = body.get("model")
    answers = body.get("answers")
    usage = body.get("usage")
    if not isinstance(model, str) or not isinstance(answers, dict):
        raise ValueError("JEV response is missing its model or answers object.")

    expected_types = {"is_payment_issue": "noul", "routing_team": "choice", "urgency": "score"}
    for name, question_type in expected_types.items():
        answer = answers.get(name)
        if not isinstance(answer, dict) or answer.get("type") != question_type:
            raise ValueError(f"JEV response has a missing or invalid {name!r} answer.")
        if question_type == "noul":
            value = answer.get("noul")
            if not isinstance(value, (int, float)) or not 0 <= value <= 1:
                raise ValueError(f"JEV response has an invalid noul value for {name!r}.")
        elif question_type == "choice":
            probabilities = answer.get("probabilities")
            if (
                not isinstance(answer.get("choice"), str)
                or not isinstance(probabilities, dict)
                or not probabilities
                or any(not isinstance(value, (int, float)) for value in probabilities.values())
            ):
                raise ValueError(f"JEV response has an invalid choice answer for {name!r}.")
            if abs(sum(probabilities.values()) - 1) > 0.02:
                raise ValueError("JEV choice probabilities do not sum to approximately 1.")
        elif question_type == "score":
            if (
                not isinstance(answer.get("score"), (int, float))
                or not isinstance(answer.get("probabilities"), dict)
                or not isinstance(answer.get("legend"), dict)
            ):
                raise ValueError(f"JEV response has an invalid score answer for {name!r}.")

    safe_usage: dict[str, int] = {}
    if isinstance(usage, dict):
        for field in ("input_tokens", "output_tokens"):
            count = usage.get(field)
            if isinstance(count, int) and count >= 0:
                safe_usage[field] = count
    return model, answers, safe_usage


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dotenv",
        type=Path,
        default=PROJECT_ROOT / ".env",
        help="Ignored local env file (default: repository .env).",
    )
    parser.add_argument(
        "--base-url",
        help=f"Official endpoint; defaults to JEV_BASE_URL or {DEFAULT_ENDPOINT}.",
    )
    parser.add_argument("--model", help="Model name; defaults to JEV_MODEL or jev-latest.")
    parser.add_argument(
        "--timeout",
        type=float,
        default=20,
        help="Request timeout in seconds (default: 20).",
    )
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="Confirm one real API request using synthetic data; usage may be billable.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if not args.confirm:
        print("Refusing to call the real API without --confirm.", file=sys.stderr)
        return 2
    if args.timeout <= 0:
        print("--timeout must be greater than zero.", file=sys.stderr)
        return 2

    try:
        load_env_file(args.dotenv)
        endpoint = validate_endpoint(
            args.base_url or os.environ.get("JEV_BASE_URL", DEFAULT_ENDPOINT)
        )
    except (OSError, ValueError) as error:
        print(f"Configuration error: {error}", file=sys.stderr)
        return 2

    api_key = os.environ.get("TYPESAFE_API_KEY")
    if not api_key:
        print(
            "Missing TYPESAFE_API_KEY. Add it to the ignored .env file or export it in the shell.",
            file=sys.stderr,
        )
        return 2

    model = args.model or os.environ.get("JEV_MODEL", "jev-latest")
    request_body = json.dumps(
        {"state": TEST_STATE, "model": model, "questions": TEST_QUESTIONS},
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    request = Request(
        endpoint,
        data=request_body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    opener = build_opener(NoRedirectHandler())
    started = time.perf_counter()
    try:
        with opener.open(request, timeout=args.timeout) as response:
            status = response.status
            response_bytes = response.read(2 * 1024 * 1024 + 1)
    except HTTPError as error:
        print(f"JEV returned HTTP {error.code}; no retry was attempted.", file=sys.stderr)
        return 1
    except (URLError, TimeoutError, OSError) as error:
        print(
            f"JEV request failed ({type(error).__name__}); no retry was attempted.",
            file=sys.stderr,
        )
        return 1

    elapsed_ms = (time.perf_counter() - started) * 1000
    if len(response_bytes) > 2 * 1024 * 1024:
        print("JEV response exceeded the 2 MiB safety limit.", file=sys.stderr)
        return 1
    try:
        body = json.loads(response_bytes)
        actual_model, answers, usage = validate_response(body)
    except (json.JSONDecodeError, ValueError) as error:
        print(f"Invalid JEV response: {error}", file=sys.stderr)
        return 1

    print(f"HTTP {status}; model={actual_model}; latency_ms={elapsed_ms:.1f}")
    if usage:
        print(f"usage={json.dumps(usage, sort_keys=True)}")
    for name, answer in answers.items():
        if answer["type"] == "noul":
            summary: Any = {"noul": answer["noul"]}
        elif answer["type"] == "choice":
            summary = {
                "choice": answer["choice"],
                "probabilities": answer["probabilities"],
                "confidence": answer.get("confidence"),
            }
        else:
            summary = {
                "score": answer["score"],
                "legend": answer["legend"],
                "probabilities": answer["probabilities"],
                "confidence": answer.get("confidence"),
            }
        print(f"{name}={json.dumps(summary, ensure_ascii=False, sort_keys=True)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
