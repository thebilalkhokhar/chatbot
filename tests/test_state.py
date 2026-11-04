from __future__ import annotations

from chatbot.bot import canon
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
    # Asterisk, spaced x, and "by" fold to the same stored shape.
    assert normalise_size("2*2") == "2x2"
    assert normalise_size("2 * 2") == "2x2"
    assert normalise_size("2 x 2") == "2x2"
    assert normalise_size("2 by 2") == "2x2"
    assert normalise_size("2×2 inches") == "2x2 in"
    assert normalise_size("4*6*2 cm") == "4x6x2 cm"


def test_asterisk_and_by_sizes_extract_without_reask():
    from chatbot.bot.state import SIZE_DIM_RE, normalise_dimension_separators

    for raw in ("2*2", "2 * 2", "2 x 2", "2 by 2", "2×2", "4*6*2"):
        assert SIZE_DIM_RE.search(normalise_dimension_separators(raw)), raw
        state = make_state(raw)
        updates = extract_fields(raw, "sizes", state)
        assert "sizes" in updates, raw
        accepted, rejected = apply_field_updates(state, updates, raw)
        assert "sizes" in accepted, raw
        assert "sizes" not in rejected
        assert "x" in state.fields["sizes"].value
        assert state.fields["sizes"].status == STATUS_VISITOR


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
    state.last_question = "style"
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
    assert use_case_from("mailer boxes for shipping candles") in {"candles", "shipping candles"}
    assert use_case_from("rigid boxes for my candle business") == "candle business"
    assert use_case_from("labels for retail") == "retail"
    assert use_case_from("I need boxes") == ""
    # "{product} for {purpose}" — already answered; do not ask use case again.
    assert use_case_from("labels for whisky bottle") == "whisky bottle"
    assert use_case_from("custom labels for honey jars") == "honey jars"
    assert use_case_from("boxes for candles") == "candles"
    assert use_case_from("looking for boxes") == ""
    assert use_case_from("labels for example") == ""
    # OCR brief lines: purpose must not truncate before QUANTITY/SIZE/FINISH.
    assert (
        use_case_from(
            "labels for coffee pouches QUANTITY: 250 SIZE: 10x15 CM FINISH: TO BE CONFIRMED"
        )
        == "coffee pouches"
    )
    # "{purpose} {product}" — whiskey bottle label, not only "labels for …".
    assert use_case_from("whiskey bottle label") == "whiskey bottle"
    assert use_case_from("whisky bottle labels") == "whisky bottle"
    assert use_case_from("honey jar stickers") == "honey jar"
    assert use_case_from("custom labels") == ""
    # A product family is the product field, not a use case — unless it is the
    # purpose after a head product (pouches for … coffee bags).
    assert use_case_from("pouches for packing coffee bags") in {
        "coffee bags",
        "packing coffee bags",
        "",
    }


def test_no_preference_on_size_becomes_to_be_confirmed():
    """Size unsure: 'no preference' (UNSPECIFIED) must waive like 'not sure'."""
    from chatbot.bot.state import TO_BE_CONFIRMED, STATUS_WAIVED

    state = make_state("no preference")
    state.fields["product"].value = "labels"
    state.fields["product"].status = STATUS_VISITOR
    state.last_question = "sizes"
    updates = extract_fields("no preference", "sizes", state)
    assert updates.get("sizes") == TO_BE_CONFIRMED
    accepted, _ = apply_field_updates(state, updates, "no preference")
    assert accepted.get("sizes") == TO_BE_CONFIRMED
    assert state.fields["sizes"].status == STATUS_WAIVED
    assert "sizes" not in state.ask_set()


def test_i_dont_know_on_use_case_becomes_to_be_confirmed():
    from chatbot.bot.state import TO_BE_CONFIRMED, STATUS_WAIVED

    state = make_state("i dont know")
    state.fields["product"].value = "labels"
    state.fields["product"].status = STATUS_VISITOR
    state.last_question = "use_case"
    updates = extract_fields("i dont know", "use_case", state)
    assert updates.get("use_case") == TO_BE_CONFIRMED
    accepted, _ = apply_field_updates(state, updates, "i dont know")
    assert accepted.get("use_case") == TO_BE_CONFIRMED
    assert state.fields["use_case"].status == STATUS_WAIVED


def test_to_be_confirmed_waives_finish_without_phrase_matching():
    """LLM (or extract) may write 'to be confirmed'; apply must waive, not re-ask."""
    from chatbot.bot.state import TO_BE_CONFIRMED, STATUS_WAIVED

    state = make_state("hmm leave that for later")
    state.last_question = "finishes"
    accepted, rejected = apply_field_updates(
        state,
        {"finishes": TO_BE_CONFIRMED},
        "hmm leave that for later",
        source="model",
    )
    assert accepted.get("finishes") == TO_BE_CONFIRMED
    assert rejected == {}
    assert state.fields["finishes"].status == STATUS_WAIVED
    assert state.fields["finishes"].value == TO_BE_CONFIRMED
    assert "finishes" not in state.ask_set()


def test_catalogue_material_from_model_stays_suggested_not_visitor():
    """PP white vinyl must not lock as visitor fact with raw text stolen from '300'."""
    from chatbot.bot.state import BASIS_CATALOGUE, BASIS_MODEL, STATUS_SUGGESTED

    state = make_state("300")
    state.last_question = "quantity"
    accepted, _rejected = apply_field_updates(
        state,
        {"material": "PP white vinyl", "quantity": "300"},
        "300",
        source="model",
        bases={"material": BASIS_CATALOGUE},
    )
    assert accepted.get("material") == "PP white vinyl"
    assert state.fields["material"].status == STATUS_SUGGESTED
    assert state.fields["material"].basis == BASIS_MODEL
    assert state.fields["material"].raw_visitor_text == ""


def test_model_cannot_tbc_size_while_use_case_is_open():
    """Regression: 'coffee beans' use-case turn must not waive size via model fields."""
    from chatbot.bot.state import TO_BE_CONFIRMED, STATUS_UNKNOWN, STATUS_VISITOR

    state = make_state("coffee beans")
    state.fields["product"].value = "bags"
    state.fields["product"].status = STATUS_VISITOR
    state.last_question = "use_case"
    accepted, rejected = apply_field_updates(
        state,
        {"use_case": "coffee beans", "sizes": TO_BE_CONFIRMED},
        "coffee beans",
        source="model",
    )
    assert accepted.get("use_case") == "coffee beans"
    assert "sizes" in rejected
    assert state.fields["sizes"].status == STATUS_UNKNOWN
    assert not state.fields["sizes"].value
    # Soft email is first; size stays missing behind it.
    assert state.ask_set() == ["email"]
    state.flags["soft_email_asked"] = True
    state.fields["email"].attempts = 1
    assert "sizes" in state.ask_set()


def test_not_sure_on_finish_question_waives_finish():
    from chatbot.bot.state import TO_BE_CONFIRMED, STATUS_WAIVED

    state = make_state("not sure")
    state.fields["product"].value = "labels"
    state.fields["product"].status = STATUS_VISITOR
    state.last_question = "finishes"
    updates = extract_fields("not sure", "finishes", state)
    assert updates.get("finishes") == TO_BE_CONFIRMED
    accepted, _ = apply_field_updates(state, updates, "not sure")
    assert accepted.get("finishes") == TO_BE_CONFIRMED
    assert state.fields["finishes"].status == STATUS_WAIVED
    assert "finishes" not in state.ask_set()


def test_no_idea_is_not_a_recommendation_ask():
    from chatbot.bot.state import wants_recommendation

    for text in ("No idea", "no idea", "I have no idea", "i have no idea."):
        assert not wants_recommendation(text)
    assert wants_recommendation("any ideas")
    assert wants_recommendation("ideas?")
    assert wants_recommendation("give me ideas")


def test_not_yet_waives_open_catalogue_field():
    from chatbot.bot.state import TO_BE_CONFIRMED, STATUS_WAIVED, UNSPECIFIED_RE

    assert UNSPECIFIED_RE.match("not yet")
    assert UNSPECIFIED_RE.match("Not yet.")
    assert UNSPECIFIED_RE.match("not yet sure")
    state = make_state("not yet")
    state.fields["product"].value = "boxes"
    state.fields["product"].status = STATUS_VISITOR
    state.last_question = "finishes"
    updates = extract_fields("not yet", "finishes", state)
    assert updates.get("finishes") == TO_BE_CONFIRMED
    accepted, rejected = apply_field_updates(state, updates, "not yet")
    assert accepted.get("finishes") == TO_BE_CONFIRMED
    assert rejected == {}
    assert state.fields["finishes"].status == STATUS_WAIVED


def test_no_idea_on_finish_style_material_waives():
    """Regression: 'idea' in 'no idea' must not block the uncertainty waiver."""
    from chatbot.bot.state import TO_BE_CONFIRMED, STATUS_WAIVED

    cases = (
        ("finishes", "No idea", TO_BE_CONFIRMED),
        ("style", "no idea", "no preference"),
        ("material", "I have no idea", "no preference"),
    )
    for field, text, expected in cases:
        state = make_state(text)
        state.fields["product"].value = "boxes"
        state.fields["product"].status = STATUS_VISITOR
        state.last_question = field
        updates = extract_fields(text, field, state)
        assert updates.get(field) == expected, (field, text, updates)
        accepted, rejected = apply_field_updates(state, updates, text)
        assert accepted.get(field) == expected, (field, text, accepted, rejected)
        assert field not in rejected
        assert state.fields[field].status == STATUS_WAIVED
        assert field not in state.ask_set()


def test_labels_for_pizza_box_locks_labels_not_boxes():
    """Head product wins when purpose names another family (attachment ambiguity)."""
    from chatbot.bot.state import family_of, headed_product_family

    for text in (
        "labels for my pizza box",
        "labels for pizza boxes",
        "pizza box labels",
        "stickers for shipping bags",
    ):
        assert family_of(text) == "labels", text
        assert headed_product_family(text) == "labels", text

    state = make_state("labels for my pizza box")
    updates = extract_fields("labels for my pizza box", "product", state)
    assert updates["product"] == "labels"
    assert updates["use_case"] == "pizza box"
    accepted, rejected = apply_field_updates(state, updates, "labels for my pizza box")
    assert accepted["product"] == "labels"
    assert accepted["use_case"] == "pizza box"
    assert rejected == {}
    assert state.family() == "labels"
    assert "product" not in state.ask_set()


def test_boxes_and_labels_stays_ambiguous_for_hybrid():
    from chatbot.bot.state import family_candidates, family_of, headed_product_family

    text = "boxes and labels"
    assert family_of(text) == "unknown"
    assert headed_product_family(text) == "unknown"
    assert family_candidates(text) == ["boxes", "labels"]
    assert use_case_from(text) == ""


def test_product_for_purpose_extracts_use_case_with_the_product():
    state = make_state("labels for whisky bottle")
    updates = extract_fields("labels for whisky bottle", "", state)
    assert updates["product"] == "labels"
    assert updates["use_case"] == "whisky bottle"
    accepted, _ = apply_field_updates(state, updates, "labels for whisky bottle")
    assert accepted["use_case"] == "whisky bottle"
    assert "use_case" not in state.ask_set()


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


def test_international_phone_is_captured_when_asked():
    # US-only PHONE_RE skipped +92… so the bot re-asked and dumped company contact.
    state = make_state("I need boxes")
    state.last_question = "phone"
    for raw in ("+923134432915", "923134432915", "+44 7911 123456"):
        state.fields["phone"].value = ""
        state.fields["phone"].status = STATUS_UNKNOWN
        updates = extract_fields(raw, "phone", state)
        assert updates.get("phone") == raw, raw
        accepted, _ = apply_field_updates(state, updates, raw)
        assert accepted["phone"] == raw
        assert state.fields["phone"].status == STATUS_VISITOR


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
    assert question == "What will you be using the boxes for?"
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
    assert constraint.startswith("You may ask about: use case, sizes, quantity.")


def test_use_case_is_asked_and_does_not_stall_the_quote():
    state = make_state("boxes")
    _fill(state, "product", "boxes")
    _fill(state, "sizes", "4x6 in")
    _fill(state, "quantity", "1000")
    assert state.specs_done()
    assert state.ask_set()[0] == "use_case"
    state.fields["use_case"].attempts = 2
    assert "use_case" not in state.ask_set()
    # Soft email comes once right after product + use case.
    assert state.next_question()[0] == "email"
    state.flags["soft_email_asked"] = True
    state.fields["email"].attempts = 1
    assert state.next_question()[0] == "style"
    assert state.next_question() is not None


def test_the_script_is_only_the_wording_once_a_field_is_selected():
    from chatbot.bot.state import SOFT_EMAIL_QUESTION

    state = make_state("boxes")
    _fill(state, "product", "boxes")
    _fill(state, "use_case", "candles")
    key, question = state.next_question()
    assert key == "email"
    assert question == SOFT_EMAIL_QUESTION
    state.flags["soft_email_asked"] = True
    state.fields["email"].attempts = 1
    _fill(state, "sizes", "4x6 in")
    _fill(state, "quantity", "1000")
    key, question = state.next_question()
    assert key == "style"
    assert question == "What style of box do you need, or can you share a reference image?"


def test_exhausted_use_case_asks_leave_the_missing_list():
    state = make_state("I need labels")
    _fill(state, "product", "labels")
    assert any("What it is for" in item for item in state.missing_for_prompt())
    state.fields["use_case"].attempts = 2
    assert "use_case" not in state.ask_set()
    assert not any("What it is for" in item for item in state.missing_for_prompt())


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
    state.flags["soft_email_asked"] = True
    state.fields["email"].attempts = 1
    assert state.ask_set()[0] == "sizes"
    assert state.next_question()[1] == "Is 100x150 in inches, cm, or mm?"
    assert "sizes" not in dict(state.do_not_ask())


def test_soft_email_asks_once_after_product_and_use_case():
    from chatbot.bot.state import SOFT_EMAIL_QUESTION

    state = make_state("boxes for candles")
    _fill(state, "product", "boxes")
    _fill(state, "use_case", "candles")
    assert state.ready_for_soft_email()
    assert state.ask_set() == ["email"]
    assert state.next_question() == ("email", SOFT_EMAIL_QUESTION)
    assert "phone" not in state.ask_set()

    # Soft ask consumed — size/qty continue even with no email.
    state.flags["soft_email_asked"] = True
    state.fields["email"].attempts = 1
    assert state.ask_set()[0] == "sizes"

    _fill(state, "sizes", "4x6 in")
    _fill(state, "quantity", "1000")
    allowed = state.ask_set()
    assert "email" not in allowed
    assert "phone" not in allowed
    assert allowed[0] == "style"
    assert "material" in allowed and "finishes" in allowed and "skus" in allowed

    _fill(state, "style", "mailer")
    _fill(state, "material", "kraft")
    _fill(state, "finishes", "matte")
    _fill(state, "skus", "1")
    # Quote-ready and email still empty → closing ask.
    assert state.ask_set()[0] == "email"


def test_soft_email_skip_keeps_product_questions_open():
    state = make_state("boxes for candles")
    _fill(state, "product", "boxes")
    _fill(state, "use_case", "candles")
    state.flags["soft_email_asked"] = True
    state.fields["email"].attempts = 1
    assert not state.fields["email"].done
    assert state.ask_set()[0] == "sizes"


def test_a_settled_style_is_not_overwritten_or_left_in_the_ask_set():
    state = make_state("pizza boxes")
    _fill(state, "product", "boxes")
    _fill(state, "style", "mailer")
    state.last_question = "material"
    accepted, rejected = apply_field_updates(
        state, {"style": "rigid", "material": "rigid board"}, "rigid board"
    )
    assert state.fields["style"].value == "mailer"
    assert "style" in rejected
    assert accepted.get("material") == "rigid board"
    assert "style" not in state.ask_set()
    assert "Locked, already accepted: style" in state.ask_constraint()
    assert canon.asks_for_our_contact("sure. testing@mail.com is my email address") is False
    assert canon.asks_for_location("sure. testing@mail.com is my email address") is False
    assert "contact" not in canon.topics_to_answer("sure. testing@mail.com is my email address")
    assert "location" not in canon.topics_to_answer("sure. testing@mail.com is my email address")


def test_size_turn_does_not_wipe_settled_use_case_or_product():
    # Regression: after "labels for whisky bottle", entering 15*20 must keep
    # use_case and product locked — never clear them or put use_case back in ask.
    state = make_state("labels for whisky bottle")
    updates = extract_fields("labels for whisky bottle", "product", state)
    apply_field_updates(state, updates, "labels for whisky bottle")
    assert state.fields["use_case"].value == "whisky bottle"
    assert state.fields["product"].value == "labels"
    state.last_question = "sizes"

    size_updates = extract_fields("15*20", "sizes", state)
    accepted, rejected = apply_field_updates(state, size_updates, "15*20")
    assert accepted.get("sizes") == "15x20"
    assert state.fields["use_case"].value == "whisky bottle"
    assert state.fields["product"].value == "labels"
    assert "use_case" not in state.ask_set()

    # A model echo must not rewrite the settled use case either.
    _accepted, model_rejected = apply_field_updates(
        state,
        {"use_case": "product label", "product": "stickers"},
        "15*20",
        source="model",
    )
    assert "use_case" in model_rejected
    assert "product" in model_rejected
    assert state.fields["use_case"].value == "whisky bottle"
    assert state.fields["product"].value == "labels"


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
    assert "You may ask about: use case, sizes, quantity." in user
    assert "use_case" not in user.split("ASK SET CONSTRAINT", 1)[-1].split("FACTS", 1)[0]
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


def test_invalid_email_is_rejected_and_detected():
    from chatbot.bot.state import looks_like_invalid_email, valid_email

    assert valid_email("buyer@example.com")
    assert not valid_email("buyer@")
    assert not valid_email("buyer@gmail")
    assert not valid_email("not-an-email")
    assert looks_like_invalid_email("buyer@")
    assert looks_like_invalid_email("buyer@gmail")
    assert looks_like_invalid_email("gmail.com")
    assert not looks_like_invalid_email("buyer@example.com")

    state = make_state("buyer@")
    state.last_question = "email"
    accepted, rejected = apply_field_updates(state, {"email": "buyer@"}, "buyer@")
    assert "email" not in accepted
    assert rejected.get("email") == "buyer@"
    assert state.fields["email"].value == ""


def test_refusing_contact_waives_email_and_phone():
    phrases = (
        "i don't want to share",
        "i have not any",
        "I don't have an email",
        "i dont have any email",
        "I don't have any email",
    )
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
    assert "NEVER combine fields in one sentence" in RULE_TEXT
    assert "State that minimum ONLY when" in RULE_TEXT
    assert RULE_TEXT.startswith("You MUST ask ONLY ONE single question")
    assert "If they just said good morning or hello" in RULE_TEXT
    assert "NEVER invent names that are not in the primer" in RULE_TEXT
    assert "ask ONCE for their email (soft ask" in RULE_TEXT
    assert "Once a style or finish is accepted, it is locked" in RULE_TEXT
    assert "You can reach the team at Support@print247.us or +1 (832) 807-3429." in RULE_TEXT
    assert "alternative materials when only one standard material exists" in RULE_TEXT
    assert "do not have an email" in RULE_TEXT
    assert "Stay inside the active product family" in RULE_TEXT
    assert "Always write your reply in English" in RULE_TEXT


def test_size_not_sure_does_not_waive_material_on_the_side():
    state = make_state("not sure")
    _fill(state, "product", "boxes")
    _fill(state, "use_case", "for pizza")
    _fill(state, "quantity", "500")
    _fill(state, "style", "no preference", status=STATUS_WAIVED)
    state.last_question = "sizes"
    accepted, rejected = apply_field_updates(
        state,
        {"sizes": "not sure", "material": "not sure"},
        "not sure",
        source="model",
    )
    assert accepted.get("sizes") == "to be confirmed"
    assert "material" in rejected or not state.fields["material"].done
    assert state.fields["material"].value in {"", "not sure"}
    assert state.fields["material"].status != STATUS_WAIVED


def test_box_material_alias_answers_are_accepted_without_relisting_options():
    """Visitor 'SBS' / parenthetical long form must settle material via registry aliases."""
    from pathlib import Path

    from chatbot.bot.capability import Registry
    from chatbot.bot.state import needs_catalogue_options

    registry = Registry.load(Path(__file__).resolve().parents[2] / "kb")
    for answer, expected in (
        ("SBS", "SBS paperboard"),
        ("solid bleached sulfate", "SBS paperboard"),
    ):
        state = make_state("boxes", "display", answer)
        _fill(state, "product", "boxes")
        _fill(state, "style", "display")
        state.last_question = "material"
        updates = extract_fields(answer, "material", state, registry=registry)
        assert updates.get("material") == expected, (answer, updates)
        accepted, _rejected = apply_field_updates(
            state, updates, answer, registry=registry
        )
        assert accepted.get("material") == expected
        assert needs_catalogue_options(state, answer, accepted, registry=registry) == ""


def test_alternative_material_ask_does_not_fill_material_or_open_email():
    from chatbot.bot.state import is_option_request, wants_recommendation

    text = "suggest me materials other than PP white vinyl"
    assert wants_recommendation(text)
    assert is_option_request(text)
    assert "contact" not in canon.detect_topics("i dont have any email")

    state = make_state(text)
    _fill(state, "product", "labels")
    _fill(state, "use_case", "honey jars")
    _fill(state, "sizes", "to be confirmed", status=STATUS_WAIVED)
    _fill(state, "quantity", "200")
    _fill(state, "finishes", "spot uv")
    _fill(state, "skus", "2")
    state.flags["soft_email_asked"] = True
    state.fields["email"].attempts = 1
    state.last_question = "material"
    apply_field_updates(state, extract_fields(text, "material", state), text)
    assert not state.fields["material"].done
    assert state.fields["material"].value == ""
    assert "material" in state.ask_set()
    assert "email" not in state.ask_set()
    assert state.next_question() is not None
    assert state.next_question()[0] == "material"

    # A stale alternatives ask stored as the material value is repaired open.
    state.fields["material"].value = text
    state.fields["material"].status = STATUS_VISITOR
    assert "material" in state.repair_fields()
    assert not state.fields["material"].done
    assert "email" not in state.ask_set()


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


def test_feet_alone_sets_preferred_unit_not_a_size():
    state = make_state("banners")
    _fill(state, "product", "banners")
    state.last_question = "sizes"
    state.fields["sizes"].attempts = 1
    updates = extract_fields("feet", "sizes", state)
    assert "sizes" not in updates
    assert state.flags.get("size_preferred_unit") == "ft"
    assert state.fields["sizes"].attempts <= 1
    assert "feet" in state.question_for("sizes").lower()


def test_two_failed_size_asks_waive_instead_of_empty_ask_set():
    state = make_state("banners")
    _fill(state, "product", "banners")
    _fill(state, "quantity", "100")
    state.fields["sizes"].attempts = 2
    assert state.blocking_open()
    noted = state.finalize_stalled()
    assert "sizes" in noted
    assert state.fields["sizes"].status == STATUS_WAIVED
    assert state.fields["sizes"].value == "to be confirmed"
    assert not state.blocking_open()
    assert state.next_question() is not None


def test_use_case_survives_semicolon_clause_break():
    """Spanish/gloss intros often use ';' — must not drop 'for my coffee beans'."""
    from chatbot.bot.state import normalize_finish, normalize_extras_pick, field_shaped_attempt

    text = (
        "I need bags for my coffee beans; I am not sure what size to choose. "
        "I need a quantity of 350 units; could you suggest some styles?"
    )
    assert use_case_from(text) == "coffee beans"
    state = make_state(text)
    updates = extract_fields(text, "", state)
    assert updates.get("product") == "bags"
    assert updates.get("use_case") == "coffee beans"
    assert updates.get("quantity") == "350"

    assert normalize_finish("mate") == "matte"
    assert normalize_finish("material") is None  # mate must not match inside material
    assert field_shaped_attempt("finishes", "mate")
    assert normalize_extras_pick("cremallera") == "zipper"
    assert normalize_extras_pick("zipper and tear notch") == "zipper, tear notch"
