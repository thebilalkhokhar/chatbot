"""Catalogue fuzzy (rapidfuzz) + English spell (pyspellchecker) helpers."""

from chatbot.bot.spelling import (
    correct_english_spelling,
    fuzzy_catalogue_match,
    prepare_visitor_text,
)
from chatbot.bot.state import ConversationState, apply_field_updates, extract_fields


def test_mate_fuzzy_matches_matte_finish():
    assert fuzzy_catalogue_match("mate", "finishes") == "matte"


def test_glos_fuzzy_matches_gloss_finish():
    assert fuzzy_catalogue_match("glos", "finishes") == "gloss"


def test_metalized_does_not_fuzzy_to_style():
    assert fuzzy_catalogue_match("metalized", "style", family="boxes") == ""


def test_mail_box_fuzzy_matches_mailer_style():
    assert fuzzy_catalogue_match("mail box", "style", family="boxes") == "mailer"
    assert fuzzy_catalogue_match("mailr", "style", family="boxes") == "mailer"


def test_extract_mail_box_settles_mailer_style():
    state = ConversationState(id="spell-mail-box", persona="Alex Kane")
    state.set_field("product", "boxes", status="visitor")
    state.last_question = "style"
    updates = extract_fields("mail box", "style", state)
    assert updates.get("style")
    apply_field_updates(state, updates, "mail box")
    assert state.fields["style"].value == "mailer"
    assert state.fields["style"].done


def test_adress_english_corrects_to_address():
    from pathlib import Path

    from chatbot.bot.capability import Registry
    from chatbot.bot.spelling import protect_terms

    assert correct_english_spelling("adress") == "address"
    assert correct_english_spelling("shipping adress please") == "shipping address please"
    # Registry token "address" (Address Labels) must not block the typo fix.
    protected = protect_terms("labels", Registry.load(Path("kb")))
    assert "address" in protected
    assert correct_english_spelling("your adress?", protect=protected) == "your address?"
    cleaned, _ = prepare_visitor_text("your adress?", "product", family="", registry=Registry.load(Path("kb")))
    assert "address" in cleaned


def test_dont_know_is_not_rewritten_to_donut():
    assert correct_english_spelling("i dont know") == "i dont know"
    text, hit = prepare_visitor_text("i dont know", "use_case")
    assert text == "i dont know"
    assert hit == ""


def test_prepare_visitor_text_catalogue_vs_english():
    text, hit = prepare_visitor_text("mate", "finishes", family="bags")
    assert hit == "matte"
    assert text == "mate"
    cleaned, empty = prepare_visitor_text("my adress is ready", "use_case")
    assert empty == ""
    assert "address" in cleaned


def test_extract_mate_settles_finish_via_fuzzy():
    state = ConversationState(id="spell-mate", persona="Alex Kane")
    state.last_question = "finishes"
    updates = extract_fields("mate", "finishes", state)
    assert updates.get("finishes") == "matte"
    apply_field_updates(state, updates, "mate")
    assert state.fields["finishes"].value == "matte"


def test_extract_adress_in_use_case_is_corrected():
    state = ConversationState(id="spell-adress", persona="Alex Kane")
    state.last_question = "use_case"
    updates = extract_fields("shipping adress labels", "use_case", state)
    assert "address" in updates.get("use_case", "").lower()


def test_adress_while_quantity_open_is_location_not_qty():
    from chatbot.bot import canon

    cleaned, hit = prepare_visitor_text("can you give me your adress", "quantity")
    assert hit == ""
    assert "address" in cleaned
    assert "location" in canon.topics_to_answer(cleaned)
    state = ConversationState(id="spell-qty-adress", persona="Alex Kane")
    state.last_question = "quantity"
    updates = extract_fields("can you give me your adress", "quantity", state)
    assert "quantity" not in updates
