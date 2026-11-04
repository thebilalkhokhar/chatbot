from __future__ import annotations

from dataclasses import replace

import pytest

from chatbot.bot.llm import (
    LLMClient,
    LLMError,
    REPLY_SCHEMA,
    build_payload,
    is_reasoning_model,
)


def test_reasoning_model_detection():
    assert is_reasoning_model("gpt-5-nano")
    assert is_reasoning_model("gpt-5.2-mini")
    assert is_reasoning_model("o4-mini")
    assert not is_reasoning_model("gpt-4o-mini")
    assert not is_reasoning_model("gpt-4.1")


def test_gpt5_payload_omits_temperature_and_uses_completion_tokens(config):
    payload = build_payload(config, "system", "user", REPLY_SCHEMA)

    assert payload["model"] == "gpt-5-nano"
    assert payload["response_format"]["type"] == "json_schema"
    assert "temperature" not in payload
    assert "max_tokens" not in payload
    assert payload["max_completion_tokens"] == 800
    assert payload["reasoning_effort"] == "minimal"


def test_standard_payload_keeps_chat_parameters(config):
    payload = build_payload(replace(config, model="gpt-4o-mini"), "system", "user", REPLY_SCHEMA)

    assert payload["temperature"] == 0.4
    assert payload["max_tokens"] == 400
    assert "max_completion_tokens" not in payload
    assert "reasoning_effort" not in payload


def test_call_cap_stops_before_the_next_request(config, monkeypatch):
    cfg = replace(config, mode="live", allow_live=True, api_key="test-key", max_llm_calls=1)
    client = LLMClient(cfg)
    monkeypatch.setattr(
        client,
        "_post",
        lambda payload, timeout_s=None: {
            "model": "gpt-5-nano",
            "choices": [{"message": {"content": '{"reply": "ok", "asked": "", "fields": {}}'}}],
            "usage": {},
        },
    )

    assert client.complete_json("system", "user", REPLY_SCHEMA)["reply"] == "ok"
    with pytest.raises(LLMError, match="cap"):
        client.complete_json("system", "user", REPLY_SCHEMA)
