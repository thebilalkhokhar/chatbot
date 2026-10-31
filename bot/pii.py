from __future__ import annotations

import re
from typing import Any

EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b")
PHONE = re.compile(
    r"(?<!\d)(?:\+?1[\s.\-]?)?(?:\(?\d{3}\)?[\s.\-]?)\d{3}[\s.\-]?\d{4}(?!\d)"
)
# The public support line is a canon fact, not a visitor's private detail.
PUBLIC_EMAIL = "Support@print247.us"
PUBLIC_PHONE = "+1 (832) 807-3429"
_PUBLIC_EMAIL = re.compile(r"support@print247\.us", re.I)
_PUBLIC_PHONE = re.compile(
    r"\+?1?[\s.\-]?\(?832\)?[\s.\-]?807[\s.\-]?3429",
    re.I,
)
_EMAIL_TOKEN = "\x00PUBLIC_EMAIL\x00"
_PHONE_TOKEN = "\x00PUBLIC_PHONE\x00"


def mask(text: str) -> str:
    if not text:
        return text
    protected = _PUBLIC_EMAIL.sub(_EMAIL_TOKEN, str(text))
    protected = _PUBLIC_PHONE.sub(_PHONE_TOKEN, protected)
    masked = EMAIL.sub("[EMAIL]", protected)
    masked = PHONE.sub("[PHONE]", masked)
    masked = masked.replace(_EMAIL_TOKEN, PUBLIC_EMAIL)
    return masked.replace(_PHONE_TOKEN, PUBLIC_PHONE)


def restore_public_contact(text: str) -> str:
    """Put the real support line back when a draft echoes the masked placeholders."""
    if not text or ("[EMAIL]" not in text and "[PHONE]" not in text):
        return text
    restored = re.sub(
        r"\[EMAIL\]\s+or\s+\[PHONE\]",
        f"{PUBLIC_EMAIL} or {PUBLIC_PHONE}",
        text,
        flags=re.I,
    )
    restored = re.sub(
        r"\[PHONE\]\s+or\s+\[EMAIL\]",
        f"{PUBLIC_PHONE} or {PUBLIC_EMAIL}",
        restored,
        flags=re.I,
    )
    return _restore_sentences(restored)


def _restore_sentences(text: str) -> str:
    parts = re.split(r"(?<=[.!?])\s+", text)
    restored: list[str] = []
    for part in parts:
        if "[EMAIL]" in part or "[PHONE]" in part:
            if re.search(r"\b(?:reach|contact|call|support|team|email us|phone)\b", part, re.I):
                part = part.replace("[EMAIL]", PUBLIC_EMAIL).replace("[PHONE]", PUBLIC_PHONE)
        restored.append(part)
    return " ".join(restored)


def mask_obj(value: Any) -> Any:
    if isinstance(value, str):
        return mask(value)
    if isinstance(value, list):
        return [mask_obj(item) for item in value]
    if isinstance(value, dict):
        return {key: mask_obj(item) for key, item in value.items()}
    return value
