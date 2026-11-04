from __future__ import annotations

from chatbot.bot.visitor_language import ENGLISH


def test_fake_mode_stays_english_without_inbound_llm(orchestrator):
    orchestrator.start("c-es-fake")
    result = orchestrator.handle("c-es-fake", "Hola, quiero cajas")
    assert result.language == ENGLISH
    # Without a live LLM, product words in other languages are not extracted.
    assert not result.accepted.get("product")


def test_inbound_anglicises_before_extract(orchestrator, monkeypatch):
    orchestrator.start("c-es-in")

    def fake_inbound(state, raw_visitor, *, started):
        state.flags["language"] = "Spanish"
        state.messages[-1].english = "boxes"
        state.flags["inbound_anglicised"] = True
        return "Spanish", "boxes"

    monkeypatch.setattr(orchestrator, "_inbound_language", fake_inbound)
    monkeypatch.setattr(
        orchestrator,
        "_outbound_language",
        lambda state, english, *, language, started: (
            "¿Qué vas a empacar?" if language == "Spanish" else english
        ),
    )

    result = orchestrator.handle("c-es-in", "cajas")
    assert result.language == "Spanish"
    assert result.accepted.get("product") == "boxes"
    assert result.reply == "¿Qué vas a empacar?"
    assert result.reply_english
    state = orchestrator.store.get_or_create("c-es-in")
    assert state.messages[1].text == "cajas"
    assert state.messages[1].english == "boxes"
    assert state.messages[-1].shown == result.reply


def test_quantity_word_anglicised_to_digits(orchestrator, monkeypatch):
    orchestrator.start("c-qty")
    state = orchestrator.store.get_or_create("c-qty")
    state.fields["product"].value = "boxes"
    state.fields["product"].status = "visitor"
    state.fields["use_case"].value = "pizza"
    state.fields["use_case"].status = "visitor"
    state.flags["soft_email_asked"] = True
    state.flags["language"] = "Spanish"
    state.last_question = "quantity"
    orchestrator.store.save(state)

    def fake_inbound(state, raw_visitor, *, started):
        state.flags["language"] = "Spanish"
        state.messages[-1].english = "300"
        return "Spanish", "300"

    monkeypatch.setattr(orchestrator, "_inbound_language", fake_inbound)
    monkeypatch.setattr(
        orchestrator,
        "_outbound_language",
        lambda state, english, *, language, started: english,
    )

    result = orchestrator.handle("c-qty", "trescientos")
    assert result.language == "Spanish"
    state = orchestrator.store.get_or_create("c-qty")
    assert "300" in str(state.fields["quantity"].value)
    assert state.messages[-2].text == "trescientos"
    assert state.messages[-2].english == "300"


def test_unit_word_anglicised_for_size(orchestrator, monkeypatch):
    orchestrator.start("c-unit")
    state = orchestrator.store.get_or_create("c-unit")
    state.fields["product"].value = "boxes"
    state.fields["product"].status = "visitor"
    state.fields["use_case"].value = "pizza"
    state.fields["use_case"].status = "visitor"
    state.fields["quantity"].value = "300"
    state.fields["quantity"].status = "visitor"
    state.fields["sizes"].value = "11x10"
    state.fields["sizes"].status = "visitor"
    state.flags["size_pending_unit"] = "11x10"
    state.flags["soft_email_asked"] = True
    state.flags["language"] = "Spanish"
    state.last_question = "sizes"
    orchestrator.store.save(state)

    def fake_inbound(state, raw_visitor, *, started):
        state.flags["language"] = "Spanish"
        state.messages[-1].english = "inches"
        return "Spanish", "inches"

    monkeypatch.setattr(orchestrator, "_inbound_language", fake_inbound)
    monkeypatch.setattr(
        orchestrator,
        "_outbound_language",
        lambda state, english, *, language, started: english,
    )

    result = orchestrator.handle("c-unit", "pulgadas")
    assert result.language == "Spanish"
    state = orchestrator.store.get_or_create("c-unit")
    assert "in" in state.fields["sizes"].value.lower() or "inch" in state.fields["sizes"].value.lower()
    assert state.messages[-2].text == "pulgadas"
    assert state.messages[-2].english == "inches"


def test_outbound_uses_session_language(orchestrator, monkeypatch):
    orchestrator.start("c-out")

    def fake_inbound(state, raw_visitor, *, started):
        state.flags["language"] = "German"
        state.messages[-1].english = "boxes"
        return "German", "boxes"

    monkeypatch.setattr(orchestrator, "_inbound_language", fake_inbound)
    monkeypatch.setattr(
        orchestrator,
        "_outbound_language",
        lambda state, english, *, language, started: (
            "Welche Größe brauchen Sie?" if language == "German" else english
        ),
    )
    result = orchestrator.handle("c-out", "kartons")
    assert result.language == "German"
    assert result.reply == "Welche Größe brauchen Sie?"
