"""Carga los lotes de preguntas tipadas por clase."""
import json
from pathlib import Path

from jev_gate.models.contracts import Action


def load_question_config(path: str | Path | None = None) -> dict:
    config_path = Path(path) if path else Path(__file__).resolve().parents[3] / "docs" / "jev_questions.json"
    data = json.loads(config_path.read_text(encoding="utf-8"))
    for action_class, questions in data["classes"].items():
        ids = [q["id"] for q in questions]
        if len(ids) != len(set(ids)):
            raise ValueError(f"IDs de pregunta duplicados en {action_class}")
        for question in questions:
            if question["type"] == "choice" and not question.get("options"):
                raise ValueError(f"La pregunta Choice {question['id']} requiere options")
    return data


def questions_for(action: Action, config: dict | None = None) -> list[dict]:
    source = config or load_question_config()
    return source["classes"][action.action_class.value]
