# Synthetic Agents

Three CLI agents generate contract-valid actions and send them to the gateway:

- `agent_sales`: email and CRM scenarios.
- `agent_social`: safe, PII-containing, misleading, and inflammatory post scenarios.
- `agent_devops`: repository merge, CI, secret, dependency, direct-push, and delete scenarios.

No agent executes a simulated side effect unless the gateway returns `allow` and
`--dry-run` was not supplied. The email tool always sends only one synthetic message to
the local SMTP sink; it never contacts an external SMTP server. Repository scenarios do
not run Git commands or alter a real repository.

## Run

```bash
export GATEWAY_BASE_URL='http://<VM1-private-address>:8000'
export GATE_TOKEN='<local-gate-token>'
export WORLD_BASE_URL='http://<VM3-private-address>:3001'
export SOCIAL_BASE_URL='http://<VM3-private-address>:3003'
export MAIL_SMTP_HOST='<VM3-private-address>'
export MAIL_SMTP_PORT=2525

python -m world.agents.agent_sales --count 5 --dry-run
python -m world.agents.agent_social --count 4 --dry-run
python -m world.agents.agent_devops --count 7 --dry-run
```

Replace the quoted address placeholders with the private addresses configured in the
local SSH inventory before running.

Flags: `--interval` seconds between actions, `--count` (0 means infinite),
`--approval-timeout` seconds to poll an `ask` decision, `--dry-run` to prohibit effects.
Tokens should be provided via environment, not command-line arguments, to avoid process
list exposure.

Each fixture is checked against `contracts/schemas/action.schema.json` before sending.
Decision responses are checked against `contracts/schemas/decision.schema.json`.
The gateway token header is `X-Gate-Token`.

Sending actions to the real gateway can incur JEV usage. The Docker Compose profile is
opt-in; agents are not started by the default world Compose command.
