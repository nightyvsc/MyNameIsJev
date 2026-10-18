"""Valida los ejemplos positivos y negativos del contrato JSON v2.0.

Uso: python docs/validate_contract.py
Requiere: pip install jsonschema
"""
import json
import pathlib
import sys

from jsonschema import Draft202012Validator, FormatChecker

BASE = pathlib.Path(__file__).parent
CASES = [
    ("schemas/action.schema.json", "examples/action_email_bulk.json", True),
    ("schemas/action.schema.json", "examples/action_crm_write.json", True),
    ("schemas/action.schema.json", "examples/action_social_post.json", True),
    ("schemas/action.schema.json", "examples/action_pr_merge.json", True),
    ("schemas/action.schema.json", "examples/action_invalid_missing_pr_subtype.json", False),
    ("schemas/decision.schema.json", "examples/decision_deny.json", True),
    ("schemas/decision.schema.json", "examples/decision_pending.json", True),
    ("schemas/decision.schema.json", "examples/decision_invalid_verdict.json", False),
    ("schemas/approval.schema.json", "examples/approval_pending.json", True),
    ("schemas/approval.schema.json", "examples/approval_invalid_unresolved.json", False),
    ("schemas/action.schema.json", "../contracts/examples/action_email_bulk.json", True),
    ("schemas/decision.schema.json", "examples/decision_allow_v2.json", True),
    ("schemas/decision.schema.json", "examples/decision_ask_v2.json", True),
    ("schemas/decision.schema.json", "examples/decision_deny_mass_email_v2.json", True),
    ("schemas/approval.schema.json", "../contracts/examples/approval_pending.json", True),
]


def load(relative_path):
    return json.loads((BASE / relative_path).read_text(encoding="utf-8"))


def main():
    failed = False
    contracts_schema_dir = BASE.parent / "contracts" / "schemas"
    for schema_name in ("action.schema.json", "decision.schema.json", "approval.schema.json"):
        if load(f"schemas/{schema_name}") != json.loads(
            (contracts_schema_dir / schema_name).read_text(encoding="utf-8")
        ):
            failed = True
            print(f"FAIL schemas/{schema_name}: docs/ y contracts/ no coinciden")
    for schema_path, example_path, should_pass in CASES:
        validator = Draft202012Validator(load(schema_path), format_checker=FormatChecker())
        errors = sorted(
            validator.iter_errors(load(example_path)),
            key=lambda error: list(error.path),
        )
        passed = not errors
        expected = passed == should_pass
        expected_status = "válido" if should_pass else "inválido"
        actual_status = "válido" if passed else "inválido"
        print(
            f"{'OK  ' if expected else 'FAIL'} {example_path}: {actual_status} "
            f"(esperado {expected_status})"
        )
        if not expected:
            failed = True
            for error in errors:
                print(f"  - {error.message}")
    try:
        policy = load("policy.defaults.json")
        questions = load("jev_questions.json")
        classes = {"email_bulk", "crm_write", "social_post", "pr_action"}
        if set(questions.get("classes", {})) != classes:
            raise ValueError("jev_questions.json debe definir exactamente las cuatro clases v2.0")
        if (
            policy.get("schema_version") != "2.0"
            or policy.get("jev", {}).get("pending_ttl_seconds", 0) <= 0
        ):
            raise ValueError("policy.defaults.json requiere versión 2.0 y TTL positivo")
        for action_class, rows in questions["classes"].items():
            seen = set()
            for question in rows:
                if (
                    question.get("type") not in {"boolean", "choice", "score"}
                    or not question.get("id")
                    or question["id"] in seen
                ):
                    raise ValueError(f"Pregunta inválida o id duplicado en {action_class}")
                seen.add(question["id"])
                if question["type"] == "choice" and not question.get("options"):
                    raise ValueError(f"Choice sin options: {action_class}.{question['id']}")
                if question["type"] == "score" and not question.get("levels"):
                    raise ValueError(f"Score sin levels: {action_class}.{question['id']}")
        print("OK   policy.defaults.json y jev_questions.json")
    except (ValueError, KeyError) as error:
        failed = True
        print(f"FAIL configuración: {error}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
