"""Modelos de datos del contrato v2.0."""
from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ActionClass(StrEnum):
    EMAIL_BULK = "email_bulk"
    CRM_WRITE = "crm_write"
    SOCIAL_POST = "social_post"
    PR_ACTION = "pr_action"


class RiskLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class Verdict(StrEnum):
    ALLOW = "allow"
    ASK = "ask"
    DENY = "deny"


class DecisionStatus(StrEnum):
    PENDING = "pending"
    DECIDED = "decided"
    EXPIRED = "expired"


class Action(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["2.0"]
    action_id: UUID
    action_class: ActionClass
    subtype: str | None = None
    tool: str = Field(min_length=1)
    actor: str = Field(min_length=1)
    args: dict[str, Any]
    recipients: list[str]
    payload: dict[str, Any]
    risk_level: RiskLevel
    dry_run: bool
    created_at: datetime

    @model_validator(mode="before")
    @classmethod
    def subtype_must_be_omitted_when_not_applicable(cls, values: Any) -> Any:
        if isinstance(values, dict) and "subtype" in values and values["subtype"] is None:
            raise ValueError("subtype se omite para clases distintas de pr_action")
        return values

    def model_post_init(self, __context: Any) -> None:
        pr_subtypes = {"merge", "approve", "push_main", "touch_ci", "touch_secrets", "add_dependency", "delete_files"}
        if self.action_class == ActionClass.PR_ACTION and self.subtype not in pr_subtypes:
            raise ValueError("pr_action requiere subtype válido")
        if self.action_class != ActionClass.PR_ACTION and self.subtype is not None:
            raise ValueError("subtype solo se permite para pr_action")


class JEVAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: str
    probs: dict[str, float]
    value: str | float | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)


class Decision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["2.0"] = "2.0"
    action_id: UUID
    status: DecisionStatus
    verdict: Verdict | None = None
    reasons: list[str] = Field(default_factory=list)
    features: dict[str, Any] = Field(default_factory=dict)
    jev_answers: dict[str, JEVAnswer] = Field(default_factory=dict)
    source: str = "jev"
    latency_ms: float = Field(ge=0)
    cost_usd: float = Field(ge=0)
    provider_model: str | None = None
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    decided_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def model_post_init(self, __context: Any) -> None:
        if self.status == DecisionStatus.DECIDED and self.verdict is None:
            raise ValueError("Decision decidida requiere verdict")
        if self.status != DecisionStatus.DECIDED and self.verdict is not None:
            raise ValueError("Decision pendiente/expirada no puede incluir verdict")
        if self.source not in {"jev", "mock"}:
            raise ValueError("source debe ser jev o mock")


class Approval(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["2.0"] = "2.0"
    action_id: UUID
    status: Literal["pending", "approved", "rejected"]
    resolved_by: str | None = None
    resolved_at: datetime | None = None

    def model_post_init(self, __context: Any) -> None:
        resolved = self.resolved_by is not None or self.resolved_at is not None
        if self.status == "pending" and resolved:
            raise ValueError("Approval pending no puede tener resolución")
        if self.status != "pending" and (self.resolved_by is None or self.resolved_at is None):
            raise ValueError("Approval resuelta requiere resolved_by y resolved_at")


class ApprovalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    resolution: Literal["approved", "rejected"]
    resolved_by: str = Field(min_length=1)
