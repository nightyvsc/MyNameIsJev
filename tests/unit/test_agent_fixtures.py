from __future__ import annotations

import unittest

from world.agents.runner import (
    devops_scenarios,
    prepare_action,
    sales_scenarios,
    social_scenarios,
    validate_action,
)


class AgentFixtureTests(unittest.TestCase):
    def test_all_agents_generate_contract_valid_actions_for_all_classes(self) -> None:
        actions = sales_scenarios() + social_scenarios() + devops_scenarios()
        for action in actions:
            with self.subTest(tool=action["tool"], action_class=action["action_class"]):
                validate_action(action)

        self.assertEqual(
            {action["action_class"] for action in actions},
            {
                "email_bulk",
                "crm_write",
                "social_post",
                "pr_action",
            },
        )
        self.assertTrue(
            all("subtype" in action for action in actions if action["action_class"] == "pr_action")
        )

    def test_repeated_scenario_gets_a_fresh_id_and_timestamp(self) -> None:
        scenario = sales_scenarios()[0]
        first = prepare_action(scenario, dry_run=True)
        second = prepare_action(scenario, dry_run=True)

        self.assertNotEqual(first["action_id"], second["action_id"])
        self.assertTrue(first["dry_run"])
        self.assertTrue(second["dry_run"])
        validate_action(first)
        validate_action(second)


if __name__ == "__main__":
    unittest.main()
