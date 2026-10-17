"""Resolución de política: reglas duras configurables + señales probabilísticas JEV."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jev_gate.models.contracts import Action, Verdict


class PolicyEngine:
    def __init__(self, config_path: str | Path | None = None):
        path = Path(config_path) if config_path else Path(__file__).resolve().parents[3] / "docs" / "policy.defaults.json"
        self.config = json.loads(path.read_text(encoding="utf-8"))

    def decide(self, action: Action, features: dict[str, Any], answers: dict[str, dict[str, Any]]) -> tuple[Verdict, list[str]]:
        reasons: list[str] = []
        cls, subtype = action.action_class.value, action.subtype
        if action.dry_run:
            return Verdict(self.config.get("dry_run_verdict", "allow")), ["dry_run"]
        if cls == "email_bulk":
            n = int(features.get("recipient_count", 0))
            thresholds = self.config["email_bulk"]["recipient_count"]
            if n > thresholds["high_gt"]:
                return Verdict.DENY, ["email_recipients_high"]
            if n >= thresholds["low_lt"]:
                reasons.append("email_recipients_medium")
        elif cls == "crm_write":
            n = int(features.get("records_count") or 0)
            thresholds = self.config["crm_write"]["record_count"]
            if n > thresholds["high_gt"]:
                return Verdict.DENY, ["crm_records_high"]
            if n >= thresholds["low_lt"]:
                reasons.append("crm_records_medium")
        elif cls == "social_post":
            reasons.append("social_post_human_review")
        elif cls == "pr_action":
            changed = int(features.get("changed_files", 0))
            if subtype == "push_main" and self.config["pr_action"]["push_main"].get("always") == "deny":
                return Verdict.DENY, ["direct_push_main_denied"]
            if subtype == "merge":
                merge_config = self.config["pr_action"]["merge"]
                if changed > merge_config["deny_changed_files_gt"]:
                    return Verdict.DENY, ["merge_too_many_files"]
                if merge_config.get("default") == "ask":
                    reasons.append("merge_requires_review")
            elif subtype in {"touch_ci", "touch_secrets"} or features.get("touches_ci") or features.get("touches_secrets"):
                reasons.append("critical_files_require_review")
            elif subtype == "delete_files":
                delete_config = self.config["pr_action"]["delete_files"]
                if changed > delete_config["deny_changed_files_gt"]:
                    return Verdict.DENY, ["delete_files_over_limit"]
                if changed < delete_config["ask_changed_files_lt"] or (changed == delete_config["deny_changed_files_gt"] and delete_config.get("five_files") == "ask"):
                    reasons.append("delete_files_review")
            elif subtype == "add_dependency":
                threshold = self.config["pr_action"]["add_dependency"].get("cve_threshold")
                score = features.get("cve_score")
                if threshold is None or score is None:
                    reasons.append("dependency_cve_threshold_unconfigured")
                elif score >= threshold:
                    return Verdict.DENY, ["dependency_cve_threshold_exceeded"]
                else:
                    reasons.append("dependency_requires_review")
            else:
                reasons.append("pr_action_requires_review")

        jev_verdict, jev_reasons = self._jev_signal(action, features, answers)
        reasons.extend(jev_reasons)
        if jev_verdict == Verdict.DENY:
            return Verdict.DENY, reasons
        if reasons or jev_verdict == Verdict.ASK:
            return Verdict.ASK, reasons or ["jev_uncertain"]
        return Verdict.ALLOW, ["within_policy"]

    def _jev_signal(self, action: Action, features: dict[str, Any], answers: dict[str, dict[str, Any]]) -> tuple[Verdict, list[str]]:
        reasons: list[str] = []
        irreversible = action.action_class.value == "email_bulk" or action.subtype in {"merge", "push_main", "touch_secrets"}
        critical_file_review = action.subtype in {"touch_ci", "touch_secrets"} or bool(features.get("touches_ci") or features.get("touches_secrets"))
        confidence = self.config["jev_confidence"]
        class_config = confidence.get(action.action_class.value, {})
        fallback = confidence["irreversible" if irreversible else "reversible"]
        for qid, answer in answers.items():
            if qid == "action_is_irreversible":
                continue
            probs = answer.get("probs", {})
            if qid in {"risk_level", "severity_score"}:
                positive = float(probs.get("critical", probs.get("Critical", 0.0)))
                high = float(probs.get("high", probs.get("High", 0.0)))
                thresholds = class_config.get("critical_risk", fallback)
                if high >= float(fallback["ask_at"]) or critical_file_review:
                    reasons.append("jev_risk_requires_review")
            elif qid == "review_action":
                positive = float(probs.get("flag_for_security_team", 0.0))
                high = float(probs.get("request_changes", 0.0))
                thresholds = class_config.get("flag_for_security_team", fallback)
                request_threshold = class_config.get("request_changes", fallback).get("ask_at", fallback["ask_at"])
                if high >= float(request_threshold):
                    reasons.append("jev_request_changes")
            else:
                positive = float(probs.get("true", 0.0))
                thresholds = class_config.get(qid, fallback)
            deny_at, ask_at = thresholds.get("deny_at"), thresholds.get("ask_at")
            if not critical_file_review and deny_at is not None and positive >= float(deny_at):
                return Verdict.DENY, reasons + [f"jev_{qid}_high_confidence"]
            if ask_at is not None and positive >= float(ask_at):
                reasons.append(f"jev_{qid}_review")
        return (Verdict.ASK, reasons) if reasons else (Verdict.ALLOW, [])
