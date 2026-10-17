from world.agents.runner import devops_scenarios, run_agent, validate_fixture_scenarios

SCENARIOS = devops_scenarios()
validate_fixture_scenarios(SCENARIOS)


if __name__ == "__main__":
    raise SystemExit(run_agent("devops", SCENARIOS))
