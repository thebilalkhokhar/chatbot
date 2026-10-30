from __future__ import annotations

from chatbot.bot.guards import settled_for_asking
from chatbot.bot.composer import RULE_TEXT, build_user
from chatbot.bot.state import (
    BASIS_MODEL,
    BASIS_VISITOR,
    USE_CASE_QUESTION,
    ConversationState,
    FieldValue,
    STATUS_CONFIRMED,
    STATUS_SUGGESTED,
    STATUS_UNKNOWN,
    STATUS_VISITOR,
    STATUS_WAIVED,
    apply_field_updates,
    extract_fields,
    normalise_size,
    use_case_from,
)


def make_state(*visitor_texts: str) -> ConversationState:
    state = ConversationState(id="state-test", persona="Alex Kane")
    for text in visitor_texts:
        state.add("visitor", text)
    return state


def test_units_are_folded_and_dimension_order_is_theirs():
    # Section 3.4 rule 1: one shape for the same answer; Section 3.1: "6x4" and
    # "4x6x2" stay different, and a gusset keeps its position.
    assert normalise_size("4 x 6 inches") == "4x6 in"
    assert normalise_size("4x6in") == "4x6 in"
    assert normalise_size('10" x 12"') == "10x12 in"
    assert normalise_size("100 X 150") == "100x150"
    assert normalise_size("6.0 x 4.0 cm") == "6x4 cm"
    assert normalise_size("8x12+4 inches") == "8x12+4 in"
    assert normalise_size("1/8 x 2 3/4 in") == "1/8 x 2 3/4 in"
    assert normalise_size("A4") == "A4"
    assert normalise_size("6 inches") == "6 in"


def test_morning_does_not_become_the_product():
    from chatbot.bot.state import family_of, is_visitor_greeting

    assert is_visitor_greeting("morning")
    assert is_visitor_greeting("good morning")
    assert is_visitor_greeting("Good morning!")
    assert is_visitor_greeting("morning I need boxes") is False
    state = make_state("morning")
    assert extract_fields("morning", "product", state) == {}
    accepted, _rejected = apply_field_updates(
        state,
        {"product": "boxes, bags, labels, or something else", "use_case": "What use case is the boxes for?"},
        "morning",
        source="model",
        bases={"product": "visitor", "use_case": "visitor"},
    )
    assert accepted == {}
    assert not state.fields["product"].value
    assert family_of("morning") == "unknown"


def test_any_zero_dimension_is_rejected():
    from chatbot.bot.state import size_has_zero_dimension

    for text in ("0x0", "0x15", "10x0x5", "0", "0.0 x 4", "10 x 0 x 5 in", "0 in"):
        assert size_has_zero_dimension(text), text
    for text in ("4x6", "4x6x2", "100x150", "8x12+4 inches", "6 inches", "A4"):
        assert size_has_zero_dimension(text) is False, text

    state = make_state("0x15")
    updates = extract_fields("0x15", "sizes", state)
    assert "sizes" not in updates
    accepted, rejected = apply_field_updates(state, {"sizes": "10x0x5"}, "10x0x5")
    assert "sizes" not in accepted
    assert rejected["sizes"] == "10x0x5"
    assert not state.fields["sizes"].value
    assert "size_pending_unit" not in state.flags
    accepted_zero, rejected_zero = apply_field_updates(state, {"sizes": "0"}, "0")
    assert "sizes" not in accepted_zero
    assert rejected_zero["sizes"] == "0"


def test_the_same_answer_in_two_spellings_is_one_value():
    state = make_state("4 x 6 inches")
    apply_field_updates(state, {"sizes": "4 x 6 inches"}, "4 x 6 inches")
    assert state.fields["sizes"].value == "4x6 in"
    assert state.fields["sizes"].raw_visitor_text == "4 x 6 inches"


def test_a_refused_size_is_waived_not_answered():
    state = make_state("I have no idea what size")
    apply_field_updates(state, {"sizes": "no idea"}, "I have no idea what size")
    sizes = state.fields["sizes"]
    assert sizes.status == STATUS_WAIVED
    assert sizes.done, "the bot stops asking; the team sizes it"
    assert not sizes.stated, "but it was never the customer's number"
    assert settled_for_asking(state, "sizes") is False


def test_no_preference_is_a_waiver_too():
    state = make_state("no preference")
    apply_field_updates(state, {"style": "no preference"}, "no preference")
    assert state.fields["style"].status == STATUS_WAIVED
    assert state.fields["style"].raw_visitor_text == "no preference"


def test_a_model_proposal_is_suggested_never_an_answer():
    state = make_state("I need a 4x6x2 in box for a 1 lb jar candle")
    accepted, rejected = apply_field_updates(
        state,
        {"style": "rigid", "sizes": "4x6x2 in"},
        "I need a 4x6x2 in box for a 1 lb jar candle",
        source="model",
    )
    assert accepted["style"] == "rigid"
    assert state.fields["style"].status == STATUS_SUGGESTED
    assert state.fields["style"].basis == BASIS_MODEL
    assert state.fields["style"].raw_visitor_text == "", "the customer never said 'rigid'"
    # Section 4.4: the type itself cannot hold an invented size, and a size the
    # customer did state stays theirs even when written through the model path.
    assert state.fields["sizes"].status == STATUS_VISITOR
    assert state.fields["sizes"].basis == BASIS_VISITOR
    assert rejected == {}


def test_a_size_the_model_invented_is_rejected():
    state = make_state("I need a box for my candle")
    accepted, rejected = apply_field_updates(
        state, {"sizes": "4x6x2 in"}, "I need a box for my candle", source="model"
    )
    assert accepted == {}
    assert rejected["sizes"] == "4x6x2 in"


def test_an_affirmation_confirms_the_proposal():
    state = make_state("I need a box for my candle")
    apply_field_updates(state, {"style": "rigid"}, "I need a box for my candle", source="model")
    state.last_question = "style"
    assert state.confirm_suggested("yes that works") == ["style"]
    assert state.fields["style"].status == STATUS_CONFIRMED
    assert state.fields["style"].basis == BASIS_VISITOR
    assert state.fields["style"].stated


def test_an_affirmation_does_not_confirm_an_answer_they_gave():
    state = make_state("rigid boxes")
    apply_field_updates(state, {"style": "rigid"}, "rigid boxes")
    state.last_question = "style"
    assert state.confirm_suggested("yes") == []
    assert state.fields["style"].status == STATUS_VISITOR


def test_a_qualified_yes_does_not_confirm_the_proposal():
    state = make_state("I need a box for my candle")
    apply_field_updates(state, {"style": "rigid"}, "I need a box for my candle", source="model")
    state.last_question = "style"
    assert state.confirm_suggested("yes but make it smaller") == []
    assert state.fields["style"].status == STATUS_SUGGESTED


def test_an_affirmation_confirms_only_the_field_that_was_asked():
    state = make_state("I need a box for my candle")
    for key, value in {"style": "rigid", "material": "kraft"}.items():
        apply_field_updates(state, {key: value}, "I need a box for my candle", source="model")
    state.last_question = "style"
    assert state.confirm_suggested("yes") == ["style"]
    assert state.fields["material"].status == STATUS_SUGGESTED


def test_use_case_phrases_and_channels_are_read_from_the_message():
    assert use_case_from("I am packing gummy bears") == "gummy bears"
    assert use_case_from("mailer boxes for shipping candles") == "candles"
    assert use_case_from("rigid boxes for my candle business") == "candle business"
    assert use_case_from("labels for retail") == "retail"
    assert use_case_from("I need boxes") == ""
    # A product family is the product field, not a use case.
    assert use_case_from("pouches for packing coffee bags") in {"coffee bags", ""}


def test_an_answer_to_the_use_case_question_is_taken_wholesale():
    state = make_state("1 lb jar candles with a wooden lid")
    updates = extract_fields("1 lb jar candles with a wooden lid", "use_case", state)
    assert updates["use_case"] == "1 lb jar candles with a wooden lid"

    state.last_question = "use_case"
    assert extract_fields("yes", "use_case", state).get("use_case") is None, state


def test_use_case_is_the_field_v1_had_nowhere_to_put_it():
    state = make_state("I need boxes for my candle business")
    updates = extract_fields("I need boxes for my candle business", "", state)
    assert updates["product"] == "boxes"
    assert updates["use_case"] == "candle business"
    accepted, _ = apply_field_updates(state, updates, "I need boxes for my candle business")
    assert accepted["use_case"] == "candle business"
    assert state.fields["use_case"].status == STATUS_VISITOR


def test_a_contact_detail_does_not_settle_a_prose_field():
    # The scripted chat reached "material" while the visitor was answering for
    # "email", so v1 wrote "buyer@example.com" into the quote sheet as a material.
    state = make_state("I need boxes")
    accepted, rejected = apply_field_updates(
        state, {"material": "buyer@example.com"}, "buyer@example.com"
    )
    assert accepted == {}
    assert rejected["material"] == "buyer@example.com"
    assert state.fields["material"].status == STATUS_UNKNOWN
    _ , rejected = apply_field_updates(state, {"style": "+1 832-807-3429"}, "+1 832-807-3429")
    assert rejected["style"] == "+1 832-807-3429"
    accepted, _ = apply_field_updates(state, {"email": "buyer@example.com"}, "buyer@example.com")
    assert accepted["email"] == "buyer@example.com"


def test_a_v1_record_loads_with_visitor_provenance():
    # The SQLite store and the replay artifacts hold v1 field dicts.
    legacy = {"value": "4x6 in", "status": "answered", "attempts": 1, "source": "visitor"}
    field_value = FieldValue.from_dict(legacy)
    assert field_value.status == STATUS_VISITOR
    assert field_value.basis == BASIS_VISITOR
    assert field_value.done and field_value.stated
    unconfirmed = FieldValue.from_dict({"value": "100x150", "status": "needs_confirmation"})
    assert unconfirmed.status == STATUS_WAIVED
    empty = FieldValue.from_dict(None)
    assert empty.status == STATUS_UNKNOWN and empty.basis == ""


def test_a_saved_conversation_round_trips_through_the_new_columns():
    state = make_state("I need boxes for my candle business")
    apply_field_updates(
        state,
        extract_fields("I need boxes for my candle business", "", state),
        "I need boxes for my candle business",
    )
    apply_field_updates(state, {"sizes": "4 x 6 inches"}, "4 x 6 inches")
    restored = ConversationState.from_dict(state.to_dict())
    assert restored.fields["sizes"].value == "4x6 in"
    assert restored.fields["sizes"].raw_visitor_text == "4 x 6 inches"
    assert restored.fields["use_case"].value == "candle business"
    assert restored.fields["use_case"].status == STATUS_VISITOR
    assert "source" not in restored.to_dict()["fields"]["sizes"]


def _fill(state: ConversationState, key: str, value: str, status: str = STATUS_VISITOR) -> None:
    state.set_field(key, value, BASIS_VISITOR, raw=value, status=status)


def test_boxes_may_be_asked_what_is_inside_and_not_a_scripted_size():
    # Section 3.4 and behaviour 1. The boxes script's first line is the size
    # question; the ask-set must not hand that string over as the next move.
    state = make_state("i am looking for boxes")
    _fill(state, "product", "boxes")
    assert state.ask_set() == ["use_case", "sizes", "quantity"]
    key, question = state.next_question()
    assert key == "use_case"
    assert question == USE_CASE_QUESTION
    assert "box size" not in question.lower()


def test_finish_skus_and_extras_wait_until_the_quote_fields_are_known():
    state = make_state("boxes")
    _fill(state, "product", "boxes")
    assert {"finishes", "skus", "extras", "style", "material"}.isdisjoint(state.ask_set())
    _fill(state, "sizes", "4x6 in")
    _fill(state, "quantity", "1000")
    allowed = state.ask_set()
    assert allowed[0] == "use_case"
    assert "finishes" in allowed and "skus" in allowed
    assert "extras" not in allowed, "boxes have no extras wording"
    assert "style" in allowed and "material" in allowed


def test_a_stated_field_is_on_the_do_not_ask_list_in_their_words():
    state = make_state("boxes")
    _fill(state, "product", "boxes")
    _fill(state, "style", "kraft")
    denied = dict(state.do_not_ask())
    assert denied["product"] == "boxes"
    assert denied["style"] == "kraft"
    assert "product" not in state.ask_set()
    assert "style" not in state.ask_set()
    constraint = state.ask_constraint()
    assert 'product (they said "boxes")' in constraint
    assert 'style (they said "kraft")' in constraint
    assert constraint.startswith("You may ask about: use_case, sizes, quantity.")


def test_use_case_is_asked_and_does_not_stall_the_quote():
    state = make_state("boxes")
    _fill(state, "product", "boxes")
    _fill(state, "sizes", "4x6 in")
    _fill(state, "quantity", "1000")
    assert state.specs_done()
    assert state.ask_set()[0] == "use_case"
    state.fields["use_case"].attempts = 2
    assert "use_case" not in state.ask_set()
    assert state.next_question()[0] == "style"
    assert state.next_question() is not None


def test_the_script_is_only_the_wording_once_a_field_is_selected():
    state = make_state("boxes")
    _fill(state, "product", "boxes")
    _fill(state, "use_case", "candles")
    _fill(state, "sizes", "4x6 in")
    _fill(state, "quantity", "1000")
    key, question = state.next_question()
    assert key == "style"
    assert question == "What style of box do you need, or can you share a reference image?"


def test_a_waived_size_leaves_the_ask_set():
    state = make_state("boxes")
    _fill(state, "product", "boxes")
    _fill(state, "sizes", "to be confirmed", status=STATUS_WAIVED)
    state.fields["sizes"].raw_visitor_text = "no idea"
    assert "sizes" not in state.ask_set()
    assert dict(state.do_not_ask())["sizes"] == "no idea"


def test_a_size_missing_its_unit_stays_askable_and_off_the_do_not_ask_list():
    state = make_state("boxes")
    _fill(state, "product", "boxes")
    _fill(state, "use_case", "candles")
    _fill(state, "sizes", "100x150")
    assert state.size_needs_unit()
    assert state.ask_set()[0] == "sizes"
    assert state.next_question()[1] == "Is 100x150 in inches, cm, or mm?"
    assert "sizes" not in dict(state.do_not_ask())


def test_plain_orders_do_not_get_a_sku_question():
    state = make_state("plain boxes")
    _fill(state, "product", "boxes")
    _fill(state, "use_case", "shipping")
    _fill(state, "sizes", "4x6 in")
    _fill(state, "quantity", "1000")
    state.flags["plain"] = True
    assert "skus" not in state.ask_set()


def test_an_unknown_family_may_only_be_asked_which_product():
    state = make_state("hello")
    assert state.ask_set() == ["product"]
    state.fields["product"].attempts = 2
    assert state.ask_set() == []
    assert state.next_question() is None


def test_the_prompt_injects_the_ask_set_and_drops_the_script_line():
    state = make_state("i am looking for boxes")
    _fill(state, "product", "boxes")
    _fill(state, "style", "kraft")
    user = build_user(state, "thanks", None)
    assert "You may ask about: use_case, sizes, quantity." in user
    assert 'Do not ask about: product (they said "boxes"), style (they said "kraft").' in user
    assert "Next script question" not in user
    assert "ASK SET" in RULE_TEXT
    assert "next script question" not in RULE_TEXT.lower()


def test_a_unit_only_reply_keeps_the_size_in_the_remembered_words():
    state = make_state("12x15")
    apply_field_updates(state, {"sizes": "12x15"}, "12x15")
    state.flags["size_pending_unit"] = state.fields["sizes"].value
    apply_field_updates(state, {"sizes": "12x15 inches"}, "inches")
    assert state.fields["sizes"].value == "12x15 in"
    assert state.fields["sizes"].raw_visitor_text == "12x15 in"


def test_i_have_no_preferences_waives_the_style():
    state = make_state("i have no preferences")
    _fill(state, "product", "boxes")
    state.last_question = "style"
    apply_field_updates(
        state,
        extract_fields("i have no preferences", "style", state),
        "i have no preferences",
    )
    assert state.fields["style"].value == "no preference"
    assert state.fields["style"].status == STATUS_WAIVED
    assert "style" not in state.ask_set()


def test_refusing_contact_waives_email_and_phone():
    phrases = ("i don't want to share", "i have not any", "I don't have an email")
    for text in phrases:
        state = make_state(text)
        _fill(state, "product", "boxes")
        _fill(state, "sizes", "4x6 in")
        _fill(state, "quantity", "1000")
        state.last_question = "email"
        apply_field_updates(state, extract_fields(text, "email", state), text)
        assert state.fields["email"].status == STATUS_WAIVED, text
        assert state.fields["phone"].status == STATUS_WAIVED, text
        assert state.fields["email"].done and state.fields["phone"].done
        assert "email" not in state.ask_set()
        assert "phone" not in state.ask_set()
    assert "Do NOT re-assert or re-emit proposed_configs" in RULE_TEXT
    assert "leave proposed_configs completely EMPTY" in RULE_TEXT
    assert "ONLY ONE single question" in RULE_TEXT
    assert "NEVER combine multiple asks" in RULE_TEXT
    assert "State that minimum ONLY when" in RULE_TEXT
    assert RULE_TEXT.startswith("You MUST ask ONLY ONE single question")
    assert "If they just said good morning or hello" in RULE_TEXT
    assert "NEVER invent or hallucinate options like Square Boxes" in RULE_TEXT


def test_unknown_design_count_uses_the_single_design_minimum():
    state = make_state("boxes")
    _fill(state, "product", "boxes")
    _fill(state, "quantity", "500")
    assert state.quantity_below_standard()
    _fill(state, "quantity", "1000")
    assert state.quantity_below_standard() is False
    _fill(state, "quantity", "500")
    _fill(state, "skus", "2")
    assert state.quantity_below_standard() is False
