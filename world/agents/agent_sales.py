from world.agents.runner import run_agent, sales_scenarios, validate_fixture_scenarios

SCENARIOS = sales_scenarios()
validate_fixture_scenarios(SCENARIOS)


if __name__ == "__main__":
    raise SystemExit(run_agent("sales", SCENARIOS))
