from __future__ import annotations

from chatbot.bot import canon, guards, pii
from chatbot.bot.personas import PERSONAS, validate_personas
from chatbot.bot.state import ConversationState, STATUS_VISITOR, STATUS_WAIVED


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
    assert stats["verified_chunks"] >= 60
    hits = kb_index.search("minimum order quantity", top_k=4)
    assert hits
    assert any("moq" in hit.chunk.doc_id.lower() for hit in hits)


def test_draft_content_never_reaches_an_answer(kb_index):
    # the v2 capability files are deliberately draft; v1 must still read verified facts only
    drafts = [chunk for chunk in kb_index.chunks if chunk.status != "verified"]
    assert drafts, "the capability registry should still be indexed as draft"
    # SIGNOFF_PACKET is paperwork for sales and production, not corpus — like the
    # two files it describes, it must never be retrievable into a reply.
    assert {chunk.doc_id for chunk in drafts} <= {
        "capability-registry",
        "compliance-allowlist",
        "SIGNOFF_PACKET",
    }
    assert all(chunk.category == "capabilities" for chunk in drafts)
    for query in ("minimum order quantity", "mylar bag sizes", "child resistant zipper"):
        assert all(hit.chunk.status == "verified" for hit in kb_index.search(query, top_k=10))


def test_a_quantity_is_not_a_minimum_question():
    assert canon.asks_for_minimum("300") is False
    assert canon.asks_for_minimum("I need 300 boxes") is False
    assert canon.asks_for_minimum("Your minimum is too high. I only need 100.") is False
    assert canon.asks_for_minimum("500 is fine if the minimum is lower than 1000.") is False
    assert canon.asks_for_minimum("What is your minimum?") is True
    assert canon.asks_for_minimum("Do you have a minimum") is True
    assert canon.asks_for_minimum("What is your MOQ and what is the lead time?") is True
    assert canon.asks_for_minimum("Is there a minimum on banners?") is True
    assert canon.asks_for_minimum("Please share your minimum order quantity and the lead time.") is True


def test_a_bare_quantity_loses_the_injected_moq_sentence():
    reply = (
        "Got it, 300 works. Our standard MOQ is 1,000 per size "
        "(500 each if you have multiple designs), but we do smaller runs too, "
        "so just tell me the quantity you need. What size do you need? And how many designs?"
    )
    cleaned = guards.prepare_reply(reply, "300", priority_key="sizes")
    lowered = cleaned.lower()
    assert "1,000" not in cleaned
    assert "moq" not in lowered
    assert "minimum" not in lowered
    assert "smaller runs" not in lowered
    assert cleaned.count("?") == 1
    assert "size" in lowered
    assert "design" not in lowered
    assert guards.count_questions(cleaned) == 1


def test_an_explicit_minimum_question_keeps_the_moq_sentence():
    reply = (
        "Our standard MOQ is 1,000 per size (500 each if you have multiple designs), "
        "but we do smaller runs too, so just tell me the quantity you need. "
        "What size do you need? Which style do you want?"
    )
    cleaned = guards.prepare_reply(reply, "What is your minimum?", priority_key="sizes")
    assert "1,000" in cleaned
    assert "smaller runs" in cleaned.lower()
    assert cleaned.count("?") == 1
    assert "size" in cleaned.lower()
    assert "style" not in cleaned.lower()


def test_a_contact_question_keeps_the_canon_line_and_the_next_field():
    exact = "You can reach the team at Support@print247.us or +1 (832) 807-3429."
    sku = "How many total designs do you have?"
    cleaned = guards.prepare_reply(
        "Sure, just email us whenever. What is the best email to send the quote to?",
        "what is your phone number?",
        priority_key="skus",
        priority_text=sku,
    )
    assert exact in cleaned
    assert sku in cleaned
    assert cleaned.count("?") == 1
    assert "best email" not in cleaned.lower()
    assert canon.asks_for_our_contact("what is your phone number?")
    assert canon.asks_for_our_contact("how can I contact you?")
    assert not canon.asks_for_our_contact("my email is buyer@example.com")
    assert not canon.asks_for_our_contact("I don't have an email")
    assert not canon.asks_for_our_contact("my phone number is +923134432915")
    assert "contact" not in canon.topics_to_answer("my phone number is +923134432915")


def test_giving_own_phone_does_not_dump_company_contact():
    product = "What product would you like us to make for you today—boxes, bags, or labels?"
    visitor = "my phone number is +923134432915"
    dumped = (
        "You can reach the team at Support@print247.us or +1 (832) 807-3429. " + product
    )
    cleaned = guards.prepare_reply(
        dumped, visitor, priority_key="product", priority_text=product
    )
    assert "Support@print247.us" not in cleaned
    assert "832" not in cleaned
    assert product in cleaned


def test_policy_ask_without_written_answer_is_injected():
    product = "Which product are you looking to have made: boxes, bags, labels or something else?"
    for visitor, needle in (
        ("what about your refund policy?", "5 business days"),
        ("refund?", "5 business days"),
        ("any privacy policy?", "ssl"),
        ("any terms and conditions?", "3 working days"),
    ):
        cleaned = guards.prepare_reply(product, visitor, priority_key="product", priority_text=product)
        assert needle in cleaned.lower(), visitor
        assert product in cleaned
        assert cleaned.count("?") == 1
        assert "unanswered_question" not in guards.check_reply(
            cleaned, make_state(visitor), visitor_text=visitor
        ).codes()


def test_contact_and_address_ask_gets_both_written_lines():
    contact = "You can reach the team at Support@print247.us or +1 (832) 807-3429."
    location = "Our facility is in Rosenberg, Texas."
    product = "What product would you like us to make today: boxes, bags, or labels?"
    visitor = "your contact details and address?"
    mangled = (
        f"{contact} Sure thing. {product} (location: Rosenberg, TX)"
    )
    cleaned = guards.prepare_reply(
        mangled,
        visitor,
        priority_key="product",
        priority_text=product,
    )
    assert contact in cleaned
    assert location in cleaned
    assert "(location:" not in cleaned.lower()
    assert cleaned.index(contact) < cleaned.index(location)
    assert cleaned.count("?") == 1
    assert "unanswered_question" not in guards.check_reply(
        cleaned, make_state(visitor), visitor_text=visitor
    ).codes()


def test_an_early_email_ask_is_replaced_with_the_open_field():
    material = "Do you have any specific material or special features in mind?"
    cleaned = guards.prepare_reply(
        "Got it. What is the best email to send the quote to?",
        "kraft is fine",
        priority_key="material",
        priority_text=material,
    )
    assert material in cleaned
    assert "best email" not in cleaned.lower()
    assert cleaned.count("?") == 1


def test_three_questions_collapse_to_the_priority_field():
    reply = "Is that in inches, cm, or mm? How many units do you need? Which style do you want?"
    cleaned = guards.prepare_reply(reply, "8x8", priority_key="sizes", priority_text="Is 8x8 in inches, cm, or mm?")
    assert cleaned.count("?") == 1
    assert "inches" in cleaned.lower()
    assert "how many" not in cleaned.lower()
    assert "style" not in cleaned.lower()


def test_a_repeated_morning_is_removed_and_a_real_sentence_stays():
    repeated = guards.prepare_reply(
        "Morning! What size do you need? How many units?",
        "8x8",
        priority_key="sizes",
        already_greeted=True,
    )
    assert "morning" not in repeated.lower()
    assert repeated.count("?") == 1
    assert "size" in repeated.lower()
    kept = guards.strip_repeated_greeting("Morning production runs with the quote. What size do you need?")
    assert kept.lower().startswith("morning production")
    first = guards.prepare_reply("Good morning. What are you looking to have made?", "hi", already_greeted=False)
    assert first.lower().startswith("good morning")


def test_multiple_questions_blocked():
    state = make_state("I need boxes")
    result = guards.check_reply(
        "What size do you need, and how many units?", state, visitor_text="I need boxes"
    )
    assert "multiple_questions" in result.codes()


def test_compound_size_and_quantity_collapsed_to_one_field():
    draft = (
        "For coffee beans in a stand-up pouch, what size (width x height x gusset) "
        "and quantity would you like to start with?"
    )
    assert guards.all_asked_fields(draft) == ["sizes", "quantity"]
    polished = guards.prepare_reply(
        draft,
        "coffee beans",
        priority_key="sizes",
        priority_text="What bag size are you looking for?",
    )
    assert guards.all_asked_fields(polished) == ["sizes"]
    assert "quantity" not in polished.lower()
    assert "?" in polished
    result = guards.check_reply(draft, make_state("bags"), visitor_text="coffee beans")
    assert "compound_ask" in result.codes()


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


def test_a_contact_refusal_is_not_a_question_about_ours():
    assert "contact" not in canon.detect_topics("I don't have an email")
    assert "contact" not in canon.detect_topics("i dont have any email")
    assert "contact" not in canon.detect_topics("i don't want to share")
    assert "contact" in canon.detect_topics("what is your email?")
    state = make_state("I don't have an email")
    result = guards.check_reply("What size do you need?", state, visitor_text="I don't have an email")
    assert "unanswered_question" not in result.codes()
    note = guards.describe(
        [guards.Issue("reply_config_mismatch", guards.BLOCK, "The configuration names kraft, and the reply never does.", "kraft")]
    )
    assert "Do NOT re-assert or re-emit proposed_configs" in note


def test_alternative_material_ask_blocks_without_forcing_written_injection():
    text = "suggest me materials other than PP white vinyl"
    state = make_state("I need custom labels for honey jars", text)
    state.fields["product"].value = "labels"
    state.fields["product"].status = "visitor"
    blocked = guards.check_reply(
        "Where should the quote go — which email works best?",
        state,
        visitor_text=text,
    )
    assert "unanswered_question" in blocked.codes()
    detail = " ".join(issue.detail for issue in blocked.issues if issue.code == "unanswered_question")
    assert "Use the written answer:" not in detail
    assert "standard material" in detail.lower()
    assert "email" in detail.lower()

    good = guards.check_reply(
        "For honey jar labels we use PP white vinyl as our standard high-grade stock "
        "for best results. Would you like to proceed with that?",
        state,
        visitor_text=text,
    )
    assert "unanswered_question" not in good.codes()


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
    state.set_field("sizes", "4 x 6 inches", raw="4 x 6 inches", status=STATUS_VISITOR)
    state.add("ai", "What size are you looking for?")
    result = guards.check_reply("What size are you looking for?", state)
    assert "repeated_message" in result.codes() or "question_already_answered" in result.codes()


def test_a_size_without_its_unit_is_still_open():
    # Section 4.4: the unit question is a live ask, not a re-ask of an answer.
    state = make_state("100 x 150")
    state.set_field("sizes", "100x150", raw="100 x 150", status=STATUS_VISITOR)
    assert state.fields["sizes"].done
    assert not guards.settled_for_asking(state, "sizes")
    state.flags["unit_asked"] = True
    assert state.finalize_stalled() == ["sizes"]
    assert state.fields["sizes"].status == STATUS_WAIVED
    assert state.size_needs_unit() is False


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


def test_unicode_apostrophe_still_counts_as_an_ai_claim():
    # The live draft got through because I’m uses U+2019 and the pattern wanted i'm.
    state = make_state("hello")
    volunteered = guards.check_reply("I\u2019m an AI assistant.", state, visitor_text="hello")
    assert "bot_self_claim" in volunteered.codes()
    assert not volunteered.ok
    honest = guards.check_reply(
        "I\u2019m an AI assistant working under the name Ethan for Print247.",
        state,
        visitor_text="you said you are ethan now you called ai",
        asked_if_bot=True,
    )
    assert "bot_self_claim" not in honest.codes()
    denial = guards.check_reply(
        "I\u2019m not an AI.",
        state,
        visitor_text="are you a bot?",
        asked_if_bot=True,
    )
    assert "bot_self_claim" in denial.codes()
    assert not denial.ok


def test_redundant_ask_blocks_a_field_they_already_stated():
    state = make_state("kraft")
    state.set_field("style", "kraft", raw="kraft", status=STATUS_VISITOR)
    result = guards.check_reply("What style of box do you need?", state)
    assert "redundant_ask" in result.codes()
    assert not result.ok
    detail = next(issue.detail for issue in result.issues if issue.code == "redundant_ask")
    assert "style" in detail and "kraft" in detail
    # The v1 guard stays active alongside the new one.
    assert "question_already_answered" in result.codes()


def test_use_case_question_is_not_misread_as_material():
    reply = (
        "What use case is this label for (e.g., product label, promo label, "
        "barcode/warnings) so I can tailor the right finish and material?"
    )
    assert guards.asked_field(reply) == "use_case"
    state = make_state("15*20")
    state.set_field("product", "labels", raw="labels", status=STATUS_VISITOR)
    state.set_field("use_case", "whisky bottle", raw="whisky bottle", status=STATUS_VISITOR)
    state.set_field("sizes", "15x20", raw="15*20", status=STATUS_VISITOR)
    result = guards.check_reply(reply, state, visitor_text="15*20")
    assert "redundant_ask" in result.codes()
    assert not result.ok
    redirected = guards.prepare_reply(
        reply,
        "15*20",
        priority_key="sizes",
        priority_text="Is 15x20 in inches, cm, or mm?",
        locked_fields=("product", "use_case"),
    )
    assert "use case" not in redirected.lower()
    assert "inches" in redirected.lower()


def test_a_size_missing_its_unit_is_not_a_redundant_ask():
    state = make_state("100 x 150")
    state.set_field("sizes", "100x150", raw="100 x 150", status=STATUS_VISITOR)
    result = guards.check_reply("What size are you looking for?", state)
    assert "redundant_ask" not in result.codes()


def test_outgoing_replies_never_say_sku_to_the_visitor():
    cleaned = guards.scrub_visitor_sku_jargon(
        "I couldn't clearly make out how many designs from this image. "
        "How many total designs or SKUs do you have?"
    )
    assert "sku" not in cleaned.lower()
    assert "designs" in cleaned.lower()
    prepared = guards.prepare_reply(
        "How many total designs or SKUs do you have?",
        "1",
        priority_key="skus",
        priority_text="How many total designs do you have?",
    )
    assert "sku" not in prepared.lower()


def test_your_address_is_a_question_and_not_a_style():
    assert guards.question_as_answer("your address", "style")
    assert guards.question_as_answer("what style should I pick?", "style")
    assert not guards.question_as_answer("a mailer box", "style")
    state = make_state("your address")
    state.last_question = "style"
    from chatbot.bot.state import apply_field_updates, extract_fields

    updates = extract_fields("your address", "style", state)
    accepted, rejected = apply_field_updates(state, updates, "your address")
    assert accepted.get("style") is None
    assert state.fields["style"].value == ""
    # Non-catalogue wording is not stored as style (options / re-ask path).
    assert updates.get("style") in (None, "") or rejected.get("style") == "your address"


def test_wrong_minimum_figures_use_canon():
    state = make_state("I need 500 bags with 3 designs")
    state.add("visitor", "bags")
    state.set_field("product", "bags")
    reply = canon.effective_answer("moq")
    result = guards.check_reply(reply, state, visitor_text="I need 500 bags with 3 designs")
    assert "wrong_minimum" not in result.codes()


def test_pii_masking():
    text = "email me at buyer@example.com or 415-555-0199"
    masked = pii.mask(text)
    assert "buyer@example.com" not in masked
    assert "415-555-0199" not in masked
    assert "[EMAIL]" in masked and "[PHONE]" in masked
    public = pii.mask(
        "You can reach the team at Support@print247.us or +1 (832) 807-3429. "
        "Visitor note: buyer@example.com"
    )
    assert "Support@print247.us" in public
    assert "+1 (832) 807-3429" in public
    assert "buyer@example.com" not in public


def test_placeholder_contact_is_replaced_with_the_canon_line():
    cleaned = guards.prepare_reply(
        "You can reach the team at [EMAIL] or [PHONE]. "
        "Could you please share your email address so we can send the quote?",
        "i have 2 SKUs",
        priority_key="email",
        priority_text="What is the best email to send the quote to?",
    )
    assert "Support@print247.us" in cleaned
    assert "+1 (832) 807-3429" in cleaned
    assert "[EMAIL]" not in cleaned
    assert "[PHONE]" not in cleaned
    assert cleaned.count("?") == 1


def test_to_finish_is_not_a_second_finish_question():
    state = make_state("spot gloss")
    state.set_field("finishes", "gloss", raw="spot gloss", status=STATUS_VISITOR)
    reply = "To finish the box build, can you provide the SKUs or design references you want us to quote against?"
    result = guards.check_reply(reply, state, visitor_text="spot gloss")
    assert "redundant_ask" not in result.codes()
    assert guards.asked_field(reply) == "skus"
