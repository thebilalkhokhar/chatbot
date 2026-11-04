from __future__ import annotations

from chatbot.bot.state import (
    ConversationState,
    STATUS_VISITOR,
    apply_field_updates,
    asks_language_preference,
    is_meta_question,
    normalize_finish,
    parse_quantity,
    traceable,
    wants_recommendation,
)


def test_parse_quantity_english_number_words():
    assert parse_quantity("three hundred") == 300
    assert parse_quantity("three hundred units") == 300
    assert parse_quantity("1,000") == 1000
    assert parse_quantity("two thousand") == 2000


def test_any_suggestion_counts_as_recommendation():
    assert wants_recommendation("Any suggestion?")
    assert wants_recommendation("any suggestions")
    assert wants_recommendation("some recommendations please")


def test_language_preference_is_meta():
    assert asks_language_preference("Do you speak Spanish?")
    assert asks_language_preference("Can you reply in French?")
    assert is_meta_question("Do you speak Spanish?")


def test_finish_matte_lamination_is_traceable():
    state = ConversationState(id="fin", persona="Alex Kane")
    assert normalize_finish("matte lamination") == "matte lamination"
    assert traceable("finishes", "matte lamination", "matte lamination", state)


def test_quantity_three_hundred_locks_as_300():
    state = ConversationState(id="qty", persona="Alex Kane")
    state.last_question = "quantity"
    accepted, rejected = apply_field_updates(
        state,
        {"quantity": "three hundred"},
        "three hundred",
    )
    assert accepted.get("quantity") == "300"
    assert not rejected
    assert state.fields["quantity"].value == "300"
    assert state.fields["quantity"].raw_visitor_text == "300"


def test_size_raw_stays_size_span_not_chat_summary():
    state = ConversationState(id="sz", persona="Alex Kane")
    state.last_question = "sizes"
    accepted, _rejected = apply_field_updates(
        state,
        {"sizes": "15x25x15 in"},
        "300 Any suggestion? matte lamination 15 × 25 × 15 inches",
    )
    assert accepted.get("sizes")
    raw = state.fields["sizes"].raw_visitor_text
    assert "suggestion" not in raw.lower()
    assert "15" in raw


def test_suggestion_does_not_waive_style_as_tbc():
    state = ConversationState(id="sty", persona="Alex Kane")
    state.last_question = "style"
    accepted, rejected = apply_field_updates(
        state,
        {"style": "to be confirmed"},
        "Any suggestion?",
    )
    assert "style" in rejected
    assert "style" not in accepted
    assert state.fields["style"].status != STATUS_VISITOR or not state.fields["style"].done
