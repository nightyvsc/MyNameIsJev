from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.test_jev_api import load_env_file, validate_endpoint, validate_response


class JEVAPIProbeTests(unittest.TestCase):
    def test_accepts_official_typed_response_shape(self) -> None:
        response = {
            "model": "jev-latest",
            "answers": {
                "is_payment_issue": {"type": "noul", "noul": 0.98},
                "routing_team": {
                    "type": "choice",
                    "choice": "billing",
                    "probabilities": {"billing": 0.9, "technical": 0.1, "sales": 0},
                    "confidence": 0.88,
                },
                "urgency": {
                    "type": "score",
                    "score": 0.2,
                    "legend": {"0": "Not urgent", "1": "Soon", "2": "Immediate"},
                    "probabilities": {"0": 0.9, "1": 0.1, "2": 0},
                    "confidence": 0.87,
                },
            },
            "usage": {"input_tokens": 100, "output_tokens": 20},
        }
        model, answers, usage = validate_response(response)
        self.assertEqual(model, "jev-latest")
        self.assertEqual(set(answers), {"is_payment_issue", "routing_team", "urgency"})
        self.assertEqual(usage["input_tokens"], 100)

    def test_rejects_invalid_choice_probabilities(self) -> None:
        with self.assertRaisesRegex(ValueError, "do not sum"):
            validate_response(
                {
                    "model": "jev-latest",
                    "answers": {
                        "is_payment_issue": {"type": "noul", "noul": 0.5},
                        "routing_team": {
                            "type": "choice",
                            "choice": "billing",
                            "probabilities": {"billing": 0.9, "technical": 0.9},
                        },
                        "urgency": {
                            "type": "score",
                            "score": 1,
                            "legend": {"0": "low"},
                            "probabilities": {"0": 1},
                        },
                    },
                }
            )

    def test_only_allows_official_https_endpoint(self) -> None:
        self.assertEqual(
            validate_endpoint("https://api.typesafe.ai/v1/systemone"),
            "https://api.typesafe.ai/v1/systemone",
        )
        for endpoint in (
            "http://api.typesafe.ai/v1/systemone",
            "https://attacker.example/v1/systemone",
            "https://api.typesafe.ai/other",
        ):
            with self.subTest(endpoint=endpoint), self.assertRaises(ValueError):
                validate_endpoint(endpoint)

    def test_loads_env_file_without_overriding_process_environment(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env"
            path.write_text("JEV_MODEL='jev-latest'\n# comment\n", encoding="utf-8")
            with patch.dict("os.environ", {}, clear=True):
                load_env_file(path)
                self.assertEqual(__import__("os").environ.get("JEV_MODEL"), "jev-latest")


if __name__ == "__main__":
    unittest.main()
