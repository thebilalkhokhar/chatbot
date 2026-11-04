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
        # Soft-decline may settle before live (heuristic "Got it." + next ask) or via live fields.
        assert result.source in {"live", "live-rewrite", "heuristic"}
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


def test_model_finish_none_waives_not_suggested(config, kb_index, tmp_path, monkeypatch):
    """Model finishes=none on soft-no must waive as TBC, not trap suggested none."""
    engine = _engine(config, kb_index, tmp_path, "finish-none")
    _mute_side_llms(monkeypatch)
    try:
        state = engine.store.get_or_create("c-finish-none")
        state.set_field("product", "bags", status=STATUS_VISITOR)
        state.set_field("use_case", "snacks", status=STATUS_VISITOR)
        state.set_field("sizes", TO_BE_CONFIRMED, status=STATUS_WAIVED)
        state.set_field("quantity", "350", status=STATUS_VISITOR)
        state.set_field("style", "no preference", status=STATUS_WAIVED)
        state.set_field("material", "pe", status=STATUS_VISITOR)
        state.flags["soft_email_asked"] = True
        state.last_question = "finishes"
        engine.store.save(state)

        monkeypatch.setattr(
            "chatbot.bot.orchestrator.live_turn",
            lambda *args, **kwargs: Composed(
                reply=(
                    "Noted — no finish for these bags. "
                    "What finish do you prefer: matte, gloss or soft touch?"
                ),
                asked="finishes",
                fields={"finishes": "none"},
                source="live",
            ),
        )
        result = engine.handle("c-finish-none", "nothing")
        state = engine.store.get_or_create("c-finish-none")
        assert state.fields["finishes"].value == TO_BE_CONFIRMED
        assert state.fields["finishes"].status == STATUS_WAIVED
        assert "finishes" not in state.ask_set()
        assert any(key == "finishes" for key, _ in state.do_not_ask())
        # Catalogue none coerced to TBC and polish must not re-ask finish.
        assert "matte" not in result.reply.lower()
        assert "gloss" not in result.reply.lower()
    finally:
        engine.close()


def test_soft_no_closes_suggested_finish_none(config, kb_index, tmp_path, monkeypatch):
    """idk on suggested finish=none must waive — not re-ask forever."""
    engine = _engine(config, kb_index, tmp_path, "finish-idk")
    _mute_side_llms(monkeypatch)
    try:
        state = engine.store.get_or_create("c-finish-idk")
        state.set_field("product", "bags", status=STATUS_VISITOR)
        state.set_field("use_case", "snacks", status=STATUS_VISITOR)
        state.set_field("sizes", TO_BE_CONFIRMED, status=STATUS_WAIVED)
        state.set_field("quantity", "350", status=STATUS_VISITOR)
        state.set_field("style", "no preference", status=STATUS_WAIVED)
        state.set_field("material", "pe", status=STATUS_VISITOR)
        state.set_field("finishes", "none", status=STATUS_SUGGESTED)
        state.flags["soft_email_asked"] = True
        state.last_question = "finishes"
        state.turn_count = 14
        engine.store.save(state)

        monkeypatch.setattr(
            "chatbot.bot.orchestrator.live_turn",
            lambda *args, **kwargs: Composed(
                reply="No problem — I can help you decide. What finish do you prefer: matte, gloss or soft touch?",
                asked="finishes",
                fields={},
                source="live",
            ),
        )
        result = engine.handle("c-finish-idk", "idk")
        state = engine.store.get_or_create("c-finish-idk")
        assert result.handoff == ""
        assert state.fields["finishes"].value == TO_BE_CONFIRMED
        assert state.fields["finishes"].status == STATUS_WAIVED
        assert "finishes" not in state.ask_set()
    finally:
        engine.close()


def test_nope_on_size_does_not_ack_email(config, kb_index, tmp_path, monkeypatch):
    """Bare nope while size is open must not be treated as email refusal."""
    engine = _engine(config, kb_index, tmp_path, "size-nope")
    _mute_side_llms(monkeypatch)
    try:
        state = engine.store.get_or_create("c-size-nope")
        state.set_field("product", "bags", status=STATUS_VISITOR)
        state.set_field("use_case", "coffee beans", status=STATUS_VISITOR)
        state.set_field("sizes", TO_BE_CONFIRMED, status=STATUS_WAIVED)
        state.flags["soft_email_asked"] = True
        state.last_question = "sizes"
        state.turn_count = 6
        engine.store.save(state)

        # Re-open as if bot just asked size again after idk coaching.
        state = engine.store.get_or_create("c-size-nope")
        state.set_field("sizes", "", status=STATUS_VISITOR)
        state.fields["sizes"].value = ""
        state.fields["sizes"].status = "unknown"
        state.fields["sizes"].basis = ""
        state.last_question = "sizes"
        engine.store.save(state)

        monkeypatch.setattr(
            "chatbot.bot.orchestrator.live_turn",
            lambda *args, **kwargs: Composed(
                reply=(
                    "Thanks — no problem about the email. "
                    "What quantity are you looking to order for your first run?"
                ),
                asked="quantity",
                fields={"sizes": TO_BE_CONFIRMED},
                source="live",
            ),
        )
        # Ensure the live prompt itself is not told this is an email refusal.
        from chatbot.bot.composer import _intent, build_user
        from chatbot.bot.state import contact_fields_refused

        assert not contact_fields_refused("nope", "sizes")
        assert _intent("nope", "sizes") != "refusal"
        assert _intent("nope", "email") == "refusal"

        result = engine.handle("c-size-nope", "nope")
        state = engine.store.get_or_create("c-size-nope")
        assert state.fields["sizes"].value == TO_BE_CONFIRMED
        assert state.fields["sizes"].status == STATUS_WAIVED
        assert "email" not in result.reply.lower()
        user_prompt = build_user(state, "nope", ("quantity", "qty?"))
        assert "declined to share their email" not in user_prompt.lower()
    finally:
        engine.close()


def test_extras_none_after_turns_does_not_max_turns_before_waive(
    config, kb_index, tmp_path, monkeypatch
):
    """Soft-no on extras must settle before max_turns can hand off."""
    live_config = replace(config, mode="live", allow_live=True, api_key="test-key", max_turns=12)
    engine = Orchestrator(
        live_config,
        store_path=tmp_path / "extras-none.sqlite3",
        index=kb_index,
        examples=[],
    )
    _mute_side_llms(monkeypatch)
    try:
        state = engine.store.get_or_create("c-extras-none")
        state.set_field("product", "bags", status=STATUS_VISITOR)
        state.set_field("use_case", "snacks", status=STATUS_VISITOR)
        state.set_field("sizes", TO_BE_CONFIRMED, status=STATUS_WAIVED)
        state.set_field("quantity", "350", status=STATUS_VISITOR)
        state.set_field("style", "no preference", status=STATUS_WAIVED)
        state.set_field("material", "pe", status=STATUS_VISITOR)
        state.set_field("finishes", TO_BE_CONFIRMED, status=STATUS_WAIVED)
        state.flags["soft_email_asked"] = True
        state.last_question = "extras"
        state.turn_count = 14
        engine.store.save(state)

        monkeypatch.setattr(
            "chatbot.bot.orchestrator.live_turn",
            lambda *args, **kwargs: Composed(
                reply="No problem — extras can be confirmed later. What is the best email for the quote?",
                asked="email",
                fields={"extras": TO_BE_CONFIRMED},
                source="live",
            ),
        )
        result = engine.handle("c-extras-none", "none")
        state = engine.store.get_or_create("c-extras-none")
        assert result.handoff != "max_turns"
        assert state.fields["extras"].value == TO_BE_CONFIRMED
        assert state.fields["extras"].status == STATUS_WAIVED
        assert "specialist" not in result.reply.lower()
    finally:
        engine.close()
