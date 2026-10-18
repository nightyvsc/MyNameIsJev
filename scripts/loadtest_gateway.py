#!/usr/bin/env python3
"""Run a bounded real-provider baseline against the Jev gateway."""

from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
import time
import urllib.error
import urllib.request
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

MAX_BASELINE_REQUESTS = 10
MAX_CONCURRENT_REQUESTS = 5
MAX_ESTIMATED_BUDGET_USD = 0.01
RESERVED_COST_PER_ACTION_USD = 0.0005
DEFAULT_TARGET = "http://10.43.99.216:8000"
DEFAULT_ENV_FILE = Path.home() / ".config" / "mynameisjev" / ".env"


class NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, new_url):
        del request, response, code, message, headers, new_url
        return None


def _read_private_env(path: Path) -> dict[str, str]:
    if not path.is_file():
        raise FileNotFoundError(f"VM6 environment file not found: {path}")
    if path.stat().st_mode & 0o077:
        raise PermissionError(f"Environment file must be mode 600 or stricter: {path}")
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        key, separator, value = stripped.partition("=")
        if not separator or not key.replace("_", "").isalnum():
            raise ValueError(f"Invalid environment entry in {path}.")
        values[key] = value
    return values


def _validate_target(base_url: str) -> str:
    parsed = urlparse(base_url)
    if (
        parsed.scheme not in {"http", "https"}
        or parsed.hostname != "10.43.99.216"
        or parsed.port not in {None, 8000}
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
        or parsed.username
        or parsed.password
    ):
        raise ValueError("Load test target must be the VM1 gateway at 10.43.99.216:8000.")
    return base_url.rstrip("/")


def _synthetic_action(index: int) -> dict[str, Any]:
    return {
        "schema_version": "2.0",
        "action_id": str(uuid.uuid4()),
        "action_class": "email_bulk",
        "tool": "loadtest.synthetic_email",
        "actor": "vm6-baseline",
        "args": {"baseline_sequence": index},
        "recipients": ["baseline@example.invalid"],
        "payload": {
            "subject": "Synthetic gateway capacity baseline",
            "body": "Fictional content for a bounded Jev latency and cost baseline.",
        },
        "risk_level": "low",
        "dry_run": True,
        "created_at": datetime.now(timezone.utc).isoformat(),  # noqa: UP017
    }


def _percentile95(values: list[float]) -> float:
    ordered = sorted(values)
    return ordered[max(0, math.ceil(0.95 * len(ordered)) - 1)]


def _send_action(
    target: str, token: str, index: int, timeout: float
) -> dict[str, Any]:
    opener = urllib.request.build_opener(NoRedirectHandler())
    request = urllib.request.Request(
        f"{target}/gate",
        data=json.dumps(_synthetic_action(index)).encode("utf-8"),
        headers={"Content-Type": "application/json", "X-Gate-Token": token},
        method="POST",
    )
    started = time.perf_counter()
    try:
        with opener.open(request, timeout=timeout) as response:
            if response.status != 200:
                raise RuntimeError(f"Gateway returned HTTP {response.status}.")
            decision = json.loads(response.read())
        round_trip_ms = (time.perf_counter() - started) * 1000
    except urllib.error.HTTPError as error:
        raise RuntimeError(f"Gateway returned HTTP {error.code}; baseline stopped.") from error
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as error:
        raise RuntimeError(
            f"Gateway request {index} failed ({type(error).__name__}); baseline stopped."
        ) from error

    if (
        not isinstance(decision, dict)
        or decision.get("status") != "decided"
        or decision.get("source") != "jev"
        or decision.get("verdict") != "allow"
        or not isinstance(decision.get("provider_model"), str)
    ):
        raise RuntimeError(
            f"Request {index} did not produce a real Jev allow decision; baseline stopped."
        )
    latency = decision.get("latency_ms")
    cost = decision.get("cost_usd")
    tokens_in = decision.get("input_tokens")
    tokens_out = decision.get("output_tokens")
    if (
        isinstance(latency, bool)
        or not isinstance(latency, (int, float))
        or latency < 0
        or isinstance(cost, bool)
        or not isinstance(cost, (int, float))
        or cost < 0
        or isinstance(tokens_in, bool)
        or not isinstance(tokens_in, int)
        or tokens_in < 0
        or isinstance(tokens_out, bool)
        or not isinstance(tokens_out, int)
        or tokens_out < 0
    ):
        raise RuntimeError(f"Request {index} returned invalid provider usage metadata.")

    return {
        "index": index,
        "provider_model": decision["provider_model"],
        "latency_ms": float(latency),
        "round_trip_ms": round_trip_ms,
        "cost_usd": float(cost),
        "input_tokens": tokens_in,
        "output_tokens": tokens_out,
        "verdict": decision["verdict"],
    }


def run_baseline(
    target: str,
    token: str,
    request_count: int,
    timeout: float,
    budget_usd: float,
    concurrency: int = 1,
) -> dict[str, Any]:
    target = _validate_target(target)
    if not token:
        raise ValueError("GATE_TOKEN is missing from the VM6 environment file.")
    if request_count < 1 or request_count > MAX_BASELINE_REQUESTS:
        raise ValueError(f"Baseline request count must be between 1 and {MAX_BASELINE_REQUESTS}.")
    if concurrency < 1 or concurrency > MAX_CONCURRENT_REQUESTS:
        raise ValueError(
            f"Concurrency must be between 1 and {MAX_CONCURRENT_REQUESTS}."
        )
    if not 1 <= timeout <= 30:
        raise ValueError("Per-request timeout must be between 1 and 30 seconds.")
    if (
        not math.isfinite(budget_usd)
        or budget_usd <= 0
        or budget_usd > MAX_ESTIMATED_BUDGET_USD
    ):
        raise ValueError(
            f"Estimated budget must be greater than zero and at most "
            f"${MAX_ESTIMATED_BUDGET_USD:.2f}."
        )
    minimum_budget = request_count * RESERVED_COST_PER_ACTION_USD
    if budget_usd < minimum_budget:
        raise ValueError(
            f"Budget must reserve at least ${minimum_budget:.4f} for "
            f"{request_count} actions."
        )

    results: list[dict[str, Any]] = []
    for first_index in range(1, request_count + 1, concurrency):
        batch_indexes = range(
            first_index, min(first_index + concurrency, request_count + 1)
        )
        current_spend = sum(result["cost_usd"] for result in results)
        remaining_reserve = (request_count - first_index + 1) * RESERVED_COST_PER_ACTION_USD
        if current_spend + remaining_reserve > budget_usd:
            raise RuntimeError(
                "Estimated spend reserve reached; stopped before sending the next action."
            )
        batch_results: dict[int, dict[str, Any]] = {}
        with ThreadPoolExecutor(max_workers=len(batch_indexes)) as executor:
            futures = {
                executor.submit(_send_action, target, token, index, timeout): index
                for index in batch_indexes
            }
            for future in as_completed(futures):
                index = futures[future]
                batch_results[index] = future.result()

        for index in sorted(batch_results):
            result = batch_results[index]
            results.append(result)
            print(
                f"{index}/{request_count}: {result['provider_model']} "
                f"Jev {result['latency_ms']:.1f} ms / "
                f"gateway {result['round_trip_ms']:.1f} ms, "
                f"{result['input_tokens']}/{result['output_tokens']} tokens, "
                f"${result['cost_usd']:.8f}, verdict={result['verdict']}",
                flush=True,
            )
        if sum(result["cost_usd"] for result in results) >= budget_usd:
            print("Estimated budget reached; no further actions will be sent.", file=sys.stderr)
            break

    latencies = [result["latency_ms"] for result in results]
    round_trip_latencies = [result["round_trip_ms"] for result in results]
    return {
        "requests": len(results),
        "requested_actions": request_count,
        "concurrency": concurrency,
        "jev_latency_ms": {
            "min": min(latencies),
            "median": statistics.median(latencies),
            "p95": _percentile95(latencies),
            "max": max(latencies),
        },
        "gateway_round_trip_ms": {
            "min": min(round_trip_latencies),
            "median": statistics.median(round_trip_latencies),
            "p95": _percentile95(round_trip_latencies),
            "max": max(round_trip_latencies),
        },
        "provider_tokens": {
            "input": sum(result["input_tokens"] for result in results),
            "output": sum(result["output_tokens"] for result in results),
        },
        "estimated_cost_usd": sum(result["cost_usd"] for result in results),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV_FILE)
    parser.add_argument("--target", default=None)
    parser.add_argument("--requests", type=int, default=MAX_BASELINE_REQUESTS)
    parser.add_argument("--concurrency", type=int, default=1)
    parser.add_argument("--timeout", type=float, default=15)
    parser.add_argument("--max-estimated-cost-usd", type=float, required=True)
    args = parser.parse_args()
    try:
        settings = _read_private_env(args.env_file)
        target = args.target or settings.get("LOAD_TEST_TARGET", DEFAULT_TARGET)
        result = run_baseline(
            target,
            settings.get("GATE_TOKEN", ""),
            args.requests,
            args.timeout,
            args.max_estimated_cost_usd,
            args.concurrency,
        )
        print(json.dumps(result, indent=2, sort_keys=True))
    except (FileNotFoundError, PermissionError, OSError, RuntimeError, ValueError) as error:
        print(f"Baseline stopped: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
