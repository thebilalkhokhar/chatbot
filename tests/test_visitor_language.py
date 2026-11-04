"""Session language helpers — detection itself is LLM-driven in reply_language."""

from __future__ import annotations

from chatbot.bot.visitor_language import ENGLISH, session_language


def test_session_language_defaults_to_english():
    assert session_language(None) == ENGLISH
    assert session_language({}) == ENGLISH
    assert session_language({"language": ""}) == ENGLISH


def test_session_language_reads_flag():
    assert session_language({"language": "Spanish"}) == "Spanish"
    assert session_language({"language": "German"}, default="French") == "German"
