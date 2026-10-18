"""Valida cada Action del JSONL contra el contrato Draft 2020-12."""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = json.loads((ROOT / "docs/schemas/action.schema.json").read_text(encoding="utf-8"))
VALIDATOR = Draft202012Validator(SCHEMA, format_checker=FormatChecker())


def validate(path: Path) -> tuple[int, Counter[str]]:
    labels: Counter[str] = Counter()
    total = 0
    errors = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        row = json.loads(line)
        total += 1
        if row.get("label") not in {"safe", "dangerous", "ambiguous"} or row.get("expected") not in {"allow", "ask", "deny"} or not row.get("reason"):
            errors.append(f"línea {line_number}: faltan label/expected/reason válidos")
        labels[row.get("label", "missing")] += 1
        for error in VALIDATOR.iter_errors(row.get("action")):
            errors.append(f"línea {line_number}: {'/'.join(map(str, error.path))}: {error.message}")
    if total < 500:
        errors.append(f"dataset tiene {total} registros; el plan requiere al menos 500")
    if errors:
        raise ValueError("\n".join(errors[:20]))
    return total, labels


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, default=ROOT / "eval/data/actions.jsonl")
    args = parser.parse_args()
    try:
        total, labels = validate(args.dataset)
    except (ValueError, json.JSONDecodeError) as exc:
        print(f"Dataset inválido: {exc}")
        return 1
    print(f"OK: {total} acciones; etiquetas={dict(labels)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
