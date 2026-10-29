from __future__ import annotations

from dataclasses import replace

import pytest

from chatbot.bot import guards
from chatbot.bot.composer import build_system, select_examples
from chatbot.bot.config import ConfigError
from chatbot.bot.replay import offline_config
from chatbot.bot.state import ConversationState, wants_recommendation


def test_context_defaults_to_full(config):
    assert config.context == "full"
    assert replace(config, context="retrieval").context == "retrieval"
    with pytest.raises(ConfigError):
        replace(config, context="everything")


def test_replay_forces_fake_mode(config):
    live = replace(config, mode="live", allow_live=True, api_key="sk-test", max_llm_calls=5)
    offline = offline_config(live)
    assert offline.mode == "fake"
    assert offline.real_llm_enabled is False
    assert offline.api_key == ""
    assert offline.max_llm_calls == 0


def test_verified_returns_every_indexed_chunk(kb_index):
    verified = kb_index.verified()
    assert len(verified) == len(kb_index.chunks)
    assert all(chunk.status == "verified" for chunk in verified)


def test_full_kb_prompt_contains_product_use_cases(kb_index):
    state = ConversationState(id="c-full", persona="alex")
    prompt = build_system(state, kb_index.verified()).lower()
    assert "ground coffee" in prompt
    assert "jerky" in prompt
    assert "cosmetic boxes" in prompt


def test_select_examples_prefers_family_and_drops_stale_fact():
    examples = [
        {"visitor": "a", "reply": "Boxes one", "family": "boxes"},
        {"visitor": "b", "reply": "Boxes two", "family": "boxes"},
        {"visitor": "c", "reply": "Boxes three", "family": "boxes"},
        {"visitor": "d", "reply": "Bags one", "family": "bags"},
        {
            "visitor": "Where are you located?",
            "reply": "We are based in Houston, Tx.",
            "family": "unknown",
        },
    ]
    picked = select_examples(examples, "boxes")
    assert [item["family"] for item in picked] == ["boxes", "boxes", "bags"]
    assert all("houston" not in item["reply"].lower() for item in picked)


@pytest.mark.parametrize(
    "text",
    [
        "suggest me the best box for dry meat",
        "what packaging do you recommend for coffee?",
        "which packaging should I use for snacks?",
        "what is best for cosmetics",
        "help me choose a bag style",
    ],
)
def test_recommendation_intent_is_detected(text):
    assert wants_recommendation(text)


@pytest.mark.parametrize(
    "text",
    [
        "what is your minimum order?",
        "I need custom boxes",
        "how much does it cost?",
        "where are you located?",
    ],
)
def test_non_recommendation_requests_are_ignored(text):
    assert not wants_recommendation(text)


def test_guard_warns_when_recommendation_is_not_answered(config):
    state = ConversationState(id="c-rec", persona="alex")
    result = guards.check_reply(
        "What box size are you looking for?",
        state,
        visitor_text="suggest me the best box for coffee",
        expected=("sizes", "What box size are you looking for?"),
    )
    assert "recommendation_unanswered" in result.codes()
    assert result.ok


def test_guard_accepts_a_concrete_recommendation(config):
    state = ConversationState(id="c-rec", persona="alex")
    result = guards.check_reply(
        "For ground coffee, I'd suggest a stand-up pouch with a degassing valve. "
        "What box size are you looking for?",
        state,
        visitor_text="suggest me the best packaging for coffee",
        expected=("sizes", "What box size are you looking for?"),
    )
    assert "recommendation_unanswered" not in result.codes()
    assert result.ok
