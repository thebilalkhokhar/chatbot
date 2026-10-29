from __future__ import annotations

import re
from typing import Any

EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b")
PHONE = re.compile(
    r"(?<!\d)(?:\+?1[\s.\-]?)?(?:\(?\d{3}\)?[\s.\-]?)\d{3}[\s.\-]?\d{4}(?!\d)"
)


def mask(text: str) -> str:
    if not text:
        return text
    masked = EMAIL.sub("[EMAIL]", str(text))
    return PHONE.sub("[PHONE]", masked)


def mask_obj(value: Any) -> Any:
    if isinstance(value, str):
        return mask(value)
    if isinstance(value, list):
        return [mask_obj(item) for item in value]
    if isinstance(value, dict):
        return {key: mask_obj(item) for key, item in value.items()}
    return value
