from __future__ import annotations

from pathlib import Path

from chatbot.bot.capability import Registry
from chatbot.bot.composer import heuristic_turn
from chatbot.bot.guards import check_reply
from chatbot.bot.orchestrator import Orchestrator
from chatbot.bot.reply_language import language_named_in_preference_ask
from chatbot.bot.state import (
    ConversationState,
    UNSPECIFIED_RE,
    apply_field_updates,
    asks_language_preference,
    extract_fields,
    needs_catalogue_options,
    size_has_unit,
    wants_recommendation,
)

KB_DIR = Path(__file__).resolve().parents[1] / "kb"


def test_language_preference_heuristic_says_yes(orchestrator: Orchestrator):
    orchestrator.start("c-lang")
    state = orchestrator.store.get_or_create("c-lang")
    composed = heuristic_turn(
        state,
        "Do you speak Spanish?",
        ("product", state.question_for("product")),
    )
    lowered = composed.reply.lower()
    assert "yes" in lowered
    assert "language" in lowered or "español" in lowered or "spanish" in lowered or "continue" in lowered
    assert "?" in composed.reply


def test_language_preference_fallback_not_fair_question(orchestrator: Orchestrator):
    orchestrator.start("c-lang2")
    state = orchestrator.store.get_or_create("c-lang2")
    state.add("visitor", "Do you speak Spanish?")
    orchestrator.store.save(state)
    state = orchestrator.store.get_or_create("c-lang2")
    reply = orchestrator._safe_fallback(
        state,
        ("product", state.question_for("product")),
        "",
    )
    assert "fair question" not in reply.lower()
    assert "yes" in reply.lower()
    assert "continue" in reply.lower() or "language" in reply.lower()


def test_language_preference_yes_reply_passes_guards():
    state = ConversationState(id="lang-g", persona="Alex Kane")
    expected = ("product", state.question_for("product"))
    reply = (
        "Yes — I can continue in your language. "
        "I'll keep the questions focused on what the quote needs. "
        + expected[1]
    )
    result = check_reply(
        reply,
        state,
        visitor_text="Do you speak Spanish?",
        chunks=[],
        expected=expected,
        handoff=False,
        proposed_configs=[],
    )
    assert not any(issue.code == "unanswered_question" for issue in result.issues)
    assert not any(issue.code == "possibly_unanswered_question" for issue in result.issues)
    assert not result.blockers


def test_language_named_in_preference_ask_dynamic():
    assert language_named_in_preference_ask("Do you speak Spanish?") == "Spanish"
    assert language_named_in_preference_ask("Can you reply in French?") == "French"
    assert language_named_in_preference_ask("switch to German please") == "German"
    assert language_named_in_preference_ask("Boxes please") == ""


def test_language_preference_turn_keeps_yes(orchestrator: Orchestrator):
    orchestrator.start("c-lang3")
    result = orchestrator.handle("c-lang3", "Do you speak Spanish?")
    lowered = result.reply.lower()
    assert "yes" in lowered
    assert "language" in lowered or "continue" in lowered
    assert "?" in result.reply
    assert result.source == "heuristic"
    assert not any(
        issue.get("code") == "unanswered_question" and issue.get("severity") == "block"
        for issue in (result.issues or [])
    )


def test_language_preference_not_retriggered_on_use_case(orchestrator: Orchestrator):
    orchestrator.start("c-lang4")
    first = orchestrator.handle("c-lang4", "Do you speak Spanish?")
    assert "yes" in first.reply.lower()
    orchestrator.handle("c-lang4", "boxes")
    second = orchestrator.handle("c-lang4", "for pizza")
    lowered = second.reply.lower()
    assert "continue in your language" not in lowered
    assert "yes — i can continue" not in lowered
    # Soft email or packing follow-up is fine; language Yes must not repeat.
    state = orchestrator.store.get_or_create("c-lang4")
    assert state.fields["use_case"].done
    assert "pizza" in (state.fields["use_case"].value or "").lower()


def test_sticky_language_keeps_spanish_on_short_english_answers():
    from chatbot.bot.reply_language import sticky_session_language

    assert sticky_session_language("Spanish", "English", "Mailer Box") == "Spanish"
    assert sticky_session_language("Spanish", "English", "no") == "Spanish"
    assert sticky_session_language("Spanish", "English", "296") == "Spanish"
    assert sticky_session_language("Spanish", "English", "bilal@gmail.com") == "Spanish"
    assert (
        sticky_session_language(
            "Spanish",
            "English",
            "I would like to continue the rest of this quote in English please",
        )
        == "English"
    )


def test_please_speak_spanish_is_language_preference():
    assert asks_language_preference("Please speak Spanish.")
    assert asks_language_preference("speak Spanish please")
    from chatbot.bot.reply_language import language_named_in_preference_ask

    assert language_named_in_preference_ask("Please speak Spanish.") == "Spanish"


def test_skus_wrong_question_replaced_with_designs_ask():
    from chatbot.bot.guards import ensure_priority_field_question

    fixed = ensure_priority_field_question(
        "Do you have internal product codes or article numbers for these boxes?",
        "skus",
        "How many total designs do you have?",
    )
    assert "designs" in fixed.lower()
    assert "product code" not in fixed.lower()
    assert "article" not in fixed.lower()


def test_three_side_seal_pouches_locks_catalogue_style_not_flat():
    registry = Registry.load(KB_DIR)
    state = ConversationState(id="3ss", persona="Alex Kane")
    state.fields["product"].value = "bags"
    state.fields["product"].status = "visitor"
    state.last_question = "style"
    visitor = "3 Side Seal Pouches"
    updates = extract_fields(visitor, "style", state, registry=registry)
    assert updates.get("style") == "3 Side Seal Pouches"
    assert "use_case" not in updates
    accepted, rejected = apply_field_updates(
        state, updates, visitor, registry=registry
    )
    assert accepted.get("style") == "3 Side Seal Pouches"
    assert state.fields["style"].done
    assert "style" not in rejected


def test_product_tbc_rejected_even_from_model():
    state = ConversationState(id="ptbc", persona="Alex Kane")
    state.last_question = "product"
    accepted, rejected = apply_field_updates(
        state, {"product": "to be confirmed"}, "for pizza", source="model"
    )
    assert "product" in rejected
    assert not state.fields["product"].value


def test_for_pizza_while_product_open_sets_use_case_not_product():
    state = ConversationState(id="fp", persona="Alex Kane")
    state.last_question = "product"
    updates = extract_fields("for pizza", "product", state)
    assert "product" not in updates
    assert "pizza" in (updates.get("use_case") or "").lower()
    accepted, _ = apply_field_updates(state, updates, "for pizza")
    assert accepted.get("use_case")
    assert not state.fields["product"].done


def test_repair_clears_product_tbc():
    state = ConversationState(id="rp", persona="Alex Kane")
    state.set_field("product", "to be confirmed", "model_knowledge", status="suggested")
    assert state.repair_fields() == ["product"]
    assert not state.fields["product"].value
    assert state.fields["product"].status == "unknown"


def test_size_unit_inches_merges_after_dimensions():
    state = ConversationState(id="sz-u", persona="Alex Kane")
    state.fields["product"].value = "boxes"
    state.fields["product"].status = "visitor"
    state.last_question = "sizes"
    accepted, _ = apply_field_updates(state, extract_fields("15x3x25", "sizes", state), "15x3x25")
    assert accepted.get("sizes") == "15x3x25"
    assert state.flags.get("size_pending_unit") == "15x3x25"
    state.last_question = "sizes"
    accepted2, _ = apply_field_updates(
        state, extract_fields("inches", "sizes", state), "inches"
    )
    assert "in" in (accepted2.get("sizes") or state.fields["sizes"].value)
    assert size_has_unit(state.fields["sizes"].value)


def test_failed_unit_answer_does_not_waive_size():
    state = ConversationState(id="sz-w", persona="Alex Kane")
    state.fields["product"].value = "boxes"
    state.fields["product"].status = "visitor"
    state.set_field("sizes", "15x3x25", "visitor", raw="15x3x25", status="visitor")
    state.flags["size_pending_unit"] = "15x3x25"
    state.flags["unit_asked"] = True
    state.add("visitor", "pulgadas")
    noted = state.finalize_stalled()
    assert "sizes" not in noted
    assert state.fields["sizes"].status == "visitor"
    assert not state.flags.get("unit_asked")
    assert state.size_needs_unit()


def test_foil_finish_does_not_lock_material():
    state = ConversationState(id="foil", persona="Alex Kane")
    state.fields["product"].value = "boxes"
    state.fields["product"].status = "visitor"
    state.last_question = "finishes"
    updates = extract_fields("foil printing", "finishes", state)
    assert updates.get("finishes")
    assert "foil" in updates["finishes"].lower()
    assert updates.get("material") != "foil"
    accepted, _ = apply_field_updates(state, updates, "foil printing")
    assert accepted.get("finishes")
    assert state.fields["material"].value != "foil"


def test_skus_suggestion_heuristic_gives_guidance():
    state = ConversationState(id="skus-s", persona="Alex Kane")
    state.fields["product"].value = "boxes"
    state.fields["product"].status = "visitor"
    state.last_question = "skus"
    composed = heuristic_turn(
        state, "Any suggestion?", ("skus", state.question_for("skus"))
    )
    lowered = composed.reply.lower()
    assert "design" in lowered
    assert composed.asked == "skus"
    assert "?" in composed.reply


def test_speak_pizza_is_not_language_preference():
    assert not asks_language_preference("speak pizza")
    assert not asks_language_preference("answer pizza")
    assert asks_language_preference("Do you speak Spanish?")
    assert asks_language_preference("Can you reply in French?")
    assert asks_language_preference("speak in German")


def test_inbound_rejects_language_pref_bleed():
    from chatbot.bot.reply_language import _parse_inbound

    result = _parse_inbound(
        {"language": "Spanish", "english": "Do you speak Spanish?"},
        prior="Spanish",
        raw="para pizza",
    )
    assert result.english == "para pizza"
    chip = _parse_inbound(
        {"language": "Spanish", "english": "Do you speak Spanish?"},
        prior="English",
        raw="¿Hablas español?",
    )
    assert asks_language_preference(chip.english)


def test_any_suggestion_on_style_offers_catalogue_menu():
    state = ConversationState(id="sug", persona="Alex Kane")
    state.fields["product"].value = "boxes"
    state.fields["product"].status = "visitor"
    state.last_question = "style"
    assert wants_recommendation("Any suggestion?")
    assert needs_catalogue_options(state, "Any suggestion?", {}) == "style"


def test_no_design_yet_waives_skus():
    text = "I still don't have a design."
    assert UNSPECIFIED_RE.match(text)
    state = ConversationState(id="des", persona="Alex Kane")
    state.fields["product"].value = "boxes"
    state.fields["product"].status = "visitor"
    state.last_question = "skus"
    updates = extract_fields(text, "skus", state)
    assert updates.get("skus") == "to be confirmed"
    accepted, _ = apply_field_updates(state, updates, text)
    assert accepted.get("skus") == "to be confirmed"


def test_designs_suggestion_heuristic_stays_on_skus():
    state = ConversationState(id="dsg", persona="Alex Kane")
    state.fields["product"].value = "boxes"
    state.fields["product"].status = "visitor"
    state.last_question = "skus"
    composed = heuristic_turn(state, "Any suggestion?", ("skus", state.question_for("skus")))
    lowered = composed.reply.lower()
    assert "design" in lowered
    assert composed.asked == "skus"
    assert "mailer" not in lowered  # not a style catalogue dump
