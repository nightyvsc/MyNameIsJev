from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from jev_gate.audit.store import AuditStore
from jev_gate.client.jev import Evaluation, JEVUnavailable, JevClient, MockJev
from jev_gate.client.questions import questions_for
from jev_gate.extractor.deterministic import extract_features
from jev_gate.gateway.interceptor import ToolBlocked, ToolInterceptor
from jev_gate.gateway.main import create_app
from jev_gate.models.contracts import Action, ActionClass, Decision, DecisionStatus, Verdict
from jev_gate.policy.engine import PolicyEngine


def make_action(cls="email_bulk", n=2, subtype=None, **overrides):
    fields = dict(schema_version="2.0", action_id=uuid4(), action_class=cls, tool="test_tool", actor="agent-test", args={}, recipients=[f"u{i}@ejemplo.test" for i in range(n)] if cls == "email_bulk" else [], payload={"body": "Contenido sintético."}, risk_level="medium", dry_run=False, created_at=datetime.now(timezone.utc))
    if subtype is not None:
        fields["subtype"] = subtype
    fields.update(overrides)
    return Action(**fields)


def test_extractor_counts_and_detects_colombian_pii_and_diff_flags():
    action = make_action("pr_action", 0, "touch_ci", args={"changed_files": 3, "lines_added": 7, "lines_deleted": 2, "files": [".github/workflows/build.yml", ".env"]}, payload={"diff": "contacto 3105551234 CC 1020304050 password=secret_value_123"})
    features = extract_features(action)
    assert features["changed_files"] == 3
    assert features["diff_lines"] == 9
    assert features["has_colombian_id_regex"]
    assert features["has_phone_regex"]
    assert features["touches_ci"] and features["touches_secrets"]
    assert features["has_secret_pattern"]


@pytest.mark.parametrize("count,expected", [(9, "allow"), (10, "ask"), (250, "ask"), (251, "deny")])
def test_email_recipient_threshold_boundaries(count, expected):
    action = make_action("email_bulk", count)
    verdict, _ = PolicyEngine().decide(action, extract_features(action), {})
    assert verdict.value == expected


@pytest.mark.parametrize("count,expected", [(9, "allow"), (10, "ask"), (500, "ask"), (501, "deny")])
def test_crm_record_threshold_boundaries(count, expected):
    action = make_action("crm_write", 0, args={"record_count": count})
    verdict, _ = PolicyEngine().decide(action, extract_features(action), {})
    assert verdict.value == expected


@pytest.mark.parametrize("subtype,changed,expected", [("merge", 50, "ask"), ("merge", 51, "deny"), ("delete_files", 4, "ask"), ("delete_files", 5, "ask"), ("delete_files", 6, "deny"), ("push_main", 1, "deny"), ("touch_ci", 1, "ask")])
def test_pr_hard_rules(subtype, changed, expected):
    action = make_action("pr_action", 0, subtype, args={"changed_files": changed, "files": ["src/a.py"]})
    verdict, _ = PolicyEngine().decide(action, extract_features(action), {})
    assert verdict.value == expected


def test_social_always_requires_review():
    action = make_action("social_post", 0)
    assert PolicyEngine().decide(action, extract_features(action), {})[0] == Verdict.ASK


def test_touching_ci_stays_ask_even_with_critical_risk_signal():
    action = make_action("pr_action", 0, "touch_ci", args={"changed_files": 1})
    answers = {"introduces_security_vulnerability": {"type": "boolean", "probs": {"true": 0.99, "false": 0.01}}}
    verdict, _ = PolicyEngine().decide(action, extract_features(action), answers)
    assert verdict == Verdict.ASK


def test_mock_returns_complete_typed_answers():
    action = make_action()
    questions = questions_for(action)
    result = asyncio.run(MockJev().evaluate(action, extract_features(action), questions))
    assert set(result.answers) == {q["id"] for q in questions}
    assert all(abs(sum(answer["probs"].values()) - 1) < 0.001 for answer in result.answers.values())


def test_jev_client_timeout_and_retry_failure():
    calls = 0
    async def slow(*args):
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.05)
        return {}
    client = JevClient(slow, timeout_seconds=0.001, retries=1)
    with pytest.raises(JEVUnavailable):
        asyncio.run(client.evaluate(make_action(), {}, questions_for(make_action())))
    assert calls == 2


def test_interceptor_only_executes_allow_decision():
    calls = []
    async def submit(action):
        return Decision(action_id=action.action_id, status="decided", verdict="allow", latency_ms=1, cost_usd=0)
    def tool(value):
        calls.append(value)
        return value.upper()
    result = asyncio.run(ToolInterceptor(submit).call(tool, action_class=ActionClass.EMAIL_BULK, actor="agent", payload={"body": "x"}, value="ok"))
    assert result == "OK" and calls == ["ok"]

    async def deny(action):
        return Decision(action_id=action.action_id, status="decided", verdict="deny", latency_ms=1, cost_usd=0)
    with pytest.raises(ToolBlocked):
        asyncio.run(ToolInterceptor(deny).call(tool, action_class=ActionClass.EMAIL_BULK, actor="agent", value="bad"))
    assert calls == ["ok"]


def test_gateway_pending_approval_audit_and_metrics(tmp_path):
    store = AuditStore(tmp_path / "test.db")
    client = TestClient(create_app(model=MockJev(), store=store))
    action = make_action("social_post", 0).model_dump(mode="json", exclude_none=True)
    response = client.post("/gate", json=action)
    assert response.status_code == 200
    decision = response.json()
    assert decision["verdict"] == "ask"
    approval = client.get("/approvals").json()[0]
    resolved = client.post(f"/gate/{action['action_id']}/approve", json={"resolution": "approved", "resolved_by": "dev-a"})
    assert resolved.status_code == 200 and resolved.json()["status"] == "approved"
    decisions = client.get("/decisions").json()
    assert decisions[0]["verdict"] == "allow"
    assert client.get("/metrics").json()["total_decisions"] == 1


def test_unconfigured_jev_leaves_action_pending(tmp_path):
    client = TestClient(create_app(model=JevClient(None), store=AuditStore(tmp_path / "pending.db")))
    response = client.post("/gate", json=make_action().model_dump(mode="json"))
    assert response.status_code == 200
    assert response.json()["status"] == "pending"
    assert "verdict" not in response.json()
