import json
from pathlib import Path

REGION_SETS_PATH = Path.home() / ".pdf_crop_exporter" / "region_sets.json"


def load_region_sets() -> list[dict]:
    if not REGION_SETS_PATH.exists():
        return []
    try:
        with open(REGION_SETS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def save_region_sets(region_sets: list[dict]) -> None:
    REGION_SETS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(REGION_SETS_PATH, "w", encoding="utf-8") as f:
        json.dump(region_sets, f, ensure_ascii=False, indent=2)
