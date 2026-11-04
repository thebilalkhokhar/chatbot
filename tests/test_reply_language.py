from __future__ import annotations

from chatbot.bot.reply_language import (
    InboundLanguage,
    normalize_inbound,
    pieces_of,
    skip_inbound_llm,
    translate_outbound,
    _needs_anglicise_retry,
)
from chatbot.bot.visitor_language import ENGLISH


class _FakeLLM:
    def __init__(self, payloads: list[dict] | dict | None = None, *, error: Exception | None = None):
        if payloads is None:
            payloads = {}
        self.payloads = payloads if isinstance(payloads, list) else [payloads]
        self.error = error
        self.calls = 0
        self.names: list[str] = []

    def complete_json(self, system, user, schema, *, name="chat_reply", timeout_s=None):
        self.calls += 1
        self.names.append(name)
        if self.error:
            raise self.error
        index = min(self.calls - 1, len(self.payloads) - 1)
        return dict(self.payloads[index])

    def complete_object(self, system, user, *, name="json_object", timeout_s=None, temperature=0.0):
        self.calls += 1
        self.names.append(name)
        if self.error:
            raise self.error
        index = min(self.calls - 1, len(self.payloads) - 1)
        return dict(self.payloads[index])


def test_pieces_of_keeps_whitespace_and_splits_sentences():
    parts = pieces_of("Nice to meet you. What size do you need?")
    texts = [text for text, _ in parts]
    assert "Nice to meet you." in texts
    assert "What size do you need?" in texts
    assert any(text == " " and not translate for text, translate in parts)


def test_skip_inbound_for_email_phone_and_bare_size():
    assert skip_inbound_llm("bilal@gmail.com")
    assert skip_inbound_llm("+1 (832) 555-0100")
    assert skip_inbound_llm("11x10")
    assert skip_inbound_llm("11 x 10 in")
    assert not skip_inbound_llm("trescientos")
    assert not skip_inbound_llm("cajas")
    assert not skip_inbound_llm("pulgadas")


def test_normalize_inbound_uses_schema_json():
    client = _FakeLLM({"language": "Spanish", "english": "boxes"})
    got = normalize_inbound(
        client,  # type: ignore[arg-type]
        "cajas",
        prior_language=ENGLISH,
        ms_left=5000,
    )
    assert got == InboundLanguage(language="Spanish", english="boxes")
    assert client.calls == 1
    assert client.names == ["chat_inbound_language"]


def test_normalize_inbound_retries_when_gloss_copies_raw():
    client = _FakeLLM(
        [
            {"language": "Spanish", "english": "cajas"},
            {"language": "Spanish", "english": "boxes"},
        ]
    )
    got = normalize_inbound(
        client,  # type: ignore[arg-type]
        "cajas",
        prior_language=ENGLISH,
        ms_left=8000,
    )
    assert got == InboundLanguage(language="Spanish", english="boxes")
    assert client.calls == 2
    assert client.names[1] == "chat_inbound_language_retry"


def test_needs_anglicise_retry_helper():
    assert _needs_anglicise_retry(InboundLanguage("Spanish", "cajas"), "cajas")
    assert not _needs_anglicise_retry(InboundLanguage("Spanish", "boxes"), "cajas")
    assert not _needs_anglicise_retry(InboundLanguage("English", "cajas"), "cajas")


def test_normalize_inbound_skips_llm_for_email_keeps_prior_language():
    client = _FakeLLM({"language": "English", "english": "nope"})
    got = normalize_inbound(
        client,  # type: ignore[arg-type]
        "bilal@gmail.com",
        prior_language="Spanish",
        ms_left=5000,
    )
    assert got == InboundLanguage(language="Spanish", english="bilal@gmail.com")
    assert client.calls == 0


def test_translate_outbound_sentence_by_sentence():
    client = _FakeLLM({"translations": ["¿Qué tamaño necesita?", "Gracias."]})
    out = translate_outbound(
        ["What size do you need? Thanks."],
        language="Spanish",
        client=client,  # type: ignore[arg-type]
        visitor_samples=["Hola, quiero cajas"],
        ms_left=5000,
    )
    assert out is not None
    assert out[0] == "¿Qué tamaño necesita? Gracias."
    assert client.calls == 1


def test_translate_outbound_skips_english_session():
    client = _FakeLLM({"translations": ["x"]})
    out = translate_outbound(
        ["What size do you need?"],
        language=ENGLISH,
        client=client,  # type: ignore[arg-type]
        ms_left=5000,
    )
    assert out == ["What size do you need?"]
    assert client.calls == 0


def test_normalize_inbound_returns_none_when_late():
    client = _FakeLLM({"language": "Spanish", "english": "boxes"})
    assert (
        normalize_inbound(client, "cajas", prior_language=ENGLISH, ms_left=50)  # type: ignore[arg-type]
        is None
    )
    assert client.calls == 0
