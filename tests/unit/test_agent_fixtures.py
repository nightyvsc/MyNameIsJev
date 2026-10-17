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
                "mass_communication",
                "crm_write",
                "social_post",
                "repo_merge",
                "repo_push_main",
                "repo_ci_secrets",
                "repo_add_dependency",
                "repo_delete_files",
            },
        )

    def test_repeated_scenario_gets_a_fresh_id_and_timestamp(self) -> None:
        scenario = sales_scenarios()[0]
        first = prepare_action(scenario, dry_run=True)
        second = prepare_action(scenario, dry_run=True)

        self.assertNotEqual(first["id"], second["id"])
        self.assertTrue(first["is_dry_run"])
        self.assertTrue(second["is_dry_run"])
        validate_action(first)
        validate_action(second)


if __name__ == "__main__":
    unittest.main()
