import json
from pathlib import Path

PRESETS_PATH = Path.home() / ".pdf_crop_exporter" / "presets.json"


def load_presets() -> list[dict]:
    if not PRESETS_PATH.exists():
        return []
    try:
        with open(PRESETS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def save_presets(presets: list[dict]) -> None:
    PRESETS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(PRESETS_PATH, "w", encoding="utf-8") as f:
        json.dump(presets, f, ensure_ascii=False, indent=2)
