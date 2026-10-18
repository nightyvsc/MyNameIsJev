# GitHub Webhook Relay

Accepts signed GitHub pull-request webhooks, reads the pull-request file list from the
GitHub API, transforms it to the canonical Action v2 contract, then calls the gateway.
By default, GitHub review/comment writes are **disabled**. The relay will only write
when `GITHUB_ENABLE_WRITES=true` and the repository is explicitly allowlisted. This
adapter has local contract tests, but GitHub.com webhook delivery and the full
relay-to-gateway-to-GitHub flow are not yet production-verified.

## Configuration

Set these in the VM3 environment (not in Git):

- `GITHUB_WEBHOOK_SECRET`: webhook HMAC secret.
- `GITHUB_TOKEN`: least-privilege token to read pull request files. Needed to process events.
- `GITHUB_ALLOWED_REPOSITORIES`: comma-separated `owner/repo` allowlist.
- `GATEWAY_BASE_URL`: reachable VM1 base URL.
- `GATE_TOKEN`: gateway token.
- `GITHUB_ENABLE_WRITES`: defaults to false; true enables APPROVE, REQUEST_CHANGES or a
  human-review comment, depending on the gateway verdict.
- `GITHUB_API_URL`: defaults to `https://api.github.com`.

The webhook endpoint requires valid `X-Hub-Signature-256` and
`X-GitHub-Event: pull_request`. Supported PR actions are opened, synchronize, reopened.
The generated action uses `action_class: pr_action`, `subtype: merge`, `dry_run: false`,
and v2 fields (`action_id`, string `actor`, `args`, `payload`, and `created_at`). The
`dry_run` value describes whether the gate should evaluate normal policy; it is
independent of `GITHUB_ENABLE_WRITES`. With GitHub writes disabled, a decision is
recorded but no review/comment is submitted. The current relay does not merge PRs.

## Run

```bash
pip install -e '.[world]'
uvicorn world.github_relay.app:app --host 127.0.0.1 --port 3004
curl -fsS http://127.0.0.1:3004/health
```

The supplied VMs have private RFC1918 addresses. GitHub.com cannot directly reach them;
select and approve a TLS ingress/tunnel or polling design before configuring a webhook.
This ingress is not needed for a dashboard demo that uses synthetic examples.

## Tests

The integration tests validate signature rejection and Action construction without
calling GitHub or the gateway. Real GitHub writes require a separately approved test.
