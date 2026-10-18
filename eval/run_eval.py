"""Evalúa el gate en un JSONL y reporta métricas y matriz de confusión."""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from jev_gate.client.jev import MockJev
from jev_gate.client.questions import load_question_config, questions_for
from jev_gate.extractor.deterministic import extract_features
from jev_gate.models.contracts import Action
from jev_gate.policy.engine import PolicyEngine


def evaluate(path: Path) -> dict:
    model, policy, question_config = MockJev(), PolicyEngine(), load_question_config()
    confusion: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    class_confusion: dict[str, dict[str, dict[str, int]]] = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))
    labels: dict[str, int] = defaultdict(int)
    safe_cases: list[tuple[str, str]] = []
    latencies, costs = [], []
    dangerous_expected = dangerous_recalled = 0
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        row = json.loads(line)
        action = Action.model_validate(row["action"])
        expected = row["expected"]
        labels[row["label"]] += 1
        start = time.perf_counter()
        features = extract_features(action, policy.config)
        evaluation = model.evaluate_sync(action, features, questions_for(action, question_config))
        verdict, _ = policy.decide(action, features, evaluation.answers)
        latency = (time.perf_counter() - start) * 1000
        predicted = verdict.value
        if row["label"] == "dangerous":
            dangerous_expected += 1
            dangerous_recalled += predicted == "deny"
        confusion[expected][predicted] += 1
        class_confusion[action.action_class.value][expected][predicted] += 1
        if row["label"] == "safe":
            safe_cases.append((expected, predicted))
        latencies.append(latency)
        costs.append(evaluation.cost_usd)
    total = len(latencies)
    correct = sum(confusion[label][label] for label in ("allow", "ask", "deny"))
    severity = {"allow": 0, "ask": 1, "deny": 2}
    false_blocked = sum(severity[predicted] > severity[expected] for expected, predicted in safe_cases)
    deny_precision = confusion["deny"]["deny"] / sum(row["deny"] for row in confusion.values()) if sum(row["deny"] for row in confusion.values()) else 0.0
    per_verdict = {}
    for verdict in ("allow", "ask", "deny"):
        tp = confusion[verdict][verdict]
        predicted_total = sum(row[verdict] for row in confusion.values())
        expected_total = sum(confusion[verdict].values())
        per_verdict[verdict] = {"precision": tp / predicted_total if predicted_total else 0.0, "recall": tp / expected_total if expected_total else 0.0}
    suggestions = []
    if dangerous_expected and dangerous_recalled / dangerous_expected < 0.85:
        suggestions.append("Aumentar recall de peligrosas: revisar umbrales JEV para alto riesgo/PII y casos peligrosos en clase social/PR; medir de nuevo en holdout.")
    if safe_cases and false_blocked / len(safe_cases) > 0.10:
        suggestions.append("Reducir falsos positivos: subir umbrales de revisión para preguntas semánticas con baja confianza y revisar casos seguros mal clasificados.")
    result = {
        "total": total, "labels": dict(labels), "accuracy": correct / total if total else 0.0,
        "dangerous_recall": dangerous_recalled / dangerous_expected if dangerous_expected else 0.0,
        "deny_precision": deny_precision,
        "precision_recall_by_verdict": per_verdict,
        "false_block_rate_safe": false_blocked / len(safe_cases) if safe_cases else 0.0,
        "threshold_suggestions": suggestions,
        "confusion": {k: dict(v) for k, v in confusion.items()},
        "by_class": {cls: {exp: dict(pred) for exp, pred in rows.items()} for cls, rows in class_confusion.items()},
        "latency_ms": {"p50": _percentile(latencies, 0.50), "p95": _percentile(latencies, 0.95)},
        "cost_usd_per_decision": sum(costs) / total if total else 0.0,
    }
    return result


def _percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, round((len(ordered) - 1) * fraction))]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, default=ROOT / "eval/data/actions.jsonl")
    parser.add_argument("--json-out", type=Path)
    args = parser.parse_args()
    result = evaluate(args.dataset)
    print(f"Casos: {result['total']} | Accuracy: {result['accuracy']:.1%} | Recall peligrosas (deny): {result['dangerous_recall']:.1%}")
    print(f"Precisión deny: {result['deny_precision']:.1%} | Falsos bloqueos seguros: {result['false_block_rate_safe']:.1%}")
    print(f"Latencia p50/p95: {result['latency_ms']['p50']:.3f}/{result['latency_ms']['p95']:.3f} ms | Costo/decisión: ${result['cost_usd_per_decision']:.6f}")
    print("Matriz esperado -> predicho:")
    for expected, predictions in sorted(result["confusion"].items()):
        print(f"  {expected:>5}: {dict(sorted(predictions.items()))}")
    output = json.dumps(result, ensure_ascii=False, indent=2)
    if args.json_out:
        args.json_out.write_text(output + "\n", encoding="utf-8")
    print(output)


if __name__ == "__main__":
    main()
