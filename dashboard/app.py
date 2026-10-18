from __future__ import annotations

import os
from typing import Any

import httpx
import streamlit as st

GATEWAY_BASE_URL = os.environ.get("GATEWAY_BASE_URL", "").rstrip("/")
GATE_TOKEN = os.environ.get("GATE_TOKEN", "")
APPROVER_ID = os.environ.get("DASHBOARD_APPROVER_ID", "dashboard-operator")


class GatewayAPIError(RuntimeError):
    pass


def gateway_get(
    path: str, params: dict[str, str | int] | None = None
) -> dict[str, Any] | list[dict[str, Any]]:
    if not GATEWAY_BASE_URL:
        raise GatewayAPIError("GATEWAY_BASE_URL is not configured.")
    if not GATE_TOKEN:
        raise GatewayAPIError("GATE_TOKEN is not configured.")
    try:
        response = httpx.get(
            f"{GATEWAY_BASE_URL}{path}",
            params=params,
            headers={"X-Gate-Token": GATE_TOKEN},
            timeout=8,
        )
        response.raise_for_status()
        result = response.json()
    except httpx.HTTPStatusError as error:
        raise GatewayAPIError(
            f"Gateway returned HTTP {error.response.status_code} for {path}."
        ) from error
    except (httpx.RequestError, ValueError) as error:
        raise GatewayAPIError(
            f"Cannot read {path} from the gateway: {type(error).__name__}."
        ) from error
    if not isinstance(result, (dict, list)):
        raise GatewayAPIError(f"Gateway returned an invalid response for {path}.")
    return result


def gateway_post(path: str, payload: dict[str, Any]) -> dict[str, Any]:
    if not GATEWAY_BASE_URL:
        raise GatewayAPIError("GATEWAY_BASE_URL is not configured.")
    if not GATE_TOKEN:
        raise GatewayAPIError("GATE_TOKEN is not configured.")
    try:
        response = httpx.post(
            f"{GATEWAY_BASE_URL}{path}",
            json=payload,
            headers={"X-Gate-Token": GATE_TOKEN},
            timeout=8,
        )
        response.raise_for_status()
        result = response.json()
    except httpx.HTTPStatusError as error:
        detail = ""
        try:
            detail = str(error.response.json().get("message", ""))
        except ValueError:
            detail = ""
        message = f"Gateway returned HTTP {error.response.status_code} for {path}."
        raise GatewayAPIError(f"{message} {detail}".strip()) from error
    except (httpx.RequestError, ValueError) as error:
        raise GatewayAPIError(
            f"Cannot submit {path} to the gateway: {type(error).__name__}."
        ) from error
    if not isinstance(result, dict):
        raise GatewayAPIError(f"Gateway returned an invalid response for {path}.")
    return result


def _show_gateway_error(error: GatewayAPIError) -> None:
    st.error(str(error))
    st.caption("Check gateway reachability, GATEWAY_BASE_URL, GATE_TOKEN, and the gateway logs.")


def _render_approval_controls(approval: dict[str, Any]) -> None:
    decision_id = approval.get("action_id")
    if not isinstance(decision_id, str):
        return
    with st.form(f"approval-{decision_id}"):
        approver = st.text_input(
            "Aprobador",
            value=APPROVER_ID,
            key=f"approver-{decision_id}",
        )
        approve, reject = st.columns(2)
        submitted_approve = approve.form_submit_button("Approve")
        submitted_reject = reject.form_submit_button("Reject")
    if submitted_approve or submitted_reject:
        if not approver.strip():
            st.error("El identificador del aprobador no puede estar vacío.")
            return
        try:
            result = gateway_post(
                f"/gate/{decision_id}/approve",
                {
                    "resolution": "approved" if submitted_approve else "rejected",
                    "resolved_by": approver.strip(),
                },
            )
        except GatewayAPIError as error:
            _show_gateway_error(error)
        else:
            st.success(f"Decisión actualizada a: {result.get('verdict', 'respuesta recibida')}")
            st.rerun()


@st.fragment(run_every="2s")
def _render_live_feed() -> None:
    try:
        decisions = gateway_get("/decisions", {"limit": 100})
        approvals = gateway_get("/approvals", {"status": "pending"})
    except GatewayAPIError as error:
        _show_gateway_error(error)
        return
    if not isinstance(decisions, list) or not isinstance(approvals, list):
        st.error("La API del gateway no devolvió listas de decisiones y aprobaciones.")
        return
    st.caption(f"{len(decisions)} decisiones recientes · refresco cada 2 s")
    pending_by_id = {
        approval.get("action_id"): approval
        for approval in approvals
        if isinstance(approval.get("action_id"), str)
    }
    rows: list[dict[str, Any]] = []
    for decision in decisions:
        rows.append(
            {
                "timestamp": decision.get("decided_at"),
                "action_id": decision.get("action_id"),
                "status": decision.get("status"),
                "verdict": decision.get("verdict", ""),
                "latency_ms": decision.get("latency_ms"),
                "cost_usd": decision.get("cost_usd"),
            }
        )
    st.dataframe(rows, use_container_width=True, hide_index=True)
    for decision in decisions:
        action_id = decision.get("action_id")
        approval = pending_by_id.get(action_id)
        if approval is not None:
            with st.expander(f"Approval required · {action_id}"):
                st.json(decision)
                _render_approval_controls(approval)


def render_queue() -> None:
    st.subheader("Cola de aprobación")
    try:
        approvals = gateway_get("/approvals", {"status": "pending"})
        decisions = gateway_get("/decisions", {"limit": 1000})
    except GatewayAPIError as error:
        _show_gateway_error(error)
        return
    if not isinstance(approvals, list) or not isinstance(decisions, list):
        st.error("La API del gateway no devolvió listas de aprobaciones y decisiones.")
        return
    st.metric("Pendientes", len(approvals))
    if not approvals:
        st.info("No hay acciones esperando aprobación.")
        return
    decisions_by_id = {decision.get("action_id"): decision for decision in decisions}
    for approval in approvals:
        action_id = approval.get("action_id")
        with st.expander(f"{action_id or 'acción'} · aprobación pendiente"):
            st.json(
                {
                    "approval": approval,
                    "decision": decisions_by_id.get(action_id),
                }
            )
            _render_approval_controls(approval)


@st.fragment(run_every="10s")
def _render_metrics() -> None:
    try:
        metrics = gateway_get("/metrics")
    except GatewayAPIError as error:
        _show_gateway_error(error)
        return
    latency = metrics.get("latency_ms") or {}
    cost = metrics.get("cost_usd") or {}
    verdicts = metrics.get("verdicts") or {}
    first, second, third = st.columns(3)
    first.metric("Decisiones", metrics.get("total_decisions", 0))
    second.metric("Latencia p50", f"{latency.get('p50', 0):.1f} ms")
    third.metric("Latencia p95", f"{latency.get('p95', 0):.1f} ms")
    first, second, third = st.columns(3)
    first.metric("Costo total", f"${cost.get('total', 0):.6f}")
    second.metric("Costo medio", f"${cost.get('mean_per_decision', 0):.6f}")
    third.metric("Tasa de bloqueos", f"{metrics.get('block_rate', 0):.1%}")
    st.subheader("Decisiones por veredicto")
    st.bar_chart({name: verdicts.get(name, 0) for name in ("allow", "ask", "deny", "pending")})


def main() -> None:
    st.set_page_config(page_title="JEV Safety Gate", page_icon="🛡️", layout="wide")
    st.title("JEV Safety Gate")
    st.caption("Panel operativo conectado al gateway; la base de datos permanece en VM1.")
    page = st.sidebar.radio("Vista", ["Feed en vivo", "Cola de aprobación", "Métricas"])
    if page == "Feed en vivo":
        _render_live_feed()
    elif page == "Cola de aprobación":
        render_queue()
    else:
        _render_metrics()


if __name__ == "__main__":
    main()
