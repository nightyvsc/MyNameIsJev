from __future__ import annotations

import json
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker
from streamlit.testing.v1 import AppTest

from dashboard.demo_app import SCENARIOS

DEMO_APP_PATH = Path(__file__).resolve().parents[2] / "dashboard" / "demo_app.py"
ACTION_SCHEMA_PATH = (
    Path(__file__).resolve().parents[2] / "contracts" / "schemas" / "action.schema.json"
)


class PublicDashboardDemoTests(unittest.TestCase):
    def test_examples_match_action_contract(self) -> None:
        schema = json.loads(ACTION_SCHEMA_PATH.read_text(encoding="utf-8"))
        validator = Draft202012Validator(schema, format_checker=FormatChecker())

        for scenario in SCENARIOS.values():
            with self.subTest(action_id=scenario["action"]["action_id"]):
                validator.validate(scenario["action"])

    def test_demo_runs_without_gateway_configuration(self) -> None:
        app = AppTest.from_file(DEMO_APP_PATH).run()

        self.assertFalse(app.exception)
        self.assertEqual(app.title[0].value, "Jev Safety Gate")
        self.assertTrue(
            any("no se conecta al gateway" in item.value.casefold() for item in app.info)
        )

    def test_scenario_selector_shows_policy_examples(self) -> None:
        app = AppTest.from_file(DEMO_APP_PATH).run()
        app.selectbox[0].select("Push directo a main").run()

        self.assertFalse(app.exception)
        self.assertTrue(any(item.value == "deny" for item in app.metric))


if __name__ == "__main__":
    unittest.main()
