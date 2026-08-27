import re

_FORBIDDEN_CHARS = re.compile(r'[\\/:*?"<>|]')


def sanitize_folder_name(name: str) -> str:
    cleaned = _FORBIDDEN_CHARS.sub("_", name).strip().strip(".")
    return cleaned
