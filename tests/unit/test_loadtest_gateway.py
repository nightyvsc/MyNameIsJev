from __future__ import annotations

import json
import tempfile
import threading
import time
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from jsonschema import Draft202012Validator, FormatChecker
from scripts.loadtest_gateway import (
    _read_private_env,
    _synthetic_action,
    _validate_target,
    run_baseline,
)


class GatewayLoadTestUtilityTests(unittest.TestCase):
    def test_baseline_action_matches_contract_and_is_dry_run(self) -> None:
        root = Path(__file__).resolve().parents[2]
        schema = json.loads((root / "contracts/schemas/action.schema.json").read_text())
        action = _synthetic_action(1)

        Draft202012Validator(schema, format_checker=FormatChecker()).validate(action)
        self.assertTrue(action["dry_run"])
        self.assertEqual(action["recipients"], ["baseline@example.invalid"])

    def test_target_is_restricted_to_vm1_gateway(self) -> None:
        self.assertEqual(
            _validate_target("http://10.43.99.216:8000/"),
            "http://10.43.99.216:8000",
        )
        with self.assertRaises(ValueError):
            _validate_target("https://example.com")

    def test_private_env_requires_restrictive_permissions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            env_file = Path(directory) / ".env"
            env_file.write_text("GATE_TOKEN=synthetic\n", encoding="utf-8")
            env_file.chmod(0o600)
            self.assertEqual(_read_private_env(env_file)["GATE_TOKEN"], "synthetic")
            env_file.chmod(0o644)
            with self.assertRaises(PermissionError):
                _read_private_env(env_file)

    def test_baseline_enforces_ten_action_cap_before_network(self) -> None:
        with self.assertRaises(ValueError):
            run_baseline("http://10.43.99.216:8000", "token", 11, 15, 0.005)

    def test_baseline_requires_full_per_action_reserve_before_network(self) -> None:
        with self.assertRaisesRegex(ValueError, r"\$0\.0050"):
            run_baseline("http://10.43.99.216:8000", "token", 10, 15, 0.0049)

    def test_baseline_enforces_concurrency_cap_before_network(self) -> None:
        with self.assertRaisesRegex(ValueError, "between 1 and 5"):
            run_baseline(
                "http://10.43.99.216:8000",
                "token",
                10,
                15,
                0.01,
                concurrency=6,
            )

    def test_baseline_runs_in_bounded_concurrent_batches(self) -> None:
        active = 0
        peak = 0
        lock = threading.Lock()

        def fake_send(target: str, token: str, index: int, timeout: float) -> dict:
            nonlocal active, peak
            with lock:
                active += 1
                peak = max(peak, active)
            time.sleep(0.03)
            with lock:
                active -= 1
            return {
                "index": index,
                "provider_model": "jev-test",
                "latency_ms": 12.0,
                "round_trip_ms": 14.0,
                "cost_usd": 0.00001,
                "input_tokens": 10,
                "output_tokens": 2,
                "verdict": "allow",
            }

        with (
            patch("scripts.loadtest_gateway._send_action", side_effect=fake_send),
            redirect_stdout(StringIO()),
        ):
            result = run_baseline(
                "http://10.43.99.216:8000",
                "token",
                10,
                15,
                0.01,
                concurrency=5,
            )

        self.assertEqual(peak, 5)
        self.assertEqual(result["requests"], 10)
        self.assertEqual(result["concurrency"], 5)


if __name__ == "__main__":
    unittest.main()
