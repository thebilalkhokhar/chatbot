"""LLM-first intent: live fields settle soft-no / deferral before phrase regex."""

from __future__ import annotations

from dataclasses import replace

from chatbot.bot.composer import Composed
from chatbot.bot.orchestrator import Orchestrator
from chatbot.bot.reply_judge import JudgeVerdict
from chatbot.bot.state import (
    STATUS_SUGGESTED,
    STATUS_VISITOR,
    STATUS_WAIVED,
    TO_BE_CONFIRMED,
)


def _engine(config, kb_index, tmp_path, name: str) -> Orchestrator:
    live_config = replace(config, mode="live", allow_live=True, api_key="test-key")
    return Orchestrator(
        live_config,
        store_path=tmp_path / f"{name}.sqlite3",
        index=kb_index,
        examples=[],
    )


def _mute_side_llms(monkeypatch) -> None:
    monkeypatch.setattr(
        "chatbot.bot.orchestrator.normalize_inbound",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        "chatbot.bot.orchestrator.judge_reply",
        lambda *args, **kwargs: JudgeVerdict(ok=True),
    )


def test_llm_first_soft_no_closes_suggested_material(config, kb_index, tmp_path, monkeypatch):
    engine = _engine(config, kb_index, tmp_path, "llm-soft-no")
    _mute_side_llms(monkeypatch)
    try:
        state = engine.store.get_or_create("c-soft-no")
        state.set_field("product", "labels", status=STATUS_VISITOR)
        state.set_field("use_case", "coffee beans", status=STATUS_VISITOR)
        state.set_field("sizes", TO_BE_CONFIRMED, status=STATUS_WAIVED)
        state.set_field("quantity", "500", status=STATUS_VISITOR)
        state.set_field("material", "PP white vinyl", status=STATUS_SUGGESTED)
        state.flags["soft_email_asked"] = True
        state.last_question = "material"
        engine.store.save(state)

        monkeypatch.setattr(
            "chatbot.bot.orchestrator.live_turn",
            lambda *args, **kwargs: Composed(
                reply="No problem — we'll note no special material preference. What finish do you prefer?",
                asked="finishes",
                fields={"material": "no preference"},
                source="live",
            ),
        )
        result = engine.handle("c-soft-no", "nopeeeeee")
        state = engine.store.get_or_create("c-soft-no")
        assert result.source in {"live", "live-rewrite"}
        assert state.fields["material"].status == STATUS_WAIVED
        assert state.fields["material"].value == "no preference"
        assert "material" not in state.ask_set()
        assert "special features" not in result.reply.lower()
    finally:
        engine.close()


def test_llm_first_maybe_later_waives_size_via_fields(config, kb_index, tmp_path, monkeypatch):
    engine = _engine(config, kb_index, tmp_path, "llm-later")
    _mute_side_llms(monkeypatch)
    try:
        state = engine.store.get_or_create("c-later")
        state.set_field("product", "labels", status=STATUS_VISITOR)
        state.set_field("use_case", "coffee beans", status=STATUS_VISITOR)
        state.flags["soft_email_asked"] = True
        state.fields["email"].attempts = 1
        state.last_question = "sizes"
        engine.store.save(state)

        monkeypatch.setattr(
            "chatbot.bot.orchestrator.live_turn",
            lambda *args, **kwargs: Composed(
                reply="No problem — the team can confirm size later. What quantity do you need?",
                asked="quantity",
                fields={"sizes": TO_BE_CONFIRMED},
                source="live",
            ),
        )
        result = engine.handle("c-later", "maybe later")
        state = engine.store.get_or_create("c-later")
        assert result.source in {"live", "live-rewrite"}
        assert state.fields["sizes"].value == TO_BE_CONFIRMED
        assert state.fields["sizes"].status == STATUS_WAIVED
        assert "sizes" not in state.ask_set()
        # Must not pretend they deferred quantity.
        assert "unsure on quantity" not in result.reply.lower()
    finally:
        engine.close()


def test_llm_first_helper_flags_suggested_and_deferral(config, kb_index, tmp_path):
    engine = _engine(config, kb_index, tmp_path, "llm-helper")
    try:
        state = engine.store.get_or_create("c-help")
        state.set_field("product", "labels", status=STATUS_VISITOR)
        state.set_field("material", "PP white vinyl", status=STATUS_SUGGESTED)
        state.last_question = "material"
        assert engine._llm_first_intent_turn(state, "no bro")
        assert engine._pending_suggestion(state) == "material"

        state2 = engine.store.get_or_create("c-help2")
        state2.set_field("product", "labels", status=STATUS_VISITOR)
        state2.last_question = "sizes"
        assert engine._llm_first_intent_turn(state2, "maybe later")
        assert not engine._llm_first_intent_turn(state2, "4 x 6 inches")
    finally:
        engine.close()
