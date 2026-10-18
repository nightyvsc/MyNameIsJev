"""Persistencia SQLite de acciones, decisiones, aprobaciones y eventos append-only."""

from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import UUID

from jev_gate.models.contracts import Action, Approval, Decision, DecisionStatus, Verdict


class AuditStore:
    def __init__(self, path: str | Path = "jev_gate.sqlite3"):
        self.path = str(path)
        self.lock = threading.RLock()
        self._init_db()

    @contextmanager
    def _connect(self):
        conn = sqlite3.connect(self.path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self._connect() as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS actions(action_id TEXT PRIMARY KEY, action_json TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS decisions(action_id TEXT PRIMARY KEY, decision_json TEXT NOT NULL, updated_at TEXT NOT NULL DEFAULT '');
                CREATE TABLE IF NOT EXISTS approvals(action_id TEXT PRIMARY KEY, approval_json TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT '');
                CREATE TABLE IF NOT EXISTS audit_events(id INTEGER PRIMARY KEY AUTOINCREMENT, action_id TEXT NOT NULL, event TEXT NOT NULL, payload_json TEXT NOT NULL, created_at TEXT NOT NULL);
            """)
            for table, column in (("decisions", "updated_at"), ("approvals", "created_at")):
                columns = {row["name"] for row in db.execute(f"PRAGMA table_info({table})")}
                if column not in columns:
                    db.execute(f"ALTER TABLE {table} ADD COLUMN {column} TEXT NOT NULL DEFAULT ''")

    def record(self, action: Action, decision: Decision) -> None:
        with self.lock, self._connect() as db:
            db.execute(
                "INSERT OR REPLACE INTO actions VALUES (?, ?)",
                (str(action.action_id), action.model_dump_json(exclude_none=True)),
            )
            db.execute(
                "INSERT OR REPLACE INTO decisions(action_id,decision_json,updated_at) VALUES (?, ?, ?)",
                (str(action.action_id), decision.model_dump_json(exclude_none=True), _now()),
            )
            db.execute(
                "INSERT INTO audit_events(action_id,event,payload_json,created_at) VALUES(?,?,?,?)",
                (
                    str(action.action_id),
                    "decision",
                    decision.model_dump_json(exclude_none=True),
                    _now(),
                ),
            )
            if decision.verdict and decision.verdict.value == "ask":
                approval = Approval(action_id=action.action_id, status="pending")
                db.execute(
                    "INSERT OR REPLACE INTO approvals(action_id,approval_json,created_at) VALUES (?, ?, ?)",
                    (str(action.action_id), approval.model_dump_json(exclude_none=True), _now()),
                )
                db.execute(
                    "INSERT INTO audit_events(action_id,event,payload_json,created_at) VALUES(?,?,?,?)",
                    (
                        str(action.action_id),
                        "approval_pending",
                        approval.model_dump_json(exclude_none=True),
                        _now(),
                    ),
                )

    def resolve_approval(
        self, action_id: UUID, resolution: str, resolved_by: str
    ) -> Approval | None:
        with self.lock, self._connect() as db:
            row = db.execute(
                "SELECT approval_json FROM approvals WHERE action_id=?", (str(action_id),)
            ).fetchone()
            if row is None:
                return None
            current = Approval.model_validate_json(row["approval_json"])
            if current.status != "pending":
                raise ValueError("La aprobación ya fue resuelta")
            updated = Approval(
                action_id=action_id,
                status=resolution,
                resolved_by=resolved_by,
                resolved_at=datetime.now(timezone.utc),
            )
            db.execute(
                "UPDATE approvals SET approval_json=? WHERE action_id=?",
                (updated.model_dump_json(exclude_none=True), str(action_id)),
            )
            decision_row = db.execute(
                "SELECT decision_json FROM decisions WHERE action_id=?", (str(action_id),)
            ).fetchone()
            if decision_row is not None:
                decision = Decision.model_validate_json(decision_row["decision_json"])
                decision.verdict = Verdict.ALLOW if resolution == "approved" else Verdict.DENY
                decision.status = DecisionStatus.DECIDED
                decision.reasons.append(f"human_{resolution}")
                decision.decided_at = datetime.now(timezone.utc)
                db.execute(
                    "UPDATE decisions SET decision_json=?,updated_at=? WHERE action_id=?",
                    (decision.model_dump_json(exclude_none=True), _now(), str(action_id)),
                )
                db.execute(
                    "INSERT INTO audit_events(action_id,event,payload_json,created_at) VALUES(?,?,?,?)",
                    (
                        str(action_id),
                        "human_verdict",
                        decision.model_dump_json(exclude_none=True),
                        _now(),
                    ),
                )
            db.execute(
                "INSERT INTO audit_events(action_id,event,payload_json,created_at) VALUES(?,?,?,?)",
                (
                    str(action_id),
                    "approval_resolved",
                    updated.model_dump_json(exclude_none=True),
                    _now(),
                ),
            )
            return updated

    def list_decisions(self, limit: int = 100) -> list[Decision]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT decision_json FROM decisions ORDER BY rowid DESC LIMIT ?", (limit,)
            ).fetchall()
        return [Decision.model_validate_json(row[0]) for row in rows]

    def get_decision(self, action_id: UUID) -> Decision | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT decision_json FROM decisions WHERE action_id=?",
                (str(action_id),),
            ).fetchone()
        return Decision.model_validate_json(row[0]) if row is not None else None

    def list_approvals(self, status: str = "pending") -> list[Approval]:
        with self._connect() as db:
            rows = db.execute("SELECT approval_json FROM approvals").fetchall()
        return [
            item for row in rows if (item := Approval.model_validate_json(row[0])).status == status
        ]

    def metrics(self) -> dict[str, Any]:
        decisions = self.list_decisions(100000)
        latencies = sorted(d.latency_ms for d in decisions if d.latency_ms > 0)
        costs = [d.cost_usd for d in decisions]
        counts: dict[str, int] = {"allow": 0, "ask": 0, "deny": 0, "pending": 0, "expired": 0}
        per_class: dict[str, dict[str, int]] = {}
        with self._connect() as db:
            actions = {
                r["action_id"]: Action.model_validate_json(r["action_json"])
                for r in db.execute("SELECT * FROM actions")
            }
        for d in decisions:
            verdict = d.verdict.value if d.verdict else d.status.value
            counts[verdict] = counts.get(verdict, 0) + 1
            action = actions.get(str(d.action_id))
            if action:
                bucket = per_class.setdefault(
                    action.action_class.value, {"allow": 0, "ask": 0, "deny": 0}
                )
                if d.verdict:
                    bucket[d.verdict.value] += 1
        return {
            "total_decisions": len(decisions),
            "verdicts": counts,
            "latency_ms": {
                "p50": _percentile(latencies, 0.50),
                "p95": _percentile(latencies, 0.95),
            },
            "cost_usd": {
                "total": sum(costs),
                "mean_per_decision": sum(costs) / len(costs) if costs else 0.0,
            },
            "block_rate": (len(decisions) - counts["allow"]) / len(decisions) if decisions else 0.0,
            "deny_rate": counts["deny"] / len(decisions) if decisions else 0.0,
            "by_action_class": per_class,
        }

    def has_action(self, action_id: UUID) -> bool:
        with self._connect() as db:
            return (
                db.execute("SELECT 1 FROM actions WHERE action_id=?", (str(action_id),)).fetchone()
                is not None
            )

    def expire_pending(self, jev_ttl_seconds: int = 300, approval_ttl_seconds: int = 3600) -> None:
        """Expira al atender una petición; los vencidos permanecen bloqueados."""
        now = datetime.now(timezone.utc)
        with self.lock, self._connect() as db:
            for row in db.execute(
                "SELECT action_id,decision_json,updated_at FROM decisions"
            ).fetchall():
                decision = Decision.model_validate_json(row["decision_json"])
                if decision.status != DecisionStatus.PENDING or not row["updated_at"]:
                    continue
                if (
                    now - datetime.fromisoformat(row["updated_at"])
                ).total_seconds() >= jev_ttl_seconds:
                    decision.status = DecisionStatus.EXPIRED
                    decision.reasons.append("jev_pending_ttl_expired")
                    decision.decided_at = now
                    db.execute(
                        "UPDATE decisions SET decision_json=?,updated_at=? WHERE action_id=?",
                        (
                            decision.model_dump_json(exclude_none=True),
                            now.isoformat(),
                            row["action_id"],
                        ),
                    )
                    db.execute(
                        "INSERT INTO audit_events(action_id,event,payload_json,created_at) VALUES(?,?,?,?)",
                        (
                            row["action_id"],
                            "jev_pending_expired",
                            decision.model_dump_json(exclude_none=True),
                            now.isoformat(),
                        ),
                    )
            for row in db.execute(
                "SELECT action_id,approval_json,created_at FROM approvals"
            ).fetchall():
                approval = Approval.model_validate_json(row["approval_json"])
                if approval.status != "pending" or not row["created_at"]:
                    continue
                if (
                    now - datetime.fromisoformat(row["created_at"])
                ).total_seconds() >= approval_ttl_seconds:
                    approval.status, approval.resolved_by, approval.resolved_at = (
                        "rejected",
                        "system:approval_ttl",
                        now,
                    )
                    db.execute(
                        "UPDATE approvals SET approval_json=? WHERE action_id=?",
                        (approval.model_dump_json(exclude_none=True), row["action_id"]),
                    )
                    decision_row = db.execute(
                        "SELECT decision_json FROM decisions WHERE action_id=?", (row["action_id"],)
                    ).fetchone()
                    if decision_row:
                        decision = Decision.model_validate_json(decision_row["decision_json"])
                        decision.status, decision.verdict = DecisionStatus.DECIDED, Verdict.DENY
                        decision.reasons.append("approval_ttl_expired")
                        decision.decided_at = now
                        db.execute(
                            "UPDATE decisions SET decision_json=?,updated_at=? WHERE action_id=?",
                            (
                                decision.model_dump_json(exclude_none=True),
                                now.isoformat(),
                                row["action_id"],
                            ),
                        )
                    db.execute(
                        "INSERT INTO audit_events(action_id,event,payload_json,created_at) VALUES(?,?,?,?)",
                        (
                            row["action_id"],
                            "approval_ttl_expired",
                            approval.model_dump_json(exclude_none=True),
                            now.isoformat(),
                        ),
                    )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    index = max(0, min(len(values) - 1, int((len(values) - 1) * fraction + 0.5)))
    return float(values[index])
