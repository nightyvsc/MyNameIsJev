# MyNameIsJev

> **AI Safety Gate** — JEV-powered interception, evaluation, and enforcement for autonomous agent actions.

A safety gate that sits between AI agents and high-impact tools. Every action — sending bulk emails, writing to a CRM, posting on social media, merging PRs — passes through this gate before execution. [JEV](https://typesafe.ai) (TypeSafe's System One decision model) evaluates each action in a single structured API call and returns a calibrated verdict: **allow**, **ask**, or **deny**.

Built for the 30X Hackathon.

---

## Table of Contents

- [Why](#why)
- [Architecture](#architecture)
- [Repository Structure](#repository-structure)
- [Contracts](#contracts)
  - [Action Schema](#action-schema)
  - [Decision Schema](#decision-schema)
  - [API Endpoints](#api-endpoints)
  - [Action Classes & Thresholds](#action-classes--thresholds)
  - [JEV Question Sets](#jev-question-sets)
  - [Decision Examples](#decision-examples)
- [Infrastructure](#infrastructure)
- [Quick Start](#quick-start)
- [Configuration](#configuration)
- [Development](#development)
- [Metrics & Observability](#metrics--observability)

---

## Why

Autonomous agents make mistakes. A sales agent might send a promotional email to 10,000 customers. A DevOps agent might push directly to `main`. A social media agent might post something off-brand or misleading.

Traditional guardrails rely on keyword filters or generate long prose explanations that are expensive and slow. **JEV is different**: it evaluates a batched set of typed questions (boolean, choice, score) in a single non-autoregressive pass, returning structured, schema-safe answers with calibrated probabilities — typically in 100–300 ms.

This gate uses JEV as its sole arbiter. The only code that runs locally is:
- A **deterministic extractor** (recipient counts, regex PII detection, diff statistics) for things JEV explicitly cannot do (arithmetic, counting).
- A **policy engine** that maps JEV answers + extractor signals to a verdict using configurable thresholds per action class.

There is **no local model**. JEV is the judge.

---

## Architecture

```
Agent (real or stub)
  │
  └─▶ POST /gate  ──▶  Gateway (VM1)
                          │
                          ├─▶ 1. Deterministic Extractor
                          │       • recipient count
                          │       • regex PII detection
                          │       • diff statistics (files, CI, secrets)
                          │       • action class + base risk level
                          │
                          ├─▶ 2. JEV Client
                          │       • batched typed questions in one HTTP call
                          │       • timeout + 2 retries with backoff
                          │       • on failure → verdict = "pending" (do-nothing)
                          │
                          ├─▶ 3. Policy Engine
                          │       • per-class thresholds → allow / ask / deny
                          │       • deny_immediately rules (before JEV)
                          │       • verdict resolution: deny > ask > allow
                          │
                          ├─▶ 4. SQLite audit log (local persistent volume on VM1)
                          │       • verdict, reasons, JEV answers
                          │       • one writer; consistent backups copied to VM5
                          │
                          └─▶ 5. Human Approval Queue (ask only)
                                  └─▶ Gateway HTTP API ──▶ Streamlit dashboard (VM2)
```

**Verdict semantics:**

| Verdict | Meaning | Agent must... |
|---------|---------|---------------|
| `allow` | Action is safe to proceed | Execute immediately |
| `ask` | Ambiguous; human review required | Wait for `POST /gate/{id}/approve` |
| `deny` | Action is blocked | Abort; do not execute |
| `pending` | JEV unreachable (do-nothing policy) | Wait until TTL expires |

---

## Repository Structure

```
MyNameIsJev/
│
├── contracts/                  # Shared interface contract (C1–C5)
│   ├── schemas/
│   │   ├── action.schema.json      # JSON Schema — Action object
│   │   └── decision.schema.json    # JSON Schema — Decision object
│   ├── examples/
│   │   ├── decision_allow_pr_clean.json
│   │   ├── decision_ask_pr_ci.json
│   │   └── decision_deny_mass_email.json
│   └── openapi.yaml            # OpenAPI 3.1 spec for the Gate API
│
├── config/                     # Runtime-configurable parameters (no redeploy needed)
│   ├── thresholds.yaml         # Per-class thresholds, fail policy, JEV settings
│   └── questions/
│       ├── mass_communication.yaml
│       ├── crm_write.yaml
│       ├── social_post.yaml
│       └── repo_operations.yaml
│
├── src/
│   └── jev_gate/               # Core Python package
│       ├── gateway/            # FastAPI app, routes, middleware
│       ├── extractor/          # Deterministic extractor (counts, regex, diff stats)
│       ├── client/             # JEV API client (HTTP, retry, timeout, mock)
│       ├── policy/             # Policy engine (threshold evaluation, verdict resolution)
│       ├── queue/              # Human approval queue
│       ├── audit/              # Audit log, metrics, export
│       └── models/             # Pydantic models (Action, Decision, etc.)
│
├── tests/
│   ├── unit/                   # Unit tests per module
│   └── integration/            # End-to-end tests with mock JEV
│
├── dashboard/                  # Web dashboard (VM2) — live verdicts, approval queue
├── world/                      # Simulated world (VM3) — fake CRM, mail sink, social API
├── infra/                      # VM provisioning scripts, docker-compose, SSH config
├── data/
│   └── datasets/               # Labeled action datasets for gate evaluation (JSONL)
├── scripts/                    # Dev utilities, dataset generation, benchmarks
├── docs/                       # Extended documentation
│
├── pyproject.toml
├── .env.example
├── .gitignore
└── README.md
```

---

## Contracts

The contract defines the **shared interfaces** between every component. All services — gateway, agents, dashboard, world — communicate exclusively through these schemas.

### Action Schema

**File:** [`contracts/schemas/action.schema.json`](contracts/schemas/action.schema.json)

Every tool call intercepted by the gate is normalized into an `Action` object before evaluation.

#### Top-level fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `id` | `uuid` | ✅ | Unique identifier (UUIDv4) |
| `timestamp` | `date-time` | ✅ | ISO 8601 UTC intercept time |
| `actor` | `Actor` | ✅ | Agent or user that triggered the call |
| `tool` | `string` | ✅ | Name of the tool being called |
| `action_class` | `enum` | ✅ | Determines which JEV question set and thresholds apply |
| `risk_level_base` | `enum` | ✅ | Pre-JEV risk level from the deterministic extractor |
| `is_dry_run` | `boolean` | ✅ | If true, never executed regardless of verdict |
| `payload` | `object` | ✅ | Raw tool call arguments |
| `recipients` | `Recipients` | — | Populated for `mass_communication` and `crm_write` |
| `diff_stats` | `DiffStats` | — | Populated for all `repo_*` classes |
| `pii_flags` | `PIIFlags` | — | Output of the local regex PII detector |
| `context` | `object` | — | Extra metadata (PR title, campaign ID, etc.) |

#### Action classes

| Class | Reversible | Example tool |
|-------|-----------|-------------|
| `mass_communication` | ❌ | `send_email` |
| `crm_write` | ✅ | `upsert_crm_records` |
| `social_post` | ✅ | `post_to_twitter` |
| `repo_merge` | ❌ | `merge_pull_request` |
| `repo_push_main` | ❌ | `git_push` (to main) |
| `repo_ci_secrets` | ❌ | `modify_workflow` |
| `repo_add_dependency` | ✅ | `npm_install`, `pip_install` |
| `repo_delete_files` | ❌ | `delete_files` |

> **Irreversibility rule:** An action is irreversible if it cannot be fully undone by the actor after execution. A sent email is irreversible. A deleted social media post is reversible. A merge to `main` is irreversible even if a revert commit is possible.

<details>
<summary>Minimal valid Action example</summary>

```json
{
  "id": "a1b2c3d4-0000-4000-8000-000000000001",
  "timestamp": "2026-10-17T17:00:00Z",
  "actor": {
    "id": "agent-sales-001",
    "type": "agent",
    "name": "Sales Automation Agent"
  },
  "tool": "send_email",
  "action_class": "mass_communication",
  "risk_level_base": "high",
  "is_dry_run": false,
  "recipients": {
    "total_count": 500,
    "internal_count": 50,
    "external_count": 450,
    "includes_high_risk_roles": false
  },
  "pii_flags": {
    "contains_email": true,
    "contains_phone": false,
    "contains_national_id": false,
    "contains_credit_card": false,
    "contains_iban": false,
    "pii_fields": ["to", "body"]
  },
  "payload": {
    "subject": "Q4 Promotion — Act Now",
    "body": "Dear customer...",
    "to": ["customer1@example.com"]
  }
}
```
</details>

---

### Decision Schema

**File:** [`contracts/schemas/decision.schema.json`](contracts/schemas/decision.schema.json)

The gate's response to every `Action`. Contains the verdict, all reasons, the raw JEV answer map, and the latency breakdown.

#### Top-level fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `id` | `uuid` | ✅ | Decision identifier |
| `action_id` | `uuid` | ✅ | Links back to the evaluated Action |
| `timestamp` | `date-time` | ✅ | ISO 8601 decision time |
| `verdict` | `enum` | ✅ | `allow` / `ask` / `deny` / `pending` |
| `policy_reasons` | `PolicyReason[]` | ✅ | Ordered list of reasons driving the verdict |
| `jev_response` | `JEVResponse` | ✅ | Raw JEV answer map + model + call ID |
| `latency_ms` | `LatencyBreakdown` | ✅ | `total_ms`, `extractor_ms`, `jev_ms`, `policy_ms` |
| `cost_usd` | `number` | ✅ | Estimated USD cost of the JEV call |
| `human_approval` | `HumanApproval` | — | Populated after a human acts on an `ask` |
| `ttl_expires_at` | `date-time` | — | Only for `pending`; after this → auto-deny |

#### Verdict resolution

```
deny_immediately rules → DENY (never calls JEV)
     ↓
JEV block signals  → DENY
     ↓
JEV ask signals    → ASK
     ↓
JEV allow (default) → ALLOW
```

A single `severity: block` reason is sufficient to deny, regardless of other signals.

<details>
<summary>Decision examples</summary>

- **deny** — mass email, misleading content: [`decision_deny_mass_email.json`](contracts/examples/decision_deny_mass_email.json)
- **ask** — PR merge touching CI pipeline: [`decision_ask_pr_ci.json`](contracts/examples/decision_ask_pr_ci.json)
- **allow** — clean PR merge: [`decision_allow_pr_clean.json`](contracts/examples/decision_allow_pr_clean.json)

</details>

---

### API Endpoints

**Full spec:** [`contracts/openapi.yaml`](contracts/openapi.yaml)

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/gate` | Evaluate an intercepted action → returns a Decision |
| `GET` | `/gate/{decision_id}` | Retrieve a decision by ID |
| `POST` | `/gate/{decision_id}/approve` | Human approval or rejection for an `ask` verdict |
| `GET` | `/queue` | List all decisions awaiting human approval |
| `GET` | `/audit/log` | Query the append-only audit log |
| `GET` | `/audit/metrics` | Aggregated metrics (p50/p95 latency, cost, block rate) |
| `GET` | `/health` | Gateway + JEV reachability health check |

All endpoints require `Authorization: Bearer <GATE_TOKEN>` (internal token, not the JEV API key).

---

### Action Classes & Thresholds

**File:** [`config/thresholds.yaml`](config/thresholds.yaml)

All thresholds are runtime-configurable. No redeployment needed.

#### Recipient count thresholds (industry baselines: NIST / ISO 27001 / Microsoft DLP)

| Action class | Low (allow hint) | Medium (ask hint) | High (deny hint) |
|-------------|-----------------|-------------------|-----------------|
| `mass_communication` | ≤ 9 | 10–249 | ≥ 250 (> 1000 → immediate deny) |
| `crm_write` | ≤ 9 records | 10–499 | ≥ 500 |

#### `deny_immediately` rules (never reach JEV)

| Action class | Condition | Reason code |
|-------------|-----------|-------------|
| `mass_communication` | recipients > 1000 | `RECIPIENT_COUNT_CRITICAL` |
| `mass_communication` | credit card or IBAN in payload | `PII_CRITICAL_FIELD` |
| `repo_push_main` | **always** | `DIRECT_PUSH_TO_MAIN_PROHIBITED` |
| `repo_merge` | `diff_stats.touches_secrets == true` | `TOUCHES_SECRETS` |
| `repo_merge` | `files_changed > 50` | `DIFF_SIZE_EXCESSIVE` |
| `repo_delete_files` | `files_changed > 5` | `BULK_DELETE_EXCESSIVE` |

---

### JEV Question Sets

**Directory:** [`config/questions/`](config/questions/)

Each action class has a dedicated question set. All questions are batched into a **single JEV API call** per action.

| File | Classes served | Questions |
|------|---------------|-----------|
| `mass_communication.yaml` | `mass_communication` | `action_is_irreversible`, `content_contains_pii`, `content_is_misleading`, `content_is_off_brand`, `risk_level` |
| `crm_write.yaml` | `crm_write` | `content_contains_pii`, `content_is_misleading`, `risk_level` |
| `social_post.yaml` | `social_post` | `content_contains_pii`, `content_is_misleading`, `content_is_off_brand`, `content_is_inflammatory`, `risk_level` |
| `repo_operations.yaml` | `repo_merge`, `repo_ci_secrets`, `repo_add_dependency`, `repo_delete_files` | `introduces_security_vulnerability`, `contains_secret_leak`, `has_breaking_api_change`, `adds_unreviewed_dependency`, `code_quality_tier`, `review_action`, `severity_score` |

---

## Infrastructure

6 private VMs administered via SSH. The addresses span multiple private subnets, so
VM-to-VM routing and firewall paths must be validated rather than inferred from operator
SSH access.

| VM | Role | Why it has a separate VM |
|----|------|----|
| VM1 (`10.43.99.216`, Ubuntu) | Gateway + policy engine + local SQLite | Keeps the decision path and authoritative audit store together; no network DB dependency in the critical path. |
| VM2 (`10.43.100.175`, Ubuntu) | Streamlit dashboard | Separates operator UI from the gate; reads and approves only through the gateway API. |
| VM3 (`10.43.99.199`, Ubuntu) | Simulated world: CRM, mail sink, social API, GitHub relay | Contains side effects and test integrations so they cannot bypass the gate or share the gateway process. |
| VM4 (`10.43.99.206`, Ubuntu) | Simulated agents | Generates concurrent test actions independently, so load can be adjusted without changing the gateway. |
| VM5 (`10.43.97.73`, Rocky Linux) | SQLite backup storage and recovery tests (not a live database) | Keeps recoverable copies off the gateway host; it is a backup target, not a database cluster node. |
| VM6 (`10.43.97.69`, Rocky Linux) | Load tests / CI / optional host monitoring | Runs bursty operational jobs away from VM1; optional services depend on measured capacity. |

Provisioning scripts: [`infra/`](infra/)

The deployment sequence, exact port policy, per-host configuration, and Mermaid flow
diagram are in [`infra/DEPLOYMENT_PLAN.md`](infra/DEPLOYMENT_PLAN.md). The ignored root
`.env` is a local worksheet containing private IPs and empty secret slots; it must not
be copied wholesale to all VMs.

### Request flow

1. An agent on VM4 or the GitHub relay on VM3 submits an `Action` to `POST /gate` on VM1.
2. VM1 validates the action, extracts deterministic signals, calls JEV over HTTPS, and computes the policy verdict.
3. VM1 writes the action, verdict, JEV response, and approval-queue state to its local persistent SQLite database. SQLite is single-writer here; it is not mounted over the network or opened by the dashboard.
4. The gateway returns `allow`, `ask`, `deny`, or `pending`. An immediate `allow` permits the caller to continue to VM3; for `ask`, the caller must wait for approval and resume only after confirming the updated decision. `deny` and `pending` never execute the effect.
5. The Streamlit dashboard on VM2 polls the gateway's HTTP audit/queue/metrics endpoints. Human approve/reject actions are sent back to VM1, which updates SQLite.
6. VM1 creates a consistent SQLite backup and transfers it to VM5 over SSH/SFTP. VM5 is for recovery, not live reads/writes.
7. VM6 can generate load or run CI on demand. Optional monitoring runs only after confirming the hosts have sufficient capacity.

The distribution is justified by isolating failure domains and side effects, letting the agents/load tests vary independently from the gateway, and separating backups from the active audit store. It does **not** mean that one synchronous JEV decision is split among machines, and the current design does not provide automatic failover. A queue, gateway replicas, or Ray workers remain future options and require measured need; gateway active-active is incompatible with the current single-writer SQLite design.

Persona B's simulated world, agents, Streamlit dashboard, backup utility, and support
deployment scripts are separate from the gateway implementation. See
[`world/agents/README.md`](world/agents/README.md),
[`dashboard/README.md`](dashboard/README.md), and [`infra/README.md`](infra/README.md)
for their runbooks. The support deployment scripts have not been run against the VMs.

---

## Quick Start

```bash
# 1. Clone and enter the repo
git clone https://github.com/your-org/MyNameIsJev.git
cd MyNameIsJev

# 2. Set up environment
cp .env.example .env
# Edit .env and set TYPESAFE_API_KEY and GATE_TOKEN

# 3. Install dependencies
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# 4. Run the gateway
uvicorn jev_gate.gateway.main:app --reload --port 8000

# 5. Check health
curl http://localhost:8000/health

# 6. Submit a test action (dry-run)
curl -X POST http://localhost:8000/gate \
  -H "Authorization: Bearer changeme-dev-token" \
  -H "Content-Type: application/json" \
  -d @contracts/examples/decision_deny_mass_email.json
```

### Real TypeSafe API smoke test

For an intentional, one-request connectivity check against the provider, put
`TYPESAFE_API_KEY` in the ignored root `.env` file and run:

```bash
python scripts/test_jev_api.py --confirm
```

The command sends synthetic data only, rejects non-official endpoints, does not retry,
and may incur API usage charges. It has not been run without a locally configured key.
See [`scripts/README.md`](scripts/README.md) for details.

---

## Configuration

The entire policy is driven by [`config/thresholds.yaml`](config/thresholds.yaml). Key settings:

| Setting | Default | Description |
|---------|---------|-------------|
| `fail_policy` | `do_nothing` | What to do when JEV is unreachable |
| `pending_ttl_seconds` | `300` | After this, pending actions auto-deny |
| `jev_timeout_seconds` | `10` | JEV HTTP call timeout |
| `jev_max_retries` | `2` | Retries before marking as pending |
| `jev_model` | `jev-1.14` | JEV model version |

All per-class thresholds and `deny_immediately` rules are also in this file.

---

## Development

```bash
# Run tests
pytest

# Run tests with coverage
pytest --cov=src/jev_gate --cov-report=term-missing

# Lint and format
ruff check src/ tests/
ruff format src/ tests/

# Type check
mypy src/
```

To develop without a real JEV API key, the mock JEV server (task B7) can be run locally:

```bash
python scripts/mock_jev_server.py --port 9000
# Then set JEV_BASE_URL=http://localhost:9000 in .env

# Verify the mock HTTP endpoint
python -m unittest tests.unit.test_mock_jev_server
```

---

## Metrics & Observability

The gate exposes metrics at `GET /audit/metrics`:

| Metric | Target |
|--------|--------|
| False positive rate | ≤ 10% |
| Cost per decision (mean) | ≤ $0.001 |
| Recall of dangerous actions | ≥ 85% |
| Latency p95 (end-to-end) | < 800 ms |

Prometheus-compatible metrics are also exposed at `/metrics` for scraping by VM2's dashboard.

---

## License

MIT
