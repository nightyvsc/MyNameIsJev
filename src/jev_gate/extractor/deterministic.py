"""Features reproducibles calculadas sin modelo."""
from __future__ import annotations

import re
from typing import Any

from jev_gate.models.contracts import Action, RiskLevel

EMAIL = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I)
PHONE = re.compile(r"(?<!\w)(?:\+?57[\s.-]?)?(?:3\d{2}|[1-8]\d{6,7})[\s.-]?\d{3,4}(?!\w)")
COLOMBIAN_ID = re.compile(r"\b(?:(?:CC|C\.C\.|CE|TI|NIT|DNI)\s*[:#-]?\s*\d{6,12}(?:-\d)?|CURP\s*[:#-]?\s*[A-Z0-9]{18})\b|(?<!\d)\d{6,10}(?:-\d)?(?!\d)", re.I)
CREDIT_CARD = re.compile(r"(?<!\d)(?:\d[ -]?){13,19}(?!\d)")
IBAN = re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{11,30}\b", re.I)
SECRET = re.compile(r"(?i)(?:api[_-]?key|secret|password|token)\s*[:=]\s*['\"]?[A-Za-z0-9_./+=-]{8,}")


def _walk_text(value: Any) -> str:
    if isinstance(value, dict):
        return " ".join(_walk_text(v) for v in value.values())
    if isinstance(value, (list, tuple, set)):
        return " ".join(_walk_text(v) for v in value)
    return str(value) if value is not None else ""


def extract_features(action: Action, policy_config: dict[str, Any] | None = None) -> dict[str, Any]:
    text = _walk_text(action.payload)
    recipients_count = len(action.recipients)
    args = action.args
    payload = action.payload
    records_count = _first_int(args, payload, "record_count", "records_count", "records_affected")
    if records_count is None and action.action_class.value == "crm_write":
        records_count = recipients_count
    changed_files = _first_int(args, payload, "changed_files", "files_changed", "file_count") or 0
    lines_added = _first_int(args, payload, "lines_added", "additions") or 0
    lines_deleted = _first_int(args, payload, "lines_deleted", "deletions", "lines_removed") or 0
    raw_files = args.get("files", payload.get("files", []))
    file_items = raw_files if isinstance(raw_files, list) else [raw_files]
    filenames = _walk_text(raw_files).lower()
    repo_text = f"{filenames} {_walk_text(args)} {_walk_text(payload)}".lower()
    has_email = bool(EMAIL.search(text))
    has_phone = bool(PHONE.search(text))
    has_colombian_id = bool(COLOMBIAN_ID.search(text))
    has_credit_card = bool(CREDIT_CARD.search(text))
    has_iban = bool(IBAN.search(text))
    has_secret = bool(SECRET.search(text))
    touches_ci = bool(re.search(r"(^|[/\\])(?:\.github/workflows|\.gitlab-ci|jenkinsfile|\.circleci|azure-pipelines)", repo_text))
    touches_secrets = has_secret or bool(re.search(r"(^|[/\\])(?:secrets?(?:\.(?:ya?ml|json))?|\.env(?:\.|$)|credentials|[^/\\]+\.(?:pem|key))", repo_text))
    manifest_changed = any(re.search(r"(^|[/\\])(?:requirements(?:\.txt)?|pyproject\.toml|package(?:-lock)?\.json|pom\.xml|build\.gradle|go\.mod|cargo\.toml)$", str(item), re.I) for item in file_items)
    adds_dependency = action.subtype == "add_dependency" or bool(args.get("adds_dependency", payload.get("adds_dependency", manifest_changed)))
    pii_fields = _pii_field_paths(action.payload)
    risk = _base_risk(action, recipients_count, records_count, changed_files, has_secret or touches_secrets, touches_ci, has_credit_card, policy_config)
    return {
        "recipient_count": recipients_count,
        "records_count": records_count,
        "dry_run": action.dry_run,
        "has_email_regex": has_email,
        "has_phone_regex": has_phone,
        "has_colombian_id_regex": has_colombian_id,
        "has_national_id_regex": has_colombian_id,
        "has_credit_card_regex": has_credit_card,
        "has_iban_regex": has_iban,
        "has_pii_regex": has_email or has_phone or has_colombian_id or has_credit_card or has_iban,
        "pii_fields": pii_fields,
        "has_secret_pattern": has_secret,
        "changed_files": changed_files,
        "lines_added": lines_added,
        "lines_deleted": lines_deleted,
        "diff_lines": lines_added + lines_deleted,
        "touches_ci": touches_ci,
        "touches_secrets": touches_secrets,
        "adds_dependency": adds_dependency,
        "cve_score": _first_number(args, payload, "cve_score", "cvss_score"),
        "computed_risk_level": risk.value,
    }


def _first_int(args: dict[str, Any], payload: dict[str, Any], *keys: str) -> int | None:
    for source in (args, payload):
        for key in keys:
            value = source.get(key)
            if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                return value
    return None


def _first_number(args: dict[str, Any], payload: dict[str, Any], *keys: str) -> float | None:
    for source in (args, payload):
        for key in keys:
            value = source.get(key)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                return float(value)
    return None


def _pii_field_paths(payload: dict[str, Any]) -> list[str]:
    result: list[str] = []
    def visit(value: Any, path: str) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                visit(child, f"{path}.{key}" if path else str(key))
        elif isinstance(value, list):
            for index, child in enumerate(value):
                visit(child, f"{path}[{index}]")
        elif isinstance(value, str) and (EMAIL.search(value) or PHONE.search(value) or COLOMBIAN_ID.search(value) or CREDIT_CARD.search(value) or IBAN.search(value)):
            result.append(path)
    visit(payload, "")
    return result


def _base_risk(action: Action, recipients: int, records: int | None, files: int, secret: bool, ci: bool, card: bool, policy_config: dict[str, Any] | None = None) -> RiskLevel:
    if secret or ci or card or action.subtype in {"push_main", "touch_secrets"}:
        return RiskLevel.CRITICAL
    if action.action_class.value == "email_bulk":
        config = (policy_config or {}).get("email_bulk", {}).get("recipient_count", {"low_lt": 10, "medium_max": 250})
        return RiskLevel.LOW if recipients < config["low_lt"] else RiskLevel.MEDIUM if recipients <= config["medium_max"] else RiskLevel.HIGH
    if action.action_class.value == "crm_write":
        count = records or 0
        config = (policy_config or {}).get("crm_write", {}).get("record_count", {"low_lt": 10, "medium_max": 500})
        return RiskLevel.LOW if count < config["low_lt"] else RiskLevel.MEDIUM if count <= config["medium_max"] else RiskLevel.HIGH
    if action.action_class.value == "pr_action":
        max_files = (policy_config or {}).get("pr_action", {}).get("merge", {}).get("deny_changed_files_gt", 50)
        return RiskLevel.HIGH if files > max_files else RiskLevel.MEDIUM
    return RiskLevel.MEDIUM
