import json
from pathlib import Path

PROMPTS = Path(__file__).resolve().parent / "prompt_templates"


def render(name: str, **values: object) -> str:
    text = (PROMPTS / name).read_text(encoding="utf-8")
    for key, value in values.items():
        if not isinstance(value, str):
            value = json.dumps(value, ensure_ascii=False, indent=2)
        text = text.replace("{{" + key + "}}", value)
    return text
