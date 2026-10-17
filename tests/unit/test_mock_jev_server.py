from __future__ import annotations

import json
import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer

from scripts.mock_jev_server import create_handler


class MockJEVHTTPTest(unittest.TestCase):
    def test_returns_typed_answers_over_http(self) -> None:
        server = ThreadingHTTPServer(("127.0.0.1", 0), create_handler())
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            request_body = {
                "model": "jev-1.14",
                "state": "This email contains secret password and alice@example.com",
                "questions": {
                    "contains_secret_leak": {
                        "type": "noul",
                        "instructions": "Does this contain a secret leak?",
                    },
                    "content_contains_pii": {
                        "type": "noul",
                        "instructions": "Does this contain personal information?",
                    },
                    "risk_level": {
                        "type": "choice",
                        "instructions": "What is the risk level?",
                        "criteria": {
                            "low": "Low risk.",
                            "medium": "Medium risk.",
                            "high": "High risk.",
                            "critical": "Critical risk.",
                        },
                    },
                },
            }
            request = urllib.request.Request(
                f"http://127.0.0.1:{server.server_port}/",
                data=json.dumps(request_body).encode(),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(request, timeout=2) as response:
                result = json.load(response)

            self.assertEqual(result["model"], "jev-1.14")
            self.assertGreater(result["answers"]["contains_secret_leak"]["noul"], 0.7)
            self.assertGreater(result["answers"]["content_contains_pii"]["noul"], 0.7)
            self.assertEqual(result["answers"]["risk_level"]["choice"], "critical")
            self.assertAlmostEqual(
                sum(result["answers"]["risk_level"]["probabilities"].values()), 1
            )
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
