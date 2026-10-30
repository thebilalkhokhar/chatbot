from __future__ import annotations

from chatbot.bot.personas import PERSONAS
from chatbot.bot.state import BLOCKING_FIELDS, STATUS_UNKNOWN, STATUS_VISITOR, STATUS_WAIVED


def blockers(result) -> list[str]:
    return [issue["code"] for issue in result.issues if issue["severity"] == "block"]


def test_start_sets_persona_and_greeting(orchestrator):
    result = orchestrator.start("c-start")
    assert result.persona in {persona.name for persona in PERSONAS}
    assert "what are you looking" in result.reply.lower()
    assert blockers(result) == []


def test_first_product_message_asks_what_they_are_packing(orchestrator):
    # Behaviour 1: "boxes" is not a size. The ask-set leads with use_case.
    orchestrator.start("c-boxes")
    result = orchestrator.handle("c-boxes", "I need custom boxes")
    lowered = result.reply.lower()
    assert "inside" in lowered
    assert "box size" not in lowered
    assert result.reply.count("?") == 1
    assert blockers(result) == []
    assert result.accepted.get("product")


def test_answers_moq_and_lead_time_before_asking(orchestrator):
    orchestrator.start("c-facts")
    result = orchestrator.handle(
        "c-facts", "What is your MOQ and what is the lead time?"
    )
    lowered = result.reply.lower()
    assert "1,000" in result.reply
    assert "12-15 business days" in lowered
    assert "size" in lowered
    assert blockers(result) == []


def test_banner_never_gets_a_minimum(orchestrator):
    orchestrator.start("c-banner")
    orchestrator.handle("c-banner", "I need a banner")
    result = orchestrator.handle("c-banner", "What is the minimum order?")
    assert "no minimum" in result.reply.lower()
    assert "1,000" not in result.reply
    assert blockers(result) == []


def test_human_request_handoff(orchestrator):
    orchestrator.start("c-human")
    result = orchestrator.handle("c-human", "I want to talk to a human")
    assert result.handoff == "human"
    assert "specialist" in result.reply.lower()
    assert blockers(result) == []


def test_a_plain_quantity_is_accepted_without_the_minimum_lecture(orchestrator):
    orchestrator.start("c-small")
    orchestrator.handle("c-small", "I need custom boxes for shipping candles")
    orchestrator.handle("c-small", "4 x 6 x 2 inches")
    result = orchestrator.handle("c-small", "300")
    lowered = result.reply.lower()
    assert "smaller runs" not in lowered
    assert "1,000" not in result.reply
    assert "moq" not in lowered
    assert "?" in result.reply
    assert result.handoff == ""
    assert blockers(result) == []


def test_full_flow_reaches_quote_handoff(orchestrator):
    orchestrator.start("c-full")
    steps = [
        "I need custom boxes for shipping candles",
        "4 x 6 x 2 inches",
        "1000",
        "mailer box",
        "kraft",
        "matte",
        "1 design",
        "buyer@example.com",
    ]
    result = None
    for step in steps:
        result = orchestrator.handle("c-full", step)
        assert result.reply, f"no reply after {step!r}"
        assert blockers(result) == [], f"{step!r}: {blockers(result)}"
        if result.handoff:
            break
    assert result is not None
    assert result.handoff == "quote"
    assert "email your quote" in result.reply.lower()
    state = orchestrator.store.get_or_create("c-full")
    for key in BLOCKING_FIELDS:
        assert state.fields[key].done, key
    assert state.reachable()


def test_persona_rotation_uses_all_names(orchestrator):
    seen = set()
    for index in range(9):
        conversation_id = f"c-rotate-{index}"
        result = orchestrator.start(conversation_id)
        seen.add(result.persona)
    assert len(seen) == 9


def test_existing_conversation_keeps_persona(orchestrator):
    first = orchestrator.start("c-keep")
    orchestrator.handle("c-keep", "I need boxes")
    state = orchestrator.store.get_or_create("c-keep")
    assert state.persona == first.persona


def test_pack_count_is_not_an_order_quantity(orchestrator):
    orchestrator.start("c-pouch")
    result = orchestrator.handle("c-pouch", "flat pouch for my 2 count gummy")
    assert result.accepted.get("product")
    assert "inside" in result.reply.lower()
    state = orchestrator.store.get_or_create("c-pouch")
    assert not state.fields["quantity"].done
    assert blockers(result) == []


def test_bare_minimum_question_is_answered(orchestrator):
    orchestrator.start("c-min")
    result = orchestrator.handle("c-min", "Do you have a minimum")
    assert "1,000" in result.reply
    assert blockers(result) == []


def test_sign_is_a_banner(orchestrator):
    orchestrator.start("c-sign")
    result = orchestrator.handle("c-sign", "Parking Sign")
    assert result.accepted.get("product")
    assert orchestrator.store.get_or_create("c-sign").family() == "banners"
    assert "inside" in result.reply.lower()


def test_size_without_unit_asks_for_the_unit(orchestrator):
    orchestrator.start("c-unit")
    orchestrator.handle("c-unit", "mylar bags")
    result = orchestrator.handle("c-unit", "8x8x4")
    lowered = result.reply.lower()
    assert "inches" in lowered and "mm" in lowered


def test_finish_answer_does_not_fill_style(orchestrator):
    orchestrator.start("c-finish")
    orchestrator.handle("c-finish", "mylar bags")
    orchestrator.handle("c-finish", "8x8x4")
    result = orchestrator.handle("c-finish", "gloss")
    state = orchestrator.store.get_or_create("c-finish")
    assert state.fields["finishes"].done
    assert not state.fields["style"].done
    assert result.reply.count("?") == 1
    assert blockers(result) == []


def test_materials_question_is_answered(orchestrator):
    orchestrator.start("c-materials")
    result = orchestrator.handle("c-materials", "what materials do you have?")
    lowered = result.reply.lower()
    assert "pet" in lowered or "kraft" in lowered or "board" in lowered
    assert blockers(result) == []


def test_cheapest_is_treated_as_a_price_question(orchestrator):
    orchestrator.start("c-cheapest")
    result = orchestrator.handle("c-cheapest", "What is the cheapest option")
    assert "quote" in result.reply.lower()
    assert blockers(result) == []


def test_misspelled_robot_question_gets_disclosure(orchestrator):
    orchestrator.start("c-robort")
    result = orchestrator.handle("c-robort", "are you a robort?")
    assert "ai assistant" in result.reply.lower()
    assert blockers(result) == []


def test_tear_notch_explained(orchestrator):
    orchestrator.start("c-notch")
    result = orchestrator.handle("c-notch", "what is tear notch?")
    assert "tear notch" in result.reply.lower()
    assert blockers(result) == []


def test_material_availability_question_is_answered(orchestrator):
    orchestrator.start("c-mpet")
    result = orchestrator.handle("c-mpet", "dont you have MPET, CRAFT OR SOMETHING LIKE THAT?")
    lowered = result.reply.lower()
    assert "pet" in lowered or "kraft" in lowered
    assert blockers(result) == []


def test_packaging_types_question_is_answered(orchestrator):
    orchestrator.start("c-types")
    result = orchestrator.handle("c-types", "Could you suggest what types of packaging are available?")
    lowered = result.reply.lower()
    assert "boxes" in lowered and "bags" in lowered
    assert blockers(result) == []


def test_size_help_question_is_answered(orchestrator):
    orchestrator.start("c-sizehelp")
    result = orchestrator.handle(
        "c-sizehelp", "I am not sure of the size, do you know what size bag would fit my 10 gummies?"
    )
    assert "no standard size" in result.reply.lower()
    assert blockers(result) == []


def test_size_question_after_unknown_size_is_not_blocked(orchestrator):
    orchestrator.start("c-sizeq")
    orchestrator.handle("c-sizeq", "I need mylar bags for 10 gummies")
    orchestrator.handle("c-sizeq", "8x8")
    orchestrator.handle("c-sizeq", "gloss")
    result = orchestrator.handle(
        "c-sizeq", "I am not sure of the size, do you know what size bag would fit my 10 gummies?"
    )
    assert result.source != "fallback"
    assert result.blocked == []
    assert "no standard size" in result.reply.lower()


def test_custom_display_tray_is_a_box(orchestrator):
    orchestrator.start("c-tray")
    result = orchestrator.handle("c-tray", "I need a custom countertop display tray")
    assert result.accepted.get("product")
    assert orchestrator.store.get_or_create("c-tray").family() == "boxes"
    assert "inside" in result.reply.lower()
    assert blockers(result) == []


def test_capability_question_gets_a_yes(orchestrator):
    orchestrator.start("c-cap")
    result = orchestrator.handle("c-cap", "Do you guys do custom shaped pouches?")
    assert result.reply.lower().startswith("yes")
    assert blockers(result) == []


def test_international_shipping_question_is_answered(orchestrator):
    orchestrator.start("c-intl")
    orchestrator.handle("c-intl", "I need custom boxes")
    result = orchestrator.handle("c-intl", "can you ship orders to china?")
    lowered = result.reply.lower()
    assert "outside the usa" in lowered or "your country" in lowered
    assert result.reply.count("?") == 1
    assert blockers(result) == []
    assert "possibly_unanswered_question" not in [issue["code"] for issue in result.issues]
    assert "unanswered_question" not in [issue["code"] for issue in result.issues]


def test_domestic_shipping_question_stays_short(orchestrator):
    orchestrator.start("c-ship")
    orchestrator.handle("c-ship", "I need custom boxes")
    result = orchestrator.handle("c-ship", "what are your shipping options?")
    lowered = result.reply.lower()
    assert "ups" in lowered
    assert "outside the usa" not in lowered
    assert blockers(result) == []


def test_zipper_options_question_is_answered(orchestrator):
    orchestrator.start("c-zip")
    result = orchestrator.handle("c-zip", "could you please clarify which zipper options you have?")
    assert "press-to-close" in result.reply.lower()
    assert blockers(result) == []


def test_long_multi_question_inquiry_answers_top_questions(orchestrator):
    orchestrator.start("c-b2b")
    message = (
        "We want a custom display tray for 25 bars. Could you confirm you can make it? "
        "Please share your minimum order quantity, pricing, samples, production lead time, "
        "shipping cost, and your address. My email is buyer@example.com."
    )
    result = orchestrator.handle("c-b2b", message)
    lowered = result.reply.lower()
    assert "quote" in lowered
    assert "1,000" in result.reply
    assert blockers(result) == []


def test_handoff_still_answers_the_question(orchestrator):
    orchestrator.start("c-b2b-human")
    result = orchestrator.handle("c-b2b-human", "Can I talk to a human? Also what is the price?")
    assert result.handoff == "human"
    lowered = result.reply.lower()
    assert "quote" in lowered
    assert "specialist" in lowered
    assert blockers(result) == []


def test_four_topics_in_one_message_hands_off_to_a_specialist(orchestrator):
    orchestrator.start("c-complex")
    result = orchestrator.handle(
        "c-complex", "What is the price, the MOQ, the lead time and free samples?"
    )
    assert result.handoff == "complex"
    lowered = result.reply.lower()
    assert "quote" in lowered
    assert "1,000" in result.reply
    assert "specialist" in lowered
    assert blockers(result) == []


def test_food_box_question_gets_a_suggestion(orchestrator):
    orchestrator.start("c-food")
    orchestrator.handle("c-food", "I need custom boxes")
    result = orchestrator.handle("c-food", "suggest me best suite box for dry meat/")
    lowered = result.reply.lower()
    assert "sbs" in lowered or "food-grade" in lowered
    assert "size" in lowered
    assert result.reply.count("?") == 1
    assert blockers(result) == []


def test_dry_meat_suggestion_covers_bags_and_boxes(orchestrator):
    orchestrator.start("c-dry")
    result = orchestrator.handle("c-dry", "suggest me something suitable for dry meat")
    lowered = result.reply.lower()
    assert "mylar" in lowered or "pouch" in lowered
    assert "carton" in lowered or "box" in lowered
    assert result.reply.count("?") == 1
    assert blockers(result) == []


def test_style_question_keeps_the_product_and_answers(orchestrator):
    orchestrator.start("c-style-q")
    orchestrator.handle("c-style-q", "I need bags for shipping coffee")
    orchestrator.handle("c-style-q", "12 x 51 cm")
    orchestrator.handle("c-style-q", "1000")
    result = orchestrator.handle("c-style-q", "what style of boxes do you have")
    lowered = result.reply.lower()
    state = orchestrator.store.get_or_create("c-style-q")
    assert state.fields["product"].value == "bags"
    assert not state.fields["style"].done
    assert "mailer" in lowered or "stand-up" in lowered
    assert "style of bag" in lowered
    assert result.reply.count("?") == 1
    assert blockers(result) == []


def test_style_answer_later_in_the_chat_is_kept(orchestrator):
    orchestrator.start("c-style-late")
    orchestrator.handle("c-style-late", "I need bags for shipping coffee")
    orchestrator.handle("c-style-late", "12 x 51 cm")
    orchestrator.handle("c-style-late", "1000")
    orchestrator.handle("c-style-late", "what style of boxes do you have")
    result = orchestrator.handle("c-style-late", "i want standup style bags")
    state = orchestrator.store.get_or_create("c-style-late")
    assert state.fields["style"].value == "stand-up"
    assert state.fields["product"].value == "bags"
    assert "material" in result.reply.lower()
    assert blockers(result) == []


def test_clarifying_question_names_the_product(orchestrator):
    orchestrator.start("c-clarify")
    orchestrator.handle("c-clarify", "I need bags for shipping coffee")
    orchestrator.handle("c-clarify", "12 x 51 cm")
    orchestrator.handle("c-clarify", "1000")
    orchestrator.handle("c-clarify", "flat")
    result = orchestrator.handle("c-clarify", "for what? bag or box?")
    lowered = result.reply.lower()
    assert "your flat bags" in lowered
    assert "material" in lowered
    assert "possibly_unanswered_question" not in [issue["code"] for issue in result.issues]
    assert result.reply.count("?") == 1
    assert blockers(result) == []


def test_saved_question_in_a_field_is_repaired(orchestrator):
    state = orchestrator.store.get_or_create("c-repair")
    state.fields["product"].value = "bags"
    state.fields["product"].status = STATUS_VISITOR
    state.fields["style"].value = "what style of boxes do you have"
    state.fields["style"].status = STATUS_VISITOR
    state.last_question = "finishes"
    orchestrator.store.save(state)
    orchestrator.handle("c-repair", "gloss")
    state = orchestrator.store.get_or_create("c-repair")
    assert state.fields["style"].value == ""
    assert state.fields["style"].status == STATUS_UNKNOWN


def test_no_style_preference_gets_style_options(orchestrator):
    orchestrator.start("c-style-none")
    orchestrator.handle("c-style-none", "I need custom boxes for shipping candles")
    orchestrator.handle("c-style-none", "4 x 6 x 2 inches")
    orchestrator.handle("c-style-none", "1000")
    result = orchestrator.handle("c-style-none", "i dont have")
    lowered = result.reply.lower()
    assert "mailer" in lowered and "display boxes" in lowered
    assert "material" in lowered
    assert result.accepted.get("style") == "no preference"
    assert blockers(result) == []


def test_unknown_size_is_explained_not_stored_verbatim(orchestrator):
    orchestrator.start("c-size-unknown")
    orchestrator.handle("c-size-unknown", "I need custom boxes for shipping candles")
    result = orchestrator.handle("c-size-unknown", "not sure")
    lowered = result.reply.lower()
    assert "no standard size" in lowered
    assert "custom made" in lowered
    state = orchestrator.store.get_or_create("c-size-unknown")
    assert state.fields["sizes"].value == "to be confirmed"
    assert blockers(result) == []
    follow_up = orchestrator.handle("c-size-unknown", "matte")
    assert "inches, cm or mm" not in follow_up.reply.lower()
    state = orchestrator.store.get_or_create("c-size-unknown")
    assert state.last_question != "sizes"


def test_local_ui_resumes_after_handoff(orchestrator):
    orchestrator.start("c-ui-human")
    first = orchestrator.handle("c-ui-human", "I want to talk to a human", channel="ui")
    assert first.handoff == "human"
    second = orchestrator.handle("c-ui-human", "I need custom boxes", channel="ui")
    assert second.reply
    assert second.handoff == ""
    assert orchestrator.store.get_or_create("c-ui-human").handoff == ""


def test_webhook_channel_stays_handed_off(orchestrator):
    orchestrator.start("c-web-human")
    orchestrator.handle("c-web-human", "I want to talk to a human", channel="website")
    second = orchestrator.handle("c-web-human", "hello", channel="website")
    assert second.reply == ""
    assert second.flags.get("already_handed_off") is True


def test_contact_refusal_stops_the_email_loop(orchestrator):
    orchestrator.start("c-declined")
    for text in [
        "i need boxes for shipping candles",
        "4 x 6 x 2 inches",
        "1000",
        "mailer box",
        "kraft",
        "matte",
        "3 designs",
    ]:
        orchestrator.handle("c-declined", text)
    result = orchestrator.handle("c-declined", "no i don;t want it")
    assert result.handoff == "declined"
    lowered = result.reply.lower()
    assert "specialist" in lowered
    assert "email" not in lowered
    assert "?" not in result.reply
    state = orchestrator.store.get_or_create("c-declined")
    assert state.fields["email"].attempts >= 2
    assert state.fields["phone"].attempts >= 2
    follow_up = orchestrator.handle("c-declined", "no i dont want it")
    assert follow_up.reply == ""


def test_size_unit_follow_up_completes_the_size(orchestrator):
    orchestrator.start("c-unit-follow")
    orchestrator.handle("c-unit-follow", "I need custom boxes for shipping candles")
    first = orchestrator.handle("c-unit-follow", "100 x 150")
    assert "is 100x150 in inches, cm, or mm?" in first.reply.lower()
    result = orchestrator.handle("c-unit-follow", "mm")
    state = orchestrator.store.get_or_create("c-unit-follow")
    assert state.fields["sizes"].value == "100x150 mm"
    assert state.fields["sizes"].raw_visitor_text == "100x150 mm"
    assert state.fields["sizes"].status == STATUS_VISITOR
    assert "quantity" in result.reply.lower()
    assert blockers(result) == []


def test_live_field_echo_cannot_overwrite_an_answered_field(
    config, kb_index, tmp_path, monkeypatch
):
    from dataclasses import replace

    from chatbot.bot.composer import Composed
    from chatbot.bot.orchestrator import Orchestrator as Engine

    live_config = replace(config, mode="live", allow_live=True, api_key="test-key")
    engine = Engine(
        live_config,
        store_path=tmp_path / "live.sqlite3",
        index=kb_index,
        examples=[],
    )
    try:
        state = engine.store.get_or_create("c-live-echo")
        state.fields["product"].value = "boxes"
        state.fields["product"].status = STATUS_VISITOR
        state.fields["sizes"].value = "4 x 6 x 2 inches"
        state.fields["sizes"].status = STATUS_VISITOR
        state.fields["style"].value = "flat"
        state.fields["style"].status = STATUS_VISITOR
        state.last_question = "material"
        engine.store.save(state)

        monkeypatch.setattr(
            "chatbot.bot.orchestrator.live_turn",
            lambda *args, **kwargs: Composed(
                reply="Got it. What is the best email to send the quote to?",
                fields={
                    "product": "boxes",
                    "sizes": "4 x 6 x 2 inches",
                    "style": "no preference",
                    "material": "no preference",
                },
            ),
        )
        result = engine.handle("c-live-echo", "no preference")
        state = engine.store.get_or_create("c-live-echo")
        assert state.fields["style"].value == "flat"
        assert state.fields["material"].value == "no preference"
        assert result.source == "live"
    finally:
        engine.close()


def test_live_echo_cannot_overwrite_a_field_accepted_this_turn(
    config, kb_index, tmp_path, monkeypatch
):
    from dataclasses import replace

    from chatbot.bot.composer import Composed
    from chatbot.bot.orchestrator import Orchestrator as Engine

    live_config = replace(config, mode="live", allow_live=True, api_key="test-key")
    engine = Engine(
        live_config,
        store_path=tmp_path / "live-same-turn.sqlite3",
        index=kb_index,
        examples=[],
    )
    try:
        state = engine.store.get_or_create("c-live-same")
        state.fields["product"].value = "bags"
        state.fields["product"].status = STATUS_VISITOR
        state.fields["sizes"].value = "12 x 51 cm"
        state.fields["sizes"].status = STATUS_VISITOR
        state.last_question = "style"
        engine.store.save(state)

        monkeypatch.setattr(
            "chatbot.bot.orchestrator.live_turn",
            lambda *args, **kwargs: Composed(
                reply="Got it. What finish do you prefer: matte, gloss or soft touch?",
                fields={"style": "no preference"},
            ),
        )
        result = engine.handle("c-live-same", "i want standup style bags")
        state = engine.store.get_or_create("c-live-same")
        assert state.fields["style"].value == "stand-up"
        assert result.source == "live"
    finally:
        engine.close()


def _ready_for_style(orchestrator, conversation_id: str) -> None:
    orchestrator.start(conversation_id)
    state = orchestrator.store.get_or_create(conversation_id)
    state.persona = "Ethan Wilson"
    for key, value in (
        ("product", "boxes"),
        ("use_case", "candles"),
        ("sizes", "4x6 in"),
        ("quantity", "1000"),
    ):
        state.set_field(key, value, raw=value, status=STATUS_VISITOR)
    state.last_question = "style"
    orchestrator.store.save(state)


def test_your_address_never_satisfies_style(orchestrator):
    _ready_for_style(orchestrator, "c-address")
    result = orchestrator.handle("c-address", "your address")
    state = orchestrator.store.get_or_create("c-address")
    assert state.fields["style"].value == ""
    assert not state.fields["style"].done
    assert "rosenberg" in result.reply.lower()
    assert blockers(result) == []


def test_ethan_identity_challenge_discloses_and_returns_to_the_order(orchestrator):
    # Turn 4 of the logged chat: the fallback treated "ai" as Adobe Illustrator
    # and lectured about file formats. v2 discloses once and returns to the order.
    orchestrator.start("c-ethan")
    state = orchestrator.store.get_or_create("c-ethan")
    state.persona = "Ethan Wilson"
    orchestrator.store.save(state)
    orchestrator.handle("c-ethan", "i am looking for boxes")
    result = orchestrator.handle("c-ethan", "you said you are ethan now you called ai")
    lowered = result.reply.lower()
    assert "ai assistant" in lowered
    assert "ethan" in lowered
    assert "print247" in lowered
    assert "pdf" not in lowered
    assert "eps" not in lowered
    assert "zip" not in lowered
    # The order was already asked what goes inside; the re-ask keeps that thread.
    assert "packing" in lowered
    assert blockers(result) == []


def test_fallback_answers_only_the_top_topic(orchestrator):
    orchestrator.start("c-fallback")
    state = orchestrator.store.get_or_create("c-fallback")
    state.add("visitor", "What is your MOQ, lead time and address?")
    reply = orchestrator._safe_fallback(state, state.next_question(), "")
    assert "1,000" in reply
    assert "12-15" not in reply
    assert "rosenberg" not in reply.lower()
    assert "which product" in reply.lower()


def test_fallback_identity_path_does_not_lecture(orchestrator):
    orchestrator.start("c-fallback-id")
    state = orchestrator.store.get_or_create("c-fallback-id")
    state.persona = "Ethan Wilson"
    state.add("visitor", "you said you are ethan now you called ai")
    reply = orchestrator._safe_fallback(state, ("use_case", "What will be inside it?"), "").lower()
    assert "ai assistant" in reply
    assert "ethan" in reply
    assert "pdf" not in reply
    assert "eps" not in reply


def test_a_greeting_is_not_answered_by_a_canned_line(orchestrator):
    orchestrator.start("c-morning")
    result = orchestrator.handle("c-morning", "good morning")
    assert result.reply != "Good morning."
    assert "?" in result.reply


def test_for_example_names_the_box_styles(orchestrator):
    _ready_for_style(orchestrator, "c-example")
    result = orchestrator.handle("c-example", "for example?")
    lowered = result.reply.lower()
    assert "mailer" in lowered and "display" in lowered and "gift" in lowered
    assert result.reply.count("?") == 1
    assert blockers(result) == []


def test_which_one_uses_the_catalogue_instead_of_the_clarifier(orchestrator):
    from chatbot.bot.state import is_context_question, is_option_request

    assert is_context_question("for what? bag or box?")
    assert not is_context_question("which one you have?")
    assert not is_context_question("for example?")
    assert is_option_request("which one you have?")
    _ready_for_style(orchestrator, "c-which")
    result = orchestrator.handle("c-which", "which one you have?")
    assert "mailer" in result.reply.lower()
    assert "for your boxes" not in result.reply.lower()
    assert blockers(result) == []


def test_metalized_during_a_style_ask_is_saved_and_acknowledged(orchestrator):
    _ready_for_style(orchestrator, "c-metal")
    result = orchestrator.handle("c-metal", "metalized")
    state = orchestrator.store.get_or_create("c-metal")
    assert state.fields["material"].value == "metalized"
    assert not state.fields["style"].done
    lowered = result.reply.lower()
    assert "metalized is noted" in lowered
    assert "style" in lowered
    assert blockers(result) == []


def test_a_greeting_is_answered_and_a_second_one_does_not_end_the_chat(orchestrator):
    orchestrator.start("c-morning")
    first = orchestrator.handle("c-morning", "morning")
    assert "good morning" in first.reply.lower()
    assert first.handoff == ""
    assert "?" in first.reply
    state = orchestrator.store.get_or_create("c-morning")
    assert not state.fields["product"].done
    second = orchestrator.handle("c-morning", "good morning")
    assert second.handoff == ""
    assert "good morning" in second.reply.lower()
    assert "specialist" not in second.reply.lower()
    state = orchestrator.store.get_or_create("c-morning")
    assert state.family() == "unknown"
    assert not state.fields["product"].value


def test_a_zero_in_any_dimension_is_not_stored(orchestrator):
    orchestrator.start("c-zero")
    orchestrator.handle("c-zero", "I need custom boxes for candles")
    result = orchestrator.handle("c-zero", "0x15")
    state = orchestrator.store.get_or_create("c-zero")
    assert not state.fields["sizes"].value
    assert "size_pending_unit" not in state.flags
    assert blockers(result) == []
    orchestrator.handle("c-zero", "10x0x5")
    state = orchestrator.store.get_or_create("c-zero")
    assert not state.fields["sizes"].value


def test_a_complaint_about_the_minimum_does_not_recite_it(orchestrator):
    orchestrator.start("c-moq-complaint")
    result = orchestrator.handle(
        "c-moq-complaint", "Your minimum is too high. I only need 100."
    )
    lowered = result.reply.lower()
    assert "1,000" not in result.reply
    assert "standard moq" not in lowered
    assert "smaller runs" not in lowered
    assert blockers(result) == []


def test_a_quantity_does_not_trigger_the_minimum_sentence(orchestrator):
    orchestrator.start("c-moq-once")
    orchestrator.handle("c-moq-once", "I need boxes for pizza")
    orchestrator.handle("c-moq-once", "12x15 inches")
    stated = orchestrator.handle("c-moq-once", "500")
    assert "1,000" not in stated.reply
    assert "minimum" not in stated.reply.lower()
    asked = orchestrator.handle("c-moq-once", "What is your minimum?")
    assert "1,000" in asked.reply


def test_turn_cap_skips_the_greeting_and_a_turn_that_fills_a_field(orchestrator):
    orchestrator.start("c-cap-stall")
    state = orchestrator.store.get_or_create("c-cap-stall")
    state.turn_count = state.turn_count + 12
    orchestrator.store.save(state)
    stalled = orchestrator.handle("c-cap-stall", "hmm")
    assert stalled.handoff == "max_turns"

    orchestrator.start("c-cap-move")
    state = orchestrator.store.get_or_create("c-cap-move")
    state.turn_count = state.turn_count + 12
    orchestrator.store.save(state)
    moving = orchestrator.handle("c-cap-move", "I need boxes for pizza")
    assert moving.handoff == ""
    assert moving.accepted.get("product") == "boxes"


def test_an_unattested_build_is_noted_for_the_team(orchestrator):
    from chatbot.bot.guards import BLOCK, GuardResult, Issue

    state = orchestrator.store.get_or_create("c-note")
    state.add("visitor", "gloss")
    guard = GuardResult(
        issues=[
            Issue(
                "unknown_capability_unhedged",
                BLOCK,
                "An unattested combination needs the team to confirm the build.",
                "kraft gloss",
            ),
            Issue(
                "unsupported_configuration",
                BLOCK,
                "That combination is not an attested offering, and the reply says we make it.",
                "kraft gloss",
            ),
        ]
    )
    reply = orchestrator._safe_fallback(
        state,
        ("style", "What style of box do you need, or can you share a reference image?"),
        "",
        guard=guard,
        configs=[{"family": "boxes", "material": "kraft", "finish": "gloss"}],
    )
    assert reply == (
        "Kraft and Gloss are noted. That build needs the team to confirm. "
        "What style of box do you need, or can you share a reference image?"
    )


def test_a_catalogue_dump_is_not_read_back_as_the_order(orchestrator):
    from chatbot.bot.guards import BLOCK, GuardResult, Issue

    state = orchestrator.store.get_or_create("c-dump")
    state.set_field("product", "boxes", status=STATUS_VISITOR)
    state.add("visitor", "i want boxes")
    guard = GuardResult(
        issues=[
            Issue(
                "unknown_capability_unhedged",
                BLOCK,
                "An unattested combination needs the team to confirm the build.",
                "cbd",
            )
        ]
    )
    reply = orchestrator._safe_fallback(
        state,
        ("use_case", "What will be inside it, or who is it going to?"),
        "",
        guard=guard,
        configs=[
            {
                "style": "CBD Boxes",
                "material": "White cardboard",
                "finish": [
                    "Gloss lamination",
                    "Matte lamination",
                    "Soft touch",
                    "Spot UV",
                    "Foil printing",
                ],
            }
        ],
    )
    assert "noted" not in reply.lower()
    assert "cbd" not in reply.lower()
    assert "inside" in reply.lower()


def test_a_sentence_stuffed_into_a_config_is_not_noted(orchestrator):
    from chatbot.bot.guards import BLOCK, GuardResult, Issue

    state = orchestrator.store.get_or_create("c-sentence")
    state.set_field("product", "boxes", status=STATUS_VISITOR)
    state.set_field("use_case", "pizza", status=STATUS_VISITOR)
    state.set_field("sizes", "11x15x2 in", status=STATUS_VISITOR)
    state.set_field("quantity", "300", status=STATUS_VISITOR)
    state.set_field("style", "no preference", status=STATUS_WAIVED)
    state.set_field("material", "kraft", status=STATUS_VISITOR)
    state.set_field("finishes", "matte", status=STATUS_VISITOR)
    state.last_question = "finishes"
    state.add("visitor", "matte")
    guard = GuardResult(
        issues=[
            Issue("unknown_option", BLOCK, "not in the boxes style vocabulary.", "Mailing/Display"),
            Issue(
                "unknown_capability_unhedged",
                BLOCK,
                "An unattested combination needs the team to confirm the build.",
                "kraft",
            ),
        ]
    )
    reply = orchestrator._safe_fallback(
        state,
        ("skus", "How many total designs or SKUs do you have?"),
        "",
        guard=guard,
        configs=[
            {
                "style": "Mailing/Display style not specified in your goal; using kraft and matte lamination",
                "finish": ["Matte lamination", "Drip off", "Spot gloss", "Window", "Handle"],
            }
        ],
    )
    assert "not specified" not in reply.lower()
    assert "noted" not in reply.lower()
    assert "designs" in reply.lower()


def test_handoff_does_not_call_the_model(config, kb_index, tmp_path, monkeypatch):
    from dataclasses import replace

    from chatbot.bot.orchestrator import Orchestrator as Engine

    live_config = replace(config, mode="live", allow_live=True, api_key="test-key", max_turns=12)
    engine = Engine(live_config, store_path=tmp_path / "handoff-live.sqlite3", index=kb_index, examples=[])
    try:
        def boom(*_args, **_kwargs):
            raise AssertionError("the model was called after handoff")

        monkeypatch.setattr("chatbot.bot.orchestrator.live_turn", boom)
        engine.start("c-no-model")
        result = engine.handle("c-no-model", "I want to talk to a human")
        assert result.handoff == "human"
        assert result.source != "live"
        assert "specialist" in result.reply.lower()
    finally:
        engine.close()
