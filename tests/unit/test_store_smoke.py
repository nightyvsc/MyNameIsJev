from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from jev_gate.audit.store import AuditStore
from jev_gate.extractor.deterministic import extract_features
from jev_gate.models.contracts import Action, Decision, DecisionStatus, Verdict
from jev_gate.policy.engine import PolicyEngine


class GateCoreSmokeTests(unittest.TestCase):
    def action(self, action_class="email_bulk", subtype=None, recipients=None, args=None, payload=None):
        fields = dict(schema_version="2.0", action_id=uuid4(), action_class=action_class, tool="synthetic_tool", actor="agent-test", args=args or {}, recipients=recipients or [], payload=payload or {"body": "Texto sintético."}, risk_level="medium", dry_run=False, created_at=datetime.now(timezone.utc))
        if subtype is not None:
            fields["subtype"] = subtype
        return Action(**fields)

    def test_extractor_and_policy_thresholds(self):
        policy = PolicyEngine()
        action = self.action(recipients=["a@ejemplo.test"] * 10, payload={"body": "CC 1020304050 3105551234"})
        features = extract_features(action)
        self.assertEqual(features["recipient_count"], 10)
        self.assertTrue(features["has_colombian_id_regex"])
        self.assertTrue(features["has_phone_regex"])
        verdict, _ = policy.decide(action, features, {})
        self.assertEqual(verdict, Verdict.ASK)
        for count, expected in ((9, Verdict.ALLOW), (250, Verdict.ASK), (251, Verdict.DENY)):
            email = self.action(recipients=["x@ejemplo.test"] * count)
            self.assertEqual(policy.decide(email, extract_features(email), {})[0], expected)
        ci = self.action("pr_action", "touch_ci", args={"changed_files": 1})
        answers = {"introduces_security_vulnerability": {"type": "boolean", "probs": {"true": 0.99, "false": 0.01}}}
        self.assertEqual(policy.decide(ci, extract_features(ci), answers)[0], Verdict.ASK)

    def test_approval_resolution_and_pending_ttl(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[2]) as tmp:
            store = AuditStore(Path(tmp) / "audit.sqlite3")
            action = self.action("social_post")
            ask = Decision(action_id=action.action_id, status=DecisionStatus.DECIDED, verdict=Verdict.ASK, latency_ms=12, cost_usd=0)
            store.record(action, ask)
            resolved = store.resolve_approval(action.action_id, "approved", "human-test")
            self.assertEqual(resolved.status, "approved")
            self.assertEqual(store.list_decisions()[0].verdict, Verdict.ALLOW)

            pending_action = self.action()
            pending = Decision(action_id=pending_action.action_id, status=DecisionStatus.PENDING, reasons=["jev_unavailable_pending_ttl"], latency_ms=500, cost_usd=0)
            store.record(pending_action, pending)
            old = (datetime.now(timezone.utc) - timedelta(seconds=10)).isoformat()
            db = sqlite3.connect(store.path)
            try:
                db.execute("UPDATE decisions SET updated_at=? WHERE action_id=?", (old, str(pending_action.action_id)))
                db.commit()
            finally:
                db.close()
            store.expire_pending(1, 3600)
            statuses = {item.action_id: item.status for item in store.list_decisions()}
            self.assertEqual(statuses[pending_action.action_id], DecisionStatus.EXPIRED)
            self.assertGreaterEqual(store.metrics()["total_decisions"], 2)


if __name__ == "__main__":
    unittest.main()
