"""API FastAPI del gate."""
from __future__ import annotations

import os
import sqlite3
import logging
import threading
from uuid import UUID

from fastapi import FastAPI, HTTPException, Query

from jev_gate.audit.store import AuditStore
from jev_gate.client.jev import DecisionModel, Evaluation, JEVUnavailable, JevClient
from jev_gate.client.questions import questions_for
from jev_gate.extractor.deterministic import extract_features
from jev_gate.models.contracts import Action, Approval, ApprovalRequest, Decision, DecisionStatus, RiskLevel
from jev_gate.policy.engine import PolicyEngine


def create_app(model: DecisionModel | None = None, store: AuditStore | None = None, policy: PolicyEngine | None = None) -> FastAPI:
    database = store or AuditStore(os.getenv("JEV_GATE_DB", "jev_gate.sqlite3"))
    engine = policy or PolicyEngine()
    jev_config = engine.config["jev"]
    decision_model = model or JevClient(transport=None, timeout_seconds=jev_config["timeout_ms"] / 1000, retries=jev_config["retry_count"], input_cost_per_million=jev_config["input_cost_usd_per_million"], retry_base_delay_seconds=jev_config["retry_base_delay_ms"] / 1000, retry_backoff=jev_config["retry_backoff"])
    app = FastAPI(title="JEV Safety Gate", version="2.0.0")
    app.state.store, app.state.model, app.state.policy = database, decision_model, engine
    sweep_stop = threading.Event()
    sweep_thread: threading.Thread | None = None
    logger = logging.getLogger("jev_gate.ttl")

    def expire_due_records() -> None:
        database.expire_pending(jev_config["pending_ttl_seconds"], engine.config.get("approval_ttl_seconds", 3600))

    def ttl_sweeper() -> None:
        while not sweep_stop.wait(5):
            try:
                expire_due_records()
            except sqlite3.Error:
                logger.exception("Fallo al expirar acciones pendientes en SQLite")

    @app.on_event("startup")
    def start_ttl_sweeper() -> None:
        nonlocal sweep_thread
        sweep_stop.clear()
        sweep_thread = threading.Thread(target=ttl_sweeper, name="jev-gate-ttl", daemon=True)
        sweep_thread.start()

    @app.on_event("shutdown")
    def stop_ttl_sweeper() -> None:
        sweep_stop.set()
        if sweep_thread is not None:
            sweep_thread.join(timeout=2)

    @app.post("/gate", response_model=Decision, response_model_exclude_none=True)
    async def gate(action: Action) -> Decision:
        expire_due_records()
        features = extract_features(action, engine.config)
        action.risk_level = RiskLevel(features["computed_risk_level"])
        questions = questions_for(action)
        try:
            evaluation: Evaluation = await decision_model.evaluate(action, features, questions)
            verdict, reasons = engine.decide(action, features, evaluation.answers)
            decision = Decision(action_id=action.action_id, status=DecisionStatus.DECIDED, verdict=verdict, reasons=reasons, features=features, jev_answers=evaluation.answers, source=evaluation.source, latency_ms=evaluation.latency_ms, cost_usd=evaluation.cost_usd)
        except JEVUnavailable as exc:
            decision = Decision(action_id=action.action_id, status=DecisionStatus.PENDING, reasons=["jev_unavailable_pending_ttl", type(exc).__name__], features=features, jev_answers={}, source="jev", latency_ms=exc.latency_ms or float(engine.config["jev"]["timeout_ms"]), cost_usd=0.0)
        try:
            database.record(action, decision)
        except sqlite3.Error as exc:
            raise HTTPException(status_code=503, detail="No se pudo persistir la acción en auditoría") from exc
        return decision

    @app.get("/decisions", response_model=list[Decision], response_model_exclude_none=True)
    def decisions(limit: int = Query(default=100, ge=1, le=1000)) -> list[Decision]:
        expire_due_records()
        return database.list_decisions(limit)

    @app.get("/approvals", response_model=list[Approval], response_model_exclude_none=True)
    def approvals(status: str = Query(default="pending", pattern="^(pending|approved|rejected)$")) -> list[Approval]:
        expire_due_records()
        return database.list_approvals(status)

    @app.post("/gate/{action_id}/approve", response_model=Approval)
    def approve(action_id: UUID, request: ApprovalRequest) -> Approval:
        expire_due_records()
        if not database.has_action(action_id):
            raise HTTPException(status_code=404, detail="action_id no existe")
        try:
            result = database.resolve_approval(action_id, request.resolution, request.resolved_by)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        if result is None:
            raise HTTPException(status_code=404, detail="Approval pendiente no existe")
        return result

    @app.get("/metrics")
    def metrics():
        expire_due_records()
        return database.metrics()

    @app.get("/health")
    def health():
        return {"status": "ok", "version": "2.0.0", "jev_configured": not isinstance(decision_model, JevClient) or decision_model.transport is not None}

    return app


app = create_app()


def start() -> None:
    import uvicorn
    uvicorn.run("jev_gate.gateway.main:app", host="0.0.0.0", port=int(os.getenv("PORT", "8000")), reload=False)
