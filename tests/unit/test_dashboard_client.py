from __future__ import annotations

import unittest
from unittest.mock import patch

import httpx
from dashboard import app as dashboard_app
from dashboard.app import GatewayAPIError


class DashboardGatewayClientTests(unittest.TestCase):
    def test_get_adds_gate_token_header(self) -> None:
        response = httpx.Response(
            200,
            json=[],
            request=httpx.Request("GET", "http://gateway/decisions"),
        )
        with (
            patch.object(dashboard_app, "GATEWAY_BASE_URL", "http://gateway"),
            patch.object(dashboard_app, "GATE_TOKEN", "local-test-token"),
            patch.object(dashboard_app.httpx, "get", return_value=response) as get,
        ):
            result = dashboard_app.gateway_get("/decisions", {"limit": 5})

        self.assertEqual(result, [])
        self.assertEqual(get.call_args.kwargs["headers"]["X-Gate-Token"], "local-test-token")

    def test_post_reports_gateway_errors(self) -> None:
        response = httpx.Response(
            409,
            json={"message": "decision is not pending"},
            request=httpx.Request("POST", "http://gateway/gate/id/approve"),
        )
        with (
            patch.object(dashboard_app, "GATEWAY_BASE_URL", "http://gateway"),
            patch.object(dashboard_app, "GATE_TOKEN", "local-test-token"),
            patch.object(dashboard_app.httpx, "post", return_value=response),
            self.assertRaisesRegex(GatewayAPIError, "HTTP 409"),
        ):
            dashboard_app.gateway_post(
                "/gate/id/approve",
                {"resolution": "approved", "resolved_by": "reviewer"},
            )

    def test_missing_configuration_fails_explicitly(self) -> None:
        with (
            patch.object(dashboard_app, "GATEWAY_BASE_URL", ""),
            patch.object(dashboard_app, "GATE_TOKEN", ""),
            self.assertRaisesRegex(GatewayAPIError, "GATEWAY_BASE_URL"),
        ):
            dashboard_app.gateway_get("/approvals")


if __name__ == "__main__":
    unittest.main()
