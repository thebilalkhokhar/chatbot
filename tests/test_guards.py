from __future__ import annotations

from chatbot.bot import canon, guards, pii
from chatbot.bot.personas import PERSONAS, validate_personas
from chatbot.bot.state import ConversationState


def make_state(*visitor_texts: str) -> ConversationState:
    state = ConversationState(id="test", persona="Alex Kane")
    for text in visitor_texts:
        state.add("visitor", text)
    return state


def test_personas_are_nine_and_unique():
    assert len(PERSONAS) == 9
    assert validate_personas() == []


def test_kb_has_verified_chunks(kb_index):
    stats = kb_index.stats()
    assert stats["documents"] >= 30
    assert stats["chunks"] > 30
    assert stats["draft_chunks"] == 0
    hits = kb_index.search("minimum order quantity", top_k=4)
    assert hits
    assert any("moq" in hit.chunk.doc_id.lower() for hit in hits)


def test_multiple_questions_blocked():
    state = make_state("I need boxes")
    result = guards.check_reply(
        "What size do you need, and how many units?", state, visitor_text="I need boxes"
    )
    assert "multiple_questions" in result.codes()


def test_price_and_check_promise_blocked():
    state = make_state("How much for 1000 boxes?")
    result = guards.check_reply("They are $1.20 each. I'll check with the team.", state)
    assert "price_given" in result.codes()
    assert "promise_to_check" in result.codes()
    assert not result.ok


def test_time_promise_blocked_but_canonical_turnaround_allowed():
    state = make_state("When can you ship?")
    blocked = guards.check_reply("We can ship by Friday.", state)
    assert "time_promise" in blocked.codes()
    allowed = guards.check_reply(
        "Our standard turnaround is 12-15 business days. What box size are you looking for?",
        state,
    )
    assert "time_promise" not in allowed.codes()
    assert allowed.ok


def test_banner_minimum_guard():
    state = make_state("I need banners")
    assert state.family() == "banners"
    bad = guards.check_reply("The minimum order is 1,000 units.", state)
    assert "wrong_minimum" in bad.codes()
    good = guards.check_reply(
        "Banners have no minimum — you can order any quantity. What banner size are you looking for?",
        state,
    )
    assert "wrong_minimum" not in good.codes()


def test_answer_first_blocks_script_question_only():
    state = make_state("What is your MOQ?")
    result = guards.check_reply("What box size are you looking for?", state)
    assert "unanswered_question" in result.codes()
    good = guards.check_reply(
        "Our MOQ is 1,000 per size, or 500 each with multiple designs. "
        "What box size are you looking for?",
        state,
    )
    assert good.ok


def test_international_shipping_question_is_detected_and_answered():
    text = "can you ship orders to china?"
    assert "intl_shipping" in canon.detect_topics(text)
    state = make_state("I need custom boxes", text)

    blocked = guards.check_reply(
        "Shipping is free nationwide via UPS. What box size are you looking for?",
        state,
        visitor_text=text,
    )
    assert "unanswered_question" in blocked.codes()

    good = guards.check_reply(
        "Shipping is free nationwide via UPS. For delivery outside the USA, the team "
        "will confirm whether delivery is possible and what it costs when they send "
        "the quote. What box size are you looking for?",
        state,
        visitor_text=text,
    )
    assert good.ok
    assert "possibly_unanswered_question" not in good.codes()


def test_international_shipping_phrasings_and_domestic_stay_separate():
    for text in (
        "do you ship internationally?",
        "can you deliver to the uk?",
        "shipping to australia?",
        "outside the us shipping",
    ):
        assert "intl_shipping" in canon.detect_topics(text), text
    assert canon.detect_topics("what are your shipping options?") == ["shipping"]
    assert canon.detect_topics("can you ship orders to china?") == ["intl_shipping"]


def test_untraceable_number_blocked():
    state = make_state("What is your MOQ?")
    result = guards.check_reply("Our minimum is 750 units.", state)
    assert "untraceable_number" in result.codes()


def test_repeated_question_after_answer_blocked():
    state = make_state("4 x 6 inches")
    state.set_field("sizes", "4 x 6 inches")
    state.fields["sizes"].status = "answered"
    state.add("ai", "What size are you looking for?")
    result = guards.check_reply("What size are you looking for?", state)
    assert "repeated_message" in result.codes() or "question_already_answered" in result.codes()


def test_bot_self_claim_and_disclosure():
    state = make_state("hello")
    volunteered = guards.check_reply("I'm an AI assistant.", state, visitor_text="hello")
    assert "bot_self_claim" in volunteered.codes()
    asked = guards.check_reply(
        "I'm an AI assistant helping the Print247 team. What are you looking to have made?",
        state,
        visitor_text="Are you a bot?",
        asked_if_bot=True,
    )
    assert "bot_self_claim" not in asked.codes()


def test_wrong_minimum_figures_use_canon():
    state = make_state("I need 500 bags with 3 designs")
    state.add("visitor", "bags")
    state.set_field("product", "bags")
    reply = canon.effective_answer("moq")
    result = guards.check_reply(reply, state, visitor_text="I need 500 bags with 3 designs")
    assert "wrong_minimum" not in result.codes()


def test_pii_masking():
    text = "email me at buyer@example.com or +1 832-807-3429"
    masked = pii.mask(text)
    assert "buyer@example.com" not in masked
    assert "832-807-3429" not in masked
    assert "[EMAIL]" in masked and "[PHONE]" in masked
