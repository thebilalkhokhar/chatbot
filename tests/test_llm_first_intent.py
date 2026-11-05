"""LLM-first intent: live fields settle soft-no / deferral before phrase regex."""

from __future__ import annotations

from dataclasses import replace

from chatbot.bot.composer import Composed
from chatbot.bot.llm import LLMError
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


def test_no_design_yet_waives_skus_without_reask(config, kb_index, tmp_path, monkeypatch):
    """Live may 'note' no designs yet then re-ask — settle by contract, not phrase lists."""
    engine = _engine(config, kb_index, tmp_path, "llm-no-design-yet")
    _mute_side_llms(monkeypatch)
    try:
        state = engine.store.get_or_create("c-no-design-yet")
        state.set_field("product", "labels", status=STATUS_VISITOR)
        state.set_field("use_case", "whisky bottle", status=STATUS_VISITOR)
        state.set_field("sizes", TO_BE_CONFIRMED, status=STATUS_WAIVED)
        state.set_field("quantity", "6969", status=STATUS_VISITOR)
        state.set_field("material", "metalized film", status=STATUS_VISITOR)
        state.set_field("finishes", "soft touch", status=STATUS_VISITOR)
        state.set_field("email", "bilal@gmail.com", status=STATUS_VISITOR)
        state.flags["soft_email_asked"] = True
        state.last_question = "skus"
        engine.store.save(state)

        def fake_live(*args, **kwargs):
            correction = str(kwargs.get("correction") or "")
            if correction:
                return Composed(
                    reply=(
                        "Thanks — we'll note designs as to be confirmed for now. "
                        "The team will follow up on artwork with your quote."
                    ),
                    asked="",
                    fields={"skus": TO_BE_CONFIRMED},
                    source="live",
                )
            return Composed(
                reply=(
                    "Thanks — noted you have no designs yet. "
                    "How many total designs do you have?"
                ),
                asked="skus",
                fields={},
                source="live",
            )

        monkeypatch.setattr("chatbot.bot.orchestrator.live_turn", fake_live)
        result = engine.handle("c-no-design-yet", "no design yet")
        state = engine.store.get_or_create("c-no-design-yet")
        assert state.fields["skus"].value == TO_BE_CONFIRMED
        assert state.fields["skus"].status == STATUS_WAIVED
        assert "skus" not in state.ask_set()
        assert "how many total designs" not in result.reply.lower()
    finally:
        engine.close()


def test_live_soft_no_without_fields_does_not_reask_material(
    config, kb_index, tmp_path, monkeypatch
):
    """Live may ack decline then re-list materials; state contract must move on.

    Reproduces: visitor 'nah' on material → panel shows no preference but reply
    still asked material. Backup settles before send; polish/rewrite must not
    re-ask the waived field.
    """
    engine = _engine(config, kb_index, tmp_path, "llm-nah-material")
    _mute_side_llms(monkeypatch)
    try:
        state = engine.store.get_or_create("c-nah-material")
        state.set_field("product", "bags", status=STATUS_VISITOR)
        state.set_field("use_case", "coffee", status=STATUS_VISITOR)
        state.set_field("sizes", TO_BE_CONFIRMED, status=STATUS_WAIVED)
        state.set_field("quantity", "2000", status=STATUS_VISITOR)
        state.set_field("style", "Poly Mailers", status=STATUS_VISITOR)
        state.flags["soft_email_asked"] = True
        state.last_question = "material"
        engine.store.save(state)

        calls: list[str] = []

        def fake_live(*args, **kwargs):
            correction = str(kwargs.get("correction") or "")
            calls.append(correction)
            if correction:
                return Composed(
                    reply=(
                        "No problem — no special material preference noted. "
                        "What finish do you prefer: matte, gloss or soft touch?"
                    ),
                    asked="finishes",
                    fields={"material": "no preference"},
                    source="live",
                )
            return Composed(
                reply=(
                    "No problem — for Poly Mailers the common material choices are "
                    "metalized, kraft, PE, PP, PET or foil. Which material would you "
                    "like, or should I mark material as to be confirmed?"
                ),
                asked="material",
                fields={},
                source="live",
            )

        monkeypatch.setattr("chatbot.bot.orchestrator.live_turn", fake_live)
        result = engine.handle("c-nah-material", "nah")
        state = engine.store.get_or_create("c-nah-material")
        assert state.fields["material"].status == STATUS_WAIVED
        assert state.fields["material"].value == "no preference"
        assert "material" not in state.ask_set()
        # Outgoing must not keep the material menu / re-ask after decline.
        lower = result.reply.lower()
        assert "which material" not in lower
        assert "mark material" not in lower
        assert state.last_question != "material"
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


def test_live_failure_still_settles_designs_before_the_reply(
    config, kb_index, tmp_path, monkeypatch
):
    """Call cap / live error must not store designs and then say the answer was missed."""
    engine = _engine(config, kb_index, tmp_path, "llm-cap-designs")
    _mute_side_llms(monkeypatch)
    try:
        state = engine.store.get_or_create("c-cap-designs")
        state.set_field("product", "bags", status=STATUS_VISITOR)
        state.set_field("use_case", "coffee beans", status=STATUS_VISITOR)
        state.set_field("sizes", TO_BE_CONFIRMED, status=STATUS_WAIVED)
        state.set_field("quantity", "500", status=STATUS_VISITOR)
        state.set_field("style", "pinch bottom", status=STATUS_VISITOR)
        state.set_field("material", "pe", status=STATUS_VISITOR)
        state.set_field("finishes", "matte", status=STATUS_VISITOR)
        state.set_field("email", "bilal@gmail.com", status=STATUS_VISITOR)
        state.flags["soft_email_asked"] = True
        state.last_question = "skus"
        engine.store.save(state)

        def _capped(*args, **kwargs):
            raise LLMError("LLM call cap reached (BOT_MAX_LLM_CALLS=50)")

        monkeypatch.setattr("chatbot.bot.orchestrator.live_turn", _capped)
        result = engine.handle("c-cap-designs", "i have no designs yet")
        state = engine.store.get_or_create("c-cap-designs")
        lowered = result.reply.lower()
        assert result.source == "heuristic"
        assert state.fields["skus"].value == TO_BE_CONFIRMED
        assert state.fields["skus"].status == STATUS_WAIVED
        assert not state.fields["extras"].done
        assert "didn't quite catch" not in lowered
        assert "how many" not in lowered
    finally:
        engine.close()


def _labels_size_open(engine: Orchestrator, conversation_id: str):
    state = engine.store.get_or_create(conversation_id)
    state.set_field("product", "labels", status=STATUS_VISITOR)
    state.set_field("use_case", "whisky bottles", status=STATUS_VISITOR)
    state.set_field("email", "bilal@gmail.com", status=STATUS_VISITOR)
    state.flags["soft_email_asked"] = True
    state.last_question = "sizes"
    engine.store.save(state)


def test_ask_turn_keeps_model_size_waiver_and_moves_on(
    config, kb_index, tmp_path, monkeypatch
):
    """A question can still be a waiver when the model says so.

    The visitor's words are not the signal. The model's waiver token is.
    The same reply must not ask size again.
    """
    engine = _engine(config, kb_index, tmp_path, "llm-ask-waiver")
    _mute_side_llms(monkeypatch)
    try:
        _labels_size_open(engine, "c-ask-waiver")
        monkeypatch.setattr(
            "chatbot.bot.orchestrator.live_turn",
            lambda *args, **kwargs: Composed(
                reply=(
                    "No problem — we can sort the size later. "
                    "I'll mark the label size as to be confirmed. "
                    "What label size are you looking for?"
                ),
                asked="sizes",
                fields={"sizes": TO_BE_CONFIRMED},
                source="live",
            ),
        )
        result = engine.handle("c-ask-waiver", "size ka idea nahi, ab kya karun?")
        state = engine.store.get_or_create("c-ask-waiver")
        lowered = result.reply.lower()
        assert result.source in {"live", "live-rewrite"}
        assert state.flags.get("turn_kind") == "ask"
        assert state.fields["sizes"].value == TO_BE_CONFIRMED
        assert state.fields["sizes"].status == STATUS_WAIVED
        assert not state.fields["quantity"].done
        assert "what label size" not in lowered
        assert "quantity" in lowered
        assert state.last_question == "quantity"
    finally:
        engine.close()


def test_ask_turn_prose_waiver_settles_without_a_fields_token(
    config, kb_index, tmp_path, monkeypatch
):
    """The model can commit in the sentence when fields were left empty."""
    engine = _engine(config, kb_index, tmp_path, "llm-ask-prose")
    _mute_side_llms(monkeypatch)
    try:
        _labels_size_open(engine, "c-ask-prose")
        monkeypatch.setattr(
            "chatbot.bot.orchestrator.live_turn",
            lambda *args, **kwargs: Composed(
                reply=(
                    "No problem — we can sort the size later. "
                    "I'll mark the label size as to be confirmed. "
                    "What label size are you looking for?"
                ),
                asked="sizes",
                fields={},
                source="live",
            ),
        )
        result = engine.handle(
            "c-ask-prose", "i am unsure about size. what should i do?"
        )
        state = engine.store.get_or_create("c-ask-prose")
        lowered = result.reply.lower()
        assert state.fields["sizes"].value == TO_BE_CONFIRMED
        assert state.fields["sizes"].status == STATUS_WAIVED
        assert not state.fields["quantity"].done
        assert "what label size" not in lowered
        assert "quantity" in lowered
        assert state.last_question == "quantity"
    finally:
        engine.close()


def test_size_help_question_without_model_waiver_stays_open(
    config, kb_index, tmp_path, monkeypatch
):
    """A size question stays open when the model does not waive it."""
    engine = _engine(config, kb_index, tmp_path, "llm-ask-open")
    _mute_side_llms(monkeypatch)
    try:
        _labels_size_open(engine, "c-ask-open")
        monkeypatch.setattr(
            "chatbot.bot.orchestrator.live_turn",
            lambda *args, **kwargs: Composed(
                reply=(
                    "There's no standard size — labels are cut to the product. "
                    "What are the product dimensions?"
                ),
                asked="sizes",
                fields={},
                source="live",
            ),
        )
        result = engine.handle("c-ask-open", "any standard size?")
        state = engine.store.get_or_create("c-ask-open")
        assert not state.fields["sizes"].done
        assert state.last_question == "sizes"
        assert "dimension" in result.reply.lower()
    finally:
        engine.close()
