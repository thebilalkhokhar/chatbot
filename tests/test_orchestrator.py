from __future__ import annotations

from chatbot.bot.personas import PERSONAS
from chatbot.bot.state import BLOCKING_FIELDS, STATUS_UNKNOWN, STATUS_VISITOR, STATUS_WAIVED


def blockers(result) -> list[str]:
    return [issue["code"] for issue in result.issues if issue["severity"] == "block"]


def skip_soft_email(orchestrator, conversation_id: str, *, next_ask: str = "sizes") -> None:
    """Consume the one soft email ask so size/style tests stay focused."""
    state = orchestrator.store.get_or_create(conversation_id)
    state.flags["soft_email_asked"] = True
    state.fields["email"].attempts = max(1, state.fields["email"].attempts)
    if next_ask in state.fields and not state.fields[next_ask].done:
        state.last_question = next_ask
    orchestrator.store.save(state)


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


def test_labels_for_pizza_box_does_not_stall(orchestrator):
    # Attachment: labels ordered, box only in the purpose — lock labels, keep chatting.
    orchestrator.start("c-pizza-labels")
    first = orchestrator.handle("c-pizza-labels", "labels for my pizza box")
    assert first.handoff == ""
    assert first.accepted.get("product") == "labels"
    assert first.accepted.get("use_case") == "pizza box"
    assert "specialist" not in first.reply.lower()
    second = orchestrator.handle("c-pizza-labels", "labels for my pizza box")
    assert second.handoff == ""
    assert "specialist" not in second.reply.lower()


def test_boxes_and_labels_asks_to_confirm_instead_of_stalling(orchestrator):
    # Hybrid: conjunction names two families — suggest + confirm, no stalled handoff.
    from chatbot.bot.state import STATUS_SUGGESTED

    orchestrator.start("c-both")
    state = orchestrator.store.get_or_create("c-both")
    state.fields["product"].attempts = 2
    orchestrator.store.save(state)
    result = orchestrator.handle("c-both", "boxes and labels")
    assert result.handoff == ""
    assert "specialist" not in result.reply.lower()
    state = orchestrator.store.get_or_create("c-both")
    assert state.fields["product"].status == STATUS_SUGGESTED
    assert state.fields["product"].value == "boxes"
    lowered = result.reply.lower()
    assert "boxes" in lowered and "labels" in lowered


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
    state = orchestrator.store.get_or_create("c-pouch")
    # "2 count" is pack size / use case, not an order of two pouches.
    assert "gummy" in str(state.fields["use_case"].value)
    assert not state.fields["quantity"].done
    # Soft email is next after product + use case.
    assert "email" in result.reply.lower() or "address" in result.reply.lower()
    skip_soft_email(orchestrator, "c-pouch")
    follow = orchestrator.handle("c-pouch", "ok")
    assert "size" in follow.reply.lower()
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
    orchestrator.handle("c-unit", "mylar bags for coffee")
    skip_soft_email(orchestrator, "c-unit")
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


def test_policy_questions_are_answered_from_kb(orchestrator):
    from chatbot.bot import canon

    cases = (
        ("what about your refund policy?", "refund", ("5 business days", "support@print247.us")),
        ("any privacy policy?", "privacy", ("ssl",)),
        ("any terms and conditions?", "terms", ("3 working days", "proof")),
        ("what about your policy refund returns", "refund", ("return",)),
        ("refund?", "refund", ("5 business days", "return")),
    )
    for index, (visitor, topic, needles) in enumerate(cases):
        assert topic in canon.topics_to_answer(visitor), visitor
        cid = f"c-pol-{topic}-{index}"
        orchestrator.start(cid)
        result = orchestrator.handle(cid, visitor)
        lowered = result.reply.lower()
        assert any(n in lowered for n in needles), (visitor, result.reply)
        assert blockers(result) == []
        assert "unanswered_question" not in [issue["code"] for issue in result.issues]


def test_contact_and_address_ask_answers_both(orchestrator):
    from chatbot.bot import canon

    visitor = "your contact details and address?"
    assert "contact" in canon.topics_to_answer(visitor)
    assert "location" in canon.topics_to_answer(visitor)
    orchestrator.start("c-contact-addr")
    orchestrator.handle("c-contact-addr", "Hi")
    result = orchestrator.handle("c-contact-addr", visitor)
    lowered = result.reply.lower()
    assert "support@print247.us" in lowered
    assert "832" in result.reply
    assert "rosenberg" in lowered
    assert "our facility is in rosenberg, texas" in lowered
    assert "(location:" not in lowered
    assert result.reply.count("?") == 1
    assert blockers(result) == []
    assert "unanswered_question" not in [issue["code"] for issue in result.issues]


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
    # Soft email may be the ask after use case lands; size follows once skipped.
    if "address" in lowered or "email" in lowered:
        skip_soft_email(orchestrator, "c-food")
        result = orchestrator.handle("c-food", "ok")
        lowered = result.reply.lower()
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
    # Soft email lands right after product + use case; skip it first.
    state = orchestrator.store.get_or_create("c-style-none")
    state.flags["soft_email_asked"] = True
    state.fields["email"].attempts = max(state.fields["email"].attempts, 1)
    orchestrator.store.save(state)
    orchestrator.handle("c-style-none", "4 x 6 x 2 inches")
    orchestrator.handle("c-style-none", "1000")
    state = orchestrator.store.get_or_create("c-style-none")
    state.last_question = "style"
    orchestrator.store.save(state)
    result = orchestrator.handle("c-style-none", "i dont have")
    lowered = result.reply.lower()
    assert "mailer" in lowered and "display boxes" in lowered
    assert "material" in lowered
    assert result.accepted.get("style") == "no preference"
    assert blockers(result) == []


def test_unknown_size_is_explained_not_stored_verbatim(orchestrator):
    orchestrator.start("c-size-unknown")
    orchestrator.handle("c-size-unknown", "I need custom boxes for shipping candles")
    skip_soft_email(orchestrator, "c-size-unknown")
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


def test_let_team_decide_defers_size_without_phrase_list(orchestrator):
    """Any non-size reply to the size ask → to be confirmed (not phrase hardcoding)."""
    from chatbot.bot.state import STATUS_WAIVED, TO_BE_CONFIRMED

    orchestrator.start("c-defer-size")
    orchestrator.handle("c-defer-size", "boxes for water bottle")
    skip_soft_email(orchestrator, "c-defer-size")
    result = orchestrator.handle("c-defer-size", "let team decide it")
    state = orchestrator.store.get_or_create("c-defer-size")
    assert state.fields["sizes"].value == TO_BE_CONFIRMED
    assert state.fields["sizes"].status == STATUS_WAIVED
    assert result.accepted.get("sizes") == TO_BE_CONFIRMED
    assert "sizes" not in state.ask_set()
    assert result.handoff == ""
    # Next ask should not be size again.
    assert "what size" not in result.reply.lower() or "quantity" in result.reply.lower()


def test_coffee_beans_use_case_does_not_waive_size(orchestrator):
    orchestrator.start("c-coffee")
    orchestrator.handle("c-coffee", "bags")
    result = orchestrator.handle("c-coffee", "coffee beans")
    state = orchestrator.store.get_or_create("c-coffee")
    assert state.fields["use_case"].value == "coffee beans"
    assert not state.fields["sizes"].done
    assert state.fields["sizes"].value in {"", None} or state.fields["sizes"].status == STATUS_UNKNOWN
    # Soft email is asked on this turn; size stays open for the next ask.
    assert "address" in result.reply.lower() or "email" in result.reply.lower()
    assert state.flags.get("soft_email_asked")
    assert "sizes" in state.ask_set()


def test_give_me_options_on_style_lists_box_styles(orchestrator):
    from chatbot.bot.state import STATUS_VISITOR, STATUS_WAIVED, TO_BE_CONFIRMED

    orchestrator.start("c-style-opts")
    state = orchestrator.store.get_or_create("c-style-opts")
    state.set_field("product", "boxes", status=STATUS_VISITOR)
    state.set_field("use_case", "pizza", status=STATUS_VISITOR)
    state.set_field("sizes", TO_BE_CONFIRMED, status=STATUS_WAIVED)
    state.set_field("quantity", "1000", status=STATUS_VISITOR)
    state.flags["soft_email_asked"] = True
    state.fields["email"].attempts = 1
    state.last_question = "style"
    orchestrator.store.save(state)
    result = orchestrator.handle("c-style-opts", "give me options")
    state = orchestrator.store.get_or_create("c-style-opts")
    lowered = result.reply.lower()
    assert "mailer" in lowered or "gift" in lowered or "display" in lowered
    assert state.fields["style"].value != "give me options"
    assert not state.fields["style"].done
    assert "finish" not in lowered or "style" in lowered
    assert result.handoff == ""


def test_any_non_style_wording_lists_styles_dynamically(orchestrator):
    """No phrase hardcode: open style + non-pick wording → style menu."""
    from chatbot.bot.state import STATUS_VISITOR, STATUS_WAIVED, TO_BE_CONFIRMED

    orchestrator.start("c-style-dyn")
    state = orchestrator.store.get_or_create("c-style-dyn")
    state.set_field("product", "boxes", status=STATUS_VISITOR)
    state.set_field("use_case", "pizza", status=STATUS_VISITOR)
    state.set_field("sizes", TO_BE_CONFIRMED, status=STATUS_WAIVED)
    state.set_field("quantity", "1000", status=STATUS_VISITOR)
    state.flags["soft_email_asked"] = True
    state.fields["email"].attempts = 1
    state.last_question = "style"
    orchestrator.store.save(state)
    result = orchestrator.handle("c-style-dyn", "batao kya kya hai")
    state = orchestrator.store.get_or_create("c-style-dyn")
    lowered = result.reply.lower()
    assert "mailer" in lowered or "gift" in lowered or "kraft" in lowered or "display" in lowered
    assert state.fields["style"].value != "batao kya kya hai"
    assert not state.fields["style"].done
    assert state.flags.get("offer_options_for") == "style" or "style" in lowered


def test_not_sure_on_size_waives_even_if_live_skips_field(orchestrator):
    from chatbot.bot.state import STATUS_WAIVED, TO_BE_CONFIRMED

    orchestrator.start("c-size-ns")
    orchestrator.handle("c-size-ns", "boxes for pizza")
    skip_soft_email(orchestrator, "c-size-ns")
    result = orchestrator.handle("c-size-ns", "not sure")
    state = orchestrator.store.get_or_create("c-size-ns")
    assert state.fields["sizes"].value == TO_BE_CONFIRMED
    assert state.fields["sizes"].status == STATUS_WAIVED
    assert "sizes" not in state.ask_set()
    assert result.handoff == ""


def test_give_me_options_on_material_lists_label_stock(orchestrator):
    from chatbot.bot.state import STATUS_VISITOR, STATUS_WAIVED, TO_BE_CONFIRMED

    orchestrator.start("c-mat-opts")
    state = orchestrator.store.get_or_create("c-mat-opts")
    for key, value, status in (
        ("product", "labels", STATUS_VISITOR),
        ("use_case", "pizza box", STATUS_VISITOR),
        ("sizes", TO_BE_CONFIRMED, STATUS_WAIVED),
        ("quantity", "300", STATUS_VISITOR),
        ("finishes", TO_BE_CONFIRMED, STATUS_WAIVED),
    ):
        state.set_field(key, value, status=status)
    state.last_question = "material"
    orchestrator.store.save(state)
    result = orchestrator.handle("c-mat-opts", "give me options")
    lowered = result.reply.lower()
    assert "pp white vinyl" in lowered or "vinyl" in lowered
    assert "sku" not in lowered
    assert "email" not in lowered
    assert result.handoff == ""


def test_you_pick_defers_size_and_quantity_when_bot_asked_both(orchestrator):
    """Dual ask + 'you pick' → both shaped fields to be confirmed, not only quantity."""
    from chatbot.bot.state import STATUS_VISITOR, STATUS_WAIVED, TO_BE_CONFIRMED

    orchestrator.start("c-you-pick")
    state = orchestrator.store.get_or_create("c-you-pick")
    state.fields["product"].value = "bags"
    state.fields["product"].status = STATUS_VISITOR
    state.fields["use_case"].value = "coffee beans"
    state.fields["use_case"].status = STATUS_VISITOR
    state.last_question = "quantity"
    state.add(
        "ai",
        "For coffee beans in a stand-up pouch, what size (width x height x gusset) "
        "and quantity would you like to start with?",
    )
    orchestrator.store.save(state)
    result = orchestrator.handle("c-you-pick", "you pick")
    state = orchestrator.store.get_or_create("c-you-pick")
    assert state.fields["sizes"].value == TO_BE_CONFIRMED
    assert state.fields["sizes"].status == STATUS_WAIVED
    assert state.fields["quantity"].value == TO_BE_CONFIRMED
    assert state.fields["quantity"].status == STATUS_WAIVED
    assert result.handoff == ""
    assert "sizes" not in state.ask_set()
    assert "quantity" not in state.ask_set()


def test_bare_ok_on_size_does_not_auto_defer(orchestrator):
    from chatbot.bot.state import STATUS_WAIVED, TO_BE_CONFIRMED

    orchestrator.start("c-ok-size")
    orchestrator.handle("c-ok-size", "boxes for water bottle")
    result = orchestrator.handle("c-ok-size", "ok")
    state = orchestrator.store.get_or_create("c-ok-size")
    assert not (
        state.fields["sizes"].status == STATUS_WAIVED
        and state.fields["sizes"].value == TO_BE_CONFIRMED
    )
    assert "size" in result.reply.lower() or state.last_question == "sizes"


def test_live_model_uncertainty_sets_finish_to_be_confirmed(
    config, kb_index, tmp_path, monkeypatch
):
    """Any unsure wording: live fields write 'to be confirmed' → finish waived, next ask."""
    from dataclasses import replace

    from chatbot.bot.composer import Composed
    from chatbot.bot.orchestrator import Orchestrator as Engine
    from chatbot.bot.state import STATUS_VISITOR, STATUS_WAIVED, TO_BE_CONFIRMED

    live_config = replace(config, mode="live", allow_live=True, api_key="test-key")
    engine = Engine(
        live_config,
        store_path=tmp_path / "live-finish-tbc.sqlite3",
        index=kb_index,
        examples=[],
    )
    try:
        state = engine.store.get_or_create("c-finish-tbc")
        state.fields["product"].value = "labels"
        state.fields["product"].status = STATUS_VISITOR
        state.fields["use_case"].value = "pizza box"
        state.fields["use_case"].status = STATUS_VISITOR
        state.fields["sizes"].value = TO_BE_CONFIRMED
        state.fields["sizes"].status = STATUS_WAIVED
        state.fields["quantity"].value = "300"
        state.fields["quantity"].status = STATUS_VISITOR
        state.fields["material"].value = "PP white vinyl"
        state.fields["material"].status = STATUS_VISITOR
        state.last_question = "finishes"
        engine.store.save(state)

        monkeypatch.setattr(
            "chatbot.bot.orchestrator.live_turn",
            lambda *args, **kwargs: Composed(
                reply=(
                    "No problem — the team can confirm the finish. "
                    "How many total designs do you have?"
                ),
                asked="skus",
                fields={"finishes": TO_BE_CONFIRMED},
                source="live",
            ),
        )
        result = engine.handle("c-finish-tbc", "hmm leave the finish for later")
        state = engine.store.get_or_create("c-finish-tbc")
        assert result.handoff == ""
        assert state.fields["finishes"].value == TO_BE_CONFIRMED
        assert state.fields["finishes"].status == STATUS_WAIVED
        assert "finishes" not in state.ask_set()
        assert "gloss" not in result.reply.lower() or "skus" in result.reply.lower() or "design" in result.reply.lower()
    finally:
        engine.close()


def test_live_sku_uncertainty_does_not_lock_pp_white_vinyl(
    config, kb_index, tmp_path, monkeypatch
):
    """SKU 'not sure' must waive designs and must not settle material from catalogue."""
    from dataclasses import replace

    from chatbot.bot.composer import Composed
    from chatbot.bot.orchestrator import Orchestrator as Engine
    from chatbot.bot.state import (
        BASIS_CATALOGUE,
        STATUS_UNKNOWN,
        STATUS_VISITOR,
        STATUS_WAIVED,
        TO_BE_CONFIRMED,
    )

    live_config = replace(config, mode="live", allow_live=True, api_key="test-key")
    engine = Engine(
        live_config,
        store_path=tmp_path / "live-sku-mat.sqlite3",
        index=kb_index,
        examples=[],
    )
    try:
        state = engine.store.get_or_create("c-sku-mat")
        for key, value, status in (
            ("product", "labels", STATUS_VISITOR),
            ("use_case", "whisky bottles", STATUS_VISITOR),
            ("sizes", TO_BE_CONFIRMED, STATUS_WAIVED),
            ("quantity", "300", STATUS_VISITOR),
            ("finishes", "soft touch", STATUS_VISITOR),
        ):
            state.set_field(key, value, status=status)
        state.last_question = "skus"
        engine.store.save(state)

        monkeypatch.setattr(
            "chatbot.bot.orchestrator.live_turn",
            lambda *args, **kwargs: Composed(
                reply="Great, I can send the quote to your email. What is the best email?",
                asked="email",
                fields={
                    "skus": "no preference",
                    "material": "PP white vinyl",
                },
                source="live",
                bases={"material": BASIS_CATALOGUE},
            ),
        )
        result = engine.handle("c-sku-mat", "not sure")
        state = engine.store.get_or_create("c-sku-mat")
        assert result.handoff == ""
        assert state.fields["skus"].value == TO_BE_CONFIRMED
        assert state.fields["skus"].status == STATUS_WAIVED
        assert state.fields["material"].value != "PP white vinyl"
        assert state.fields["material"].status == STATUS_UNKNOWN
        assert "material" in state.ask_set()
    finally:
        engine.close()


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


def test_early_phone_is_acknowledged_then_product_ask(orchestrator):
    # Visitor dumps a number on turn 1 — thank them, don't ignore it.
    orchestrator.start("c-early-phone")
    result = orchestrator.handle("c-early-phone", "my phone number is +923134432915")
    assert result.accepted.get("phone") == "+923134432915"
    lowered = result.reply.lower()
    assert "got your number" in lowered or "noted" in lowered
    assert "support@print247.us" not in lowered
    assert "832" not in result.reply
    assert "box" in lowered  # still asks product
    assert result.reply.count("?") == 1
    assert blockers(result) == []


def test_quote_close_does_not_dump_the_facility_or_phone(orchestrator):
    orchestrator.start("c-quote-close")
    for text in (
        "I need custom boxes for shipping candles",
        "4 x 6 x 2 inches",
        "1000",
        "mailer box",
        "kraft",
        "matte",
        "1 design",
    ):
        step = orchestrator.handle("c-quote-close", text)
        assert blockers(step) == [], step.reply
    result = orchestrator.handle("c-quote-close", "sure. testing@mail.com is my email address")
    assert result.handoff == "quote"
    lowered = result.reply.lower()
    assert "email your quote" in lowered
    assert "rosenberg" not in lowered
    assert "832" not in result.reply
    assert "support@print247.us" not in lowered
    assert blockers(result) == []


def test_contact_inquiry_answers_then_returns_to_the_checklist(orchestrator):
    exact = "You can reach the team at Support@print247.us or +1 (832) 807-3429."
    orchestrator.start("c-contact-ask")
    for text in (
        "I need custom boxes for shipping candles",
        "4 x 6 x 2 inches",
        "1000",
    ):
        step = orchestrator.handle("c-contact-ask", text)
        assert blockers(step) == []
        assert "best email" not in step.reply.lower()
    result = orchestrator.handle("c-contact-ask", "how can I contact you?")
    assert result.handoff == ""
    assert blockers(result) == []
    assert exact in result.reply
    assert result.reply.count("?") == 1
    assert "best email" not in result.reply.lower()
    assert "best phone" not in result.reply.lower()
    state = orchestrator.store.get_or_create("c-contact-ask")
    assert "email" not in state.ask_set()
    assert state.fields["email"].value == ""


def test_soft_email_then_continue_whether_given_or_skipped(orchestrator):
    from chatbot.bot.state import SOFT_EMAIL_QUESTION, STATUS_VISITOR

    orchestrator.start("c-soft-email")
    state = orchestrator.store.get_or_create("c-soft-email")
    state.set_field("product", "boxes", status=STATUS_VISITOR)
    state.set_field("use_case", "biscuits", status=STATUS_VISITOR)
    state.last_question = "use_case"
    orchestrator.store.save(state)
    assert state.ready_for_soft_email()
    assert state.ask_set() == ["email"]
    assert state.next_question()[1] == SOFT_EMAIL_QUESTION

    soft = orchestrator.handle("c-soft-email", "later")
    state = orchestrator.store.get_or_create("c-soft-email")
    # Soft ask fired; skip without an address → size/qty continue.
    assert state.flags.get("soft_email_asked")
    assert not state.fields["email"].done
    assert state.ask_set()[0] in {"sizes", "quantity"}
    assert soft.handoff == ""

    orchestrator.start("c-soft-email-ok")
    state = orchestrator.store.get_or_create("c-soft-email-ok")
    state.set_field("product", "boxes", status=STATUS_VISITOR)
    state.set_field("use_case", "biscuits", status=STATUS_VISITOR)
    state.last_question = "use_case"
    orchestrator.store.save(state)
    got = orchestrator.handle("c-soft-email-ok", "buyer@example.com")
    state = orchestrator.store.get_or_create("c-soft-email-ok")
    assert state.fields["email"].value == "buyer@example.com"
    assert state.fields["email"].done
    assert state.flags.get("soft_email_asked")
    assert state.ask_set()[0] in {"sizes", "quantity"}
    assert got.handoff == ""


def test_soft_email_no_continues_quote_not_handoff(orchestrator):
    """Bare 'no' on the soft early email ask must keep size/qty flowing."""
    from chatbot.bot.state import STATUS_VISITOR

    orchestrator.start("c-soft-no")
    state = orchestrator.store.get_or_create("c-soft-no")
    state.set_field("product", "boxes", status=STATUS_VISITOR)
    state.set_field("use_case", "for biscuits", status=STATUS_VISITOR)
    state.last_question = "use_case"
    orchestrator.store.save(state)
    # Fire the soft email ask.
    ask = orchestrator.handle("c-soft-no", "ok")
    state = orchestrator.store.get_or_create("c-soft-no")
    assert state.last_question == "email" or "email" in ask.reply.lower()
    state.last_question = "email"
    state.flags["soft_email_asked"] = True
    orchestrator.store.save(state)

    result = orchestrator.handle("c-soft-no", "no")
    state = orchestrator.store.get_or_create("c-soft-no")
    assert result.handoff == "", result.reply
    assert state.fields["email"].value != "declined"
    assert state.fields["phone"].value != "declined"
    assert state.ask_set()[0] in {"sizes", "quantity"}
    assert "specialist" not in result.reply.lower()
    assert "?" in result.reply


def test_you_pick_on_finish_waives_to_be_confirmed(orchestrator):
    from chatbot.bot.state import STATUS_VISITOR, STATUS_WAIVED, TO_BE_CONFIRMED

    orchestrator.start("c-finish-pick")
    state = orchestrator.store.get_or_create("c-finish-pick")
    for key, value, status in (
        ("product", "boxes", STATUS_VISITOR),
        ("use_case", "biscuits", STATUS_VISITOR),
        ("sizes", TO_BE_CONFIRMED, STATUS_WAIVED),
        ("quantity", "1000", STATUS_VISITOR),
        ("style", "no preference", STATUS_WAIVED),
        ("skus", "1", STATUS_VISITOR),
        ("material", "kraft", STATUS_VISITOR),
    ):
        state.set_field(key, value, status=status)
    state.last_question = "finishes"
    orchestrator.store.save(state)
    result = orchestrator.handle("c-finish-pick", "you pick")
    state = orchestrator.store.get_or_create("c-finish-pick")
    assert state.fields["finishes"].value == TO_BE_CONFIRMED
    assert state.fields["finishes"].status == STATUS_WAIVED
    assert "finishes" not in state.ask_set()
    assert result.handoff == ""


def test_invalid_email_tells_visitor_and_keeps_asking(orchestrator):
    from chatbot.bot.state import INVALID_EMAIL_REPLY, STATUS_VISITOR, STATUS_WAIVED, TO_BE_CONFIRMED

    orchestrator.start("c-bad-email")
    state = orchestrator.store.get_or_create("c-bad-email")
    for key, value, status in (
        ("product", "labels", STATUS_VISITOR),
        ("use_case", "coffee beans", STATUS_VISITOR),
        ("sizes", TO_BE_CONFIRMED, STATUS_WAIVED),
        ("quantity", "800", STATUS_VISITOR),
        ("finishes", "soft touch", STATUS_VISITOR),
        ("skus", TO_BE_CONFIRMED, STATUS_WAIVED),
        ("material", "no preference", STATUS_WAIVED),
    ):
        state.set_field(key, value, status=status)
    state.last_question = "email"
    orchestrator.store.save(state)

    for bad in ("buyer@gmail", "bilal@com", "notanemail@"):
        result = orchestrator.handle("c-bad-email", bad)
        state = orchestrator.store.get_or_create("c-bad-email")
        assert result.handoff == ""
        lowered = result.reply.lower()
        assert (
            "doesn't look right" in lowered
            or "valid email" in lowered
            or "name@company.com" in lowered
        ), result.reply
        assert state.fields["email"].value == ""
        assert not state.fields["email"].done
        assert state.last_question == "email"
        assert "email" in state.ask_set()

    ok = orchestrator.handle("c-bad-email", "buyer@example.com")
    state = orchestrator.store.get_or_create("c-bad-email")
    assert state.fields["email"].value == "buyer@example.com"
    assert state.fields["email"].done
    assert "doesn't look right" not in ok.reply.lower()


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


def test_refuse_email_but_ask_our_contact_and_address(orchestrator):
    from chatbot.bot import canon
    from chatbot.bot.state import refuses_contact

    visitor = (
        "i do not want to share email. please share your contact details with your address"
    )
    assert refuses_contact(visitor)
    assert canon.asks_for_our_contact(visitor)
    assert canon.asks_for_location(visitor)
    assert "contact" in canon.topics_to_answer(visitor)
    assert "location" in canon.topics_to_answer(visitor)

    orchestrator.start("c-refuse-ask-ours")
    for text in [
        "i need boxes for shipping candles",
        "4 x 6 x 2 inches",
        "1000",
        "mailer box",
        "kraft",
        "matte",
        "3 designs",
    ]:
        orchestrator.handle("c-refuse-ask-ours", text)
    result = orchestrator.handle("c-refuse-ask-ours", visitor)
    lowered = result.reply.lower()
    assert result.handoff in {"", "quote"}
    assert "specialist" not in lowered
    assert "support@print247.us" in lowered
    assert "832" in result.reply
    assert "rosenberg" in lowered
    # Do not promise to email them after they refused to share an email.
    if result.handoff == "quote":
        assert "email your quote" not in lowered


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


def test_feet_alone_keeps_asking_for_banner_dimensions(orchestrator):
    orchestrator.start("c-feet")
    orchestrator.handle("c-feet", "I need banners for an outdoor event")
    # Drive to the size question if the opener did not already ask it.
    state = orchestrator.store.get_or_create("c-feet")
    if state.last_question != "sizes":
        orchestrator.handle("c-feet", "outdoor")
    result = orchestrator.handle("c-feet", "feet")
    state = orchestrator.store.get_or_create("c-feet")
    assert state.flags.get("size_preferred_unit") == "ft"
    assert not state.fields["sizes"].value
    assert not result.handoff
    assert "specialist" not in result.reply.lower()
    lowered = result.reply.lower()
    assert "size" in lowered or "3x6" in lowered or "feet" in lowered


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


def test_suggest_me_the_styles_lists_box_catalogue(orchestrator):
    from chatbot.bot.state import is_option_request, wants_recommendation
    from chatbot.bot import canon

    visitor = "suggest me the styles"
    assert wants_recommendation(visitor)
    assert is_option_request(visitor)
    assert "styles" in canon.topics_to_answer(visitor)

    _ready_for_style(orchestrator, "c-suggest-styles")
    result = orchestrator.handle("c-suggest-styles", visitor)
    lowered = result.reply.lower()
    assert "mailer" in lowered and "display" in lowered and "gift" in lowered
    assert "drip" not in lowered
    assert result.reply.count("?") == 1
    assert blockers(result) == []


def test_box_finish_options_stay_on_official_list(orchestrator):
    from chatbot.bot.composer import BOX_PRIMARY_FINISHES_TEXT, heuristic_turn

    orchestrator.start("c-box-finishes")
    state = orchestrator.store.get_or_create("c-box-finishes")
    for key, value in (
        ("product", "boxes"),
        ("use_case", "candles"),
        ("sizes", "4x6 in"),
        ("quantity", "1000"),
        ("style", "mailer"),
    ):
        state.set_field(key, value, raw=value, status=STATUS_VISITOR)
    state.last_question = "finishes"
    visitor = "suggest me the finishes"
    state.add("visitor", visitor)
    orchestrator.store.save(state)

    expected = state.next_question()
    reply = heuristic_turn(state, visitor, expected).reply.lower()
    assert "matte lamination" in reply
    assert "gloss lamination" in reply
    assert "soft touch lamination" in reply
    assert "spot uv" in reply
    assert "foil printing" in reply
    assert "drip" not in reply
    assert BOX_PRIMARY_FINISHES_TEXT.split(",")[0].lower() in reply


def test_suggest_other_materials_lists_options_not_finish(orchestrator):
    """After a kraft proposal, 'suggest me other materials' must list materials."""
    from chatbot.bot.state import STATUS_SUGGESTED, STATUS_VISITOR, STATUS_WAIVED

    orchestrator.start("c-other-mat")
    state = orchestrator.store.get_or_create("c-other-mat")
    for key, value, status in (
        ("product", "boxes", STATUS_VISITOR),
        ("use_case", "for pizza", STATUS_VISITOR),
        ("sizes", "to be confirmed", STATUS_WAIVED),
        ("quantity", "500", STATUS_VISITOR),
        ("style", "no preference", STATUS_WAIVED),
    ):
        state.set_field(key, value, raw=value, status=status)
    state.set_field("material", "kraft", status=STATUS_SUGGESTED)
    state.flags["soft_email_asked"] = True
    state.last_question = "material"
    orchestrator.store.save(state)

    result = orchestrator.handle("c-other-mat", "suggest me other materials")
    state = orchestrator.store.get_or_create("c-other-mat")
    lowered = result.reply.lower()
    assert result.handoff == ""
    assert state.fields["material"].status != STATUS_WAIVED
    assert state.fields["material"].value != "no preference"
    assert "material" in state.ask_set() or state.last_question == "material"
    assert "finish" not in lowered or "material" in lowered
    assert any(
        token in lowered
        for token in ("kraft", "board", "cardboard", "corrugated", "material")
    ), result.reply
    assert "matte lamination" not in lowered


def test_suggest_me_materials_for_mailer_lists_box_boards(orchestrator):
    """Vision asked material → visitor asks for suggestions → list boards, not finish."""
    from chatbot.bot.state import STATUS_VISITOR

    orchestrator.start("c-mailer-mat")
    state = orchestrator.store.get_or_create("c-mailer-mat")
    for key, value in (
        ("product", "boxes"),
        ("use_case", "pizza"),
        ("sizes", "15x20 in"),
        ("quantity", "300"),
        ("style", "mailer"),
    ):
        state.set_field(key, value, raw=value, status=STATUS_VISITOR)
    state.flags["soft_email_asked"] = True
    state.last_question = "material"
    state.fields["material"].attempts = 1
    orchestrator.store.save(state)

    first = orchestrator.handle("c-mailer-mat", "suggest me materials for this")
    lowered = first.reply.lower()
    assert "matte lamination" not in lowered
    assert any(
        token in lowered for token in ("kraft", "corrugated", "sbs", "chipboard", "board")
    ), first.reply
    state = orchestrator.store.get_or_create("c-mailer-mat")
    assert state.last_question == "material"
    assert state.fields["material"].attempts <= 1

    second = orchestrator.handle("c-mailer-mat", "suggest me")
    lowered2 = second.reply.lower()
    assert "matte lamination" not in lowered2
    assert any(
        token in lowered2 for token in ("kraft", "corrugated", "sbs", "chipboard", "board")
    ), second.reply
    assert state.fields["material"].attempts <= 1 or (
        orchestrator.store.get_or_create("c-mailer-mat").last_question == "material"
    )


def test_yes_confirms_label_material_proposal(orchestrator):
    # Propose-and-confirm: "yes" after the standard-stock ask must settle material,
    # not send live back into "what other materials".
    from chatbot.bot.state import STATUS_CONFIRMED, STATUS_SUGGESTED, STATUS_VISITOR, STATUS_WAIVED

    orchestrator.start("c-label-yes")
    state = orchestrator.store.get_or_create("c-label-yes")
    for key, value, status in (
        ("product", "labels", STATUS_VISITOR),
        ("use_case", "for coffee", STATUS_VISITOR),
        ("sizes", "to be confirmed", STATUS_WAIVED),
        ("quantity", "350", STATUS_VISITOR),
        ("finishes", "matte", STATUS_VISITOR),
    ):
        state.set_field(key, value, raw=value, status=status)
    state.fields["email"].value = "bilal@gmail.com"
    state.fields["email"].status = STATUS_VISITOR
    state.flags["soft_email_asked"] = True
    state.last_question = "material"
    orchestrator.store.save(state)

    propose = orchestrator.handle(
        "c-label-yes", "suggest me other label materials you have."
    )
    state = orchestrator.store.get_or_create("c-label-yes")
    assert "vinyl" in propose.reply.lower()
    assert state.fields["material"].status == STATUS_SUGGESTED
    assert "vinyl" in state.fields["material"].value.lower()
    assert state.last_question == "material"

    yes = orchestrator.handle("c-label-yes", "yes")
    state = orchestrator.store.get_or_create("c-label-yes")
    assert state.fields["material"].status == STATUS_CONFIRMED
    assert "vinyl" in state.fields["material"].value.lower()
    lowered = yes.reply.lower()
    assert "got it" in lowered
    assert "beyond the pp white vinyl" not in lowered
    assert "other option from our materials" not in lowered
    assert blockers(yes) == []


def test_label_material_fallback_stays_inside_labels(orchestrator):
    from chatbot.bot.composer import heuristic_turn
    from chatbot.bot.guards import asked_field

    material_ask = (
        "Got it. To finalize the label build for the honey jars, what material would "
        "you like us to use besides the finish you chose (soft touch) and the "
        "standard oval size with 200 units and 2 SKUs?"
    )
    assert asked_field(material_ask) == "material"

    orchestrator.start("c-label-mat")
    state = orchestrator.store.get_or_create("c-label-mat")
    for key, value, status in (
        ("product", "labels", STATUS_VISITOR),
        ("use_case", "honey jars", STATUS_VISITOR),
        ("sizes", "to be confirmed", STATUS_WAIVED),
        ("quantity", "200", STATUS_VISITOR),
        ("finishes", "soft touch", STATUS_VISITOR),
        ("skus", "2", STATUS_VISITOR),
    ):
        state.set_field(key, value, raw=value, status=status)
    state.last_question = "material"
    visitor = "suggest me materials then i will select one"
    state.add("visitor", visitor)
    orchestrator.store.save(state)

    expected = state.next_question()
    reply = heuristic_turn(state, visitor, expected).reply.lower()
    assert "vinyl" in reply
    assert "stand-up" not in reply
    assert "mailer" not in reply
    assert "flat-bottom" not in reply
    assert "kraft boxes" not in reply

    fallback = orchestrator._safe_fallback(state, expected, "").lower()
    assert "vinyl" in fallback
    assert "stand-up" not in fallback
    assert "mailer" not in fallback
    assert "bag styles" not in fallback
    assert "box styles" not in fallback


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
    assert state.fields["sizes"].value not in {"0x15", "0x15 in", "0"}
    assert "size_pending_unit" not in state.flags
    assert blockers(result) == []
    orchestrator.handle("c-zero", "10x0x5")
    state = orchestrator.store.get_or_create("c-zero")
    # Zero dims are never kept as the size; after two failed asks the field may
    # be waived as "to be confirmed" for the team, which is not a stored zero.
    assert state.fields["sizes"].value not in {"10x0x5", "10x0x5 in", "0x15", "0"}
    if state.fields["sizes"].value:
        assert state.fields["sizes"].status == STATUS_WAIVED


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
        ("skus", "How many total designs do you have?"),
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
