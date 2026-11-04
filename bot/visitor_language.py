"""Visitor reply language for a chat.

Detection and translation are LLM-driven (see reply_language.py). This module
only holds the English sentinel and helpers for reading the session language
stored on the conversation — no word lists or script heuristics.
"""

from __future__ import annotations

from typing import Any

ENGLISH = "English"


def session_language(flags: dict[str, Any] | None, default: str = ENGLISH) -> str:
    """Language last confirmed for this chat, or English."""
    value = str((flags or {}).get("language") or "").strip()
    return value or default
