from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

from world.agents.runner import (
    _execute_allowed_action,
    sales_scenarios,
    social_scenarios,
)


class AgentRoutingTests(unittest.TestCase):
    def test_crm_effect_uses_crm_service_url(self) -> None:
        response = Mock(status=200)
        with patch("world.agents.runner.urllib.request.urlopen", return_value=response) as open_url:
            result = _execute_allowed_action(
                sales_scenarios()[3],
                "http://10.43.99.199:3001",
                "http://10.43.99.199:3003",
                "10.43.99.199",
                2525,
            )

        self.assertEqual(result, "crm_http_200")
        self.assertEqual(
            open_url.call_args.args[0].get_full_url(),
            "http://10.43.99.199:3001/contacts/bulk-upsert",
        )

    def test_social_effect_uses_social_service_url(self) -> None:
        response = Mock(status=201)
        with patch("world.agents.runner.urllib.request.urlopen", return_value=response) as open_url:
            result = _execute_allowed_action(
                social_scenarios()[0],
                "http://10.43.99.199:3001",
                "http://10.43.99.199:3003",
                "10.43.99.199",
                2525,
            )

        self.assertEqual(result, "social_http_201")
        self.assertEqual(
            open_url.call_args.args[0].get_full_url(),
            "http://10.43.99.199:3003/posts",
        )


if __name__ == "__main__":
    unittest.main()
