from world.agents.runner import run_agent, social_scenarios, validate_fixture_scenarios

SCENARIOS = social_scenarios()
validate_fixture_scenarios(SCENARIOS)


if __name__ == "__main__":
    raise SystemExit(run_agent("social", SCENARIOS))
