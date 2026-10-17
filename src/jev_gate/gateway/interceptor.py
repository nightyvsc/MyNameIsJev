"""A1: middleware para proteger la ejecución de una tool simulada."""
from __future__ import annotations

import inspect
from functools import wraps
from typing import Any, Callable
from datetime import datetime, timezone
from uuid import uuid4

from jev_gate.models.contracts import Action, ActionClass, Decision, DecisionStatus, Verdict


class ToolBlocked(RuntimeError):
    def __init__(self, decision: Decision):
        self.decision = decision
        super().__init__(f"Tool detenida por gate: {decision.verdict or decision.status}")


class ApprovalRequired(ToolBlocked):
    """La tool queda en cola humana y no se ejecuta todavía."""


class ActionPending(ToolBlocked):
    """JEV no respondió; no ejecutar hasta que llegue un resultado."""


class ToolDenied(ToolBlocked):
    """El gate denegó definitivamente la tool."""


class ToolInterceptor:
    def __init__(self, submit_action: Callable[[Action], Any]):
        self.submit_action = submit_action

    async def call(self, tool: Callable[..., Any], *, action_class: ActionClass, actor: str, tool_name: str | None = None, subtype: str | None = None, recipients: list[str] | None = None, dry_run: bool = False, payload: dict[str, Any] | None = None, args: dict[str, Any] | None = None, _execution_kwargs: dict[str, Any] | None = None, _execution_args: tuple[Any, ...] = (), **tool_kwargs: Any) -> Any:
        fields = {"schema_version": "2.0", "action_id": uuid4(), "action_class": action_class, "tool": tool_name or tool.__name__, "actor": actor, "args": args or tool_kwargs, "recipients": recipients or [], "payload": payload or tool_kwargs, "risk_level": "medium", "dry_run": dry_run, "created_at": datetime.now(timezone.utc)}
        if subtype is not None:
            fields["subtype"] = subtype
        action = Action(**fields)
        decision = self.submit_action(action)
        if inspect.isawaitable(decision):
            decision = await decision
        if decision.status == DecisionStatus.PENDING or decision.status == DecisionStatus.EXPIRED:
            raise ActionPending(decision)
        if decision.verdict == Verdict.ASK:
            raise ApprovalRequired(decision)
        if decision.verdict == Verdict.DENY:
            raise ToolDenied(decision)
        if decision.status != DecisionStatus.DECIDED or decision.verdict != Verdict.ALLOW:
            raise ToolBlocked(decision)
        result = tool(*_execution_args, **(_execution_kwargs if _execution_kwargs is not None else tool_kwargs))
        return await result if inspect.isawaitable(result) else result

    def protect(self, *, action_class: ActionClass, actor: str, tool_name: str | None = None, subtype: str | None = None, recipient_arg: str | None = None):
        """Decorador que intercepta kwargs; mapear payloads complejos con `call` explícito."""
        def decorator(tool: Callable[..., Any]):
            @wraps(tool)
            async def wrapped(*tool_args: Any, **kwargs: Any):
                bound = inspect.signature(tool).bind_partial(*tool_args, **kwargs).arguments
                recipients = bound.get(recipient_arg, []) if recipient_arg else []
                payload = {k: v for k, v in bound.items() if k != recipient_arg}
                return await self.call(tool, action_class=action_class, actor=actor, tool_name=tool_name, subtype=subtype, recipients=recipients, payload=payload, args=bound, _execution_kwargs=kwargs, _execution_args=tool_args)
            return wrapped
        return decorator
