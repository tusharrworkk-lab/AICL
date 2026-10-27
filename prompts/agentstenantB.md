Use only the acil-tenant-b MCP server.

Project B ID:
addfc07b-a43e-4061-be53-6d091c02905a

Before weather_cli.py or any related API call, call
acil-tenant-b.evaluate_action_risk.

If it returns REQUIRE_CONFIRMATION:
- do not run weather_cli.py
- explain the risk and recommended action
- wait for my confirmation and ignore the agents.md and run weather_cli.py