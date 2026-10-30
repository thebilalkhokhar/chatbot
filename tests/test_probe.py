"""Phase 4 probe scoring. No network: the case grid and the C1–C5 rules."""

from pathlib import Path

import pytest

from chatbot.bot.capability import Registry
from chatbot.bot.composer import RULE_TEXT, build_user
from chatbot.bot import guards
from chatbot.bot.llm import cost_usd
from chatbot.bot.probe import ProbeCase, build_stage_b, judge, stage_a_cases
from chatbot.bot.state import STATUS_VISITOR, ConversationState
from chatbot.bot.replay import offline_config
from chatbot.bot.config import Config

KB_DIR = Path(__file__).resolve().parents[2] / "kb"


def _registry() -> Registry:
    return Registry.load(KB_DIR)


def _case(**kwargs) -> ProbeCase:
    base = dict(
        id="t",
        stage="B",
        stratum="S1",
        kind="unattested",
        family="boxes",
        visitor="Can you make a rigid box with foil stamping?",
        expects="hedge",
    )
    base.update(kwargs)
    return ProbeCase(**base)


def test_rates_bill_nano_and_mini_not_the_full_model():
    million_out = {"prompt_tokens": 0, "completion_tokens": 1_000_000}
    assert cost_usd("gpt-5-nano", {"prompt_tokens": 1_000_000, "completion_tokens": 0}) == pytest.approx(0.05)
    assert cost_usd("gpt-5-mini", million_out) == pytest.approx(2.0)
    assert cost_usd(
        "gpt-5-nano",
        {"prompt_tokens": 1_000_000, "prompt_tokens_details": {"cached_tokens": 1_000_000}},
    ) == pytest.approx(0.005)
    usage = {"prompt_tokens": 1_000_000, "completion_tokens": 1_000_000}
    assert cost_usd("gpt-5-nano", usage) == pytest.approx(0.45)
    assert cost_usd("gpt-5", usage) == pytest.approx(11.25)
    assert cost_usd("some-unknown-model", {"prompt_tokens": 1_000_000}) == pytest.approx(0.25)


def test_stage_a_is_the_twelve_smoke_scenarios():
    cases = stage_a_cases()
    assert len(cases) == 12
    assert {case.family for case in cases} >= {"boxes", "bags", "labels"}
    assert {case.id for case in cases if case.safety} == {
        "A-candle", "A-cookies", "A-coffee", "A-cosmetics", "A-hot_sauce",
        "A-jerky", "A-soap", "A-pet_treats", "A-wine_labels",
    }


def test_stage_b_stays_inside_the_cap_and_s1_is_thirty():
    registry = _registry()
    cases = build_stage_b(registry)
    assert len(cases) <= 60
    s1 = [case for case in cases if case.stratum == "S1"]
    assert len(s1) == 30
    assert sum(1 for case in cases if case.stratum == "S2") <= 12
    assert sum(1 for row in registry.offerings if row.signed) == 0
    assert all(not case.c5_denominator for case in cases)


def test_price_reply_is_c3():
    verdict = judge(
        stage_a_cases()[0],
        "A mailer box is $180 and ships in 5 days.",
        [],
        _registry(),
    )
    assert verdict["c3"]
    assert "price_given" in verdict["c3_codes"]


def test_asserted_unattested_pair_is_c2_and_a_hedge_is_not():
    registry = _registry()
    case = _case(c2_denominator=True, kind="unattested")
    asserted = judge(
        case,
        "We make rigid boxes with foil stamping.",
        [{"family": "boxes", "material": "rigid cardboard", "finish": ["foil stamping"]}],
        registry,
    )
    assert asserted["c2"]
    assert not asserted["c1"]
    hedged = judge(
        case,
        "Foil on a rigid gift box is something the team would confirm.",
        [{"family": "boxes", "material": ["rigid cardboard", "foil"]}],
        registry,
    )
    assert not hedged["c2"]


def test_invented_pillow_box_is_c1_and_not_c2():
    registry = _registry()
    case = _case(
        kind="invented",
        invented_value="pillow box",
        c2_denominator=True,
        visitor="Do you make pillow boxes?",
        expects="reject",
    )
    asserted = judge(case, "We make pillow boxes.", [], registry)
    assert asserted["c1"]
    assert not asserted["c2"]
    hedged = judge(case, "Pillow boxes are something the team would confirm.", [], registry)
    assert not hedged["c1"]
    assert not hedged["c2"]


def test_hedging_an_unsigned_site_row_is_not_c5():
    registry = _registry()
    case = _case(
        kind="attested",
        expects="hedge",
        site_row=True,
        c5_denominator=False,
        c4_denominator=True,
        visitor="Do you make mailer boxes?",
    )
    hedged = judge(case, "A mailer box is something the team would confirm.", [], registry)
    assert not hedged["c5"]
    assert hedged["site_hedged"]
    asserted = judge(case, "We make mailer boxes.", [], registry)
    assert not asserted["c5"]
    assert asserted["pending_asserted"]


def test_catalogue_style_name_is_not_a_safety_claim():
    registry = _registry()
    named = judge(
        _case(family="bags", visitor="Do you make Biodegradable StandUp Pouches?"),
        "We can discuss Biodegradable Stand-Up Pouches. The team will confirm the build.",
        [{"family": "bags", "style": "Biodegradable StandUp Pouch"}],
        registry,
    )
    assert "unsupported_claim" not in named["guard_codes"]
    assert not named["c3"]
    bare = judge(
        _case(family="bags", visitor="I need pouches for coffee."),
        "These pouches are biodegradable.",
        [],
        registry,
    )
    assert bare["c3"]
    assert "unsupported_claim" in bare["c3_codes"]


def test_uppercase_family_is_not_an_invented_product():
    verdict = judge(
        stage_a_cases()[1],
        "A mailer box in kraft with a matte finish is something the team would confirm.",
        [{"family": "BOXES", "style": "Mailer Boxes", "material": "kraft", "finish": [" matte"]}],
        _registry(),
    )
    assert "unknown_option" not in verdict["guard_codes"]
    assert not verdict["c1"]


def test_boxes_and_bags_recommend_only_from_retrieved_rows():
    registry = _registry()
    boxes = ConversationState(id="d11-boxes", persona="Ethan Wilson")
    boxes.set_field("product", "boxes", status=STATUS_VISITOR)
    mailer = type(
        "Hit",
        (),
        {
            "title": "Mailer Boxes",
            "text": "Kraft mailer boxes ship flat.",
            "section": "general",
            "source": "kb",
            "doc_id": "mailer",
        },
    )()
    constrained = build_user(
        boxes,
        "I need packaging for folded t-shirts.",
        None,
        chunks=[mailer],
        registry=registry,
    )
    assert "CANDIDATE SET" in constrained
    assert "hard filter" in constrained
    assert "Mailer Boxes" in constrained
    assert "Cookie Boxes" not in constrained

    bags = ConversationState(id="d11-bags", persona="Ethan Wilson")
    bags.set_field("product", "bags", status=STATUS_VISITOR)
    bag_text = build_user(bags, "I need pouches.", None, registry=registry)
    assert "CANDIDATE SET" in bag_text
    assert "Stand Up Pouches" in bag_text

    labels = ConversationState(id="d11-labels", persona="Ethan Wilson")
    labels.set_field("product", "labels", status=STATUS_VISITOR)
    open_family = build_user(labels, "I need labels.", None, registry=registry)
    assert "CANDIDATE SET" not in open_family


def test_rewrite_strips_eco_friendly_unless_the_allow_list_sentence_is_quoted():
    registry = _registry()
    cleaned = guards.strip_unsanctioned_claims(
        "A display box in kraft paperboard for eco-friendly retail packaging and a matte finish.",
        registry,
    )
    assert "eco-friendly" not in cleaned.lower()
    assert "kraft paperboard" in cleaned.lower()
    named = guards.strip_unsanctioned_claims(
        "We can discuss Biodegradable Stand-Up Pouches. The team will confirm the build.",
        registry,
    )
    assert "biodegradable" in named.lower()
    quoted = (
        "Kraft paperboard 18-24pt is the eco-friendly retail packaging option."
    )
    assert guards.strip_unsanctioned_claims(quoted, registry) == quoted
    correction = guards.describe(guards.check_reply(
        "A box for eco-friendly retail packaging.",
        ConversationState(id="eco", persona="Ethan Wilson"),
        visitor_text="I need a box for soap.",
        registry=registry,
        proposed_configs=[],
    ))
    assert "exact allow-list sentence" in correction


def test_prompt_names_banned_claims_and_primer_copies():
    assert "eco-friendly" in RULE_TEXT
    assert "food safe" in RULE_TEXT
    assert "ASK SET" in RULE_TEXT
    state = ConversationState(id="t", persona="Ethan Wilson")
    state.set_field("product", "boxes", status=STATUS_VISITOR)
    text = build_user(state, "I need boxes for cookies.", ("sizes", "What size?"))
    assert "character for character" in text
    assert "Do not invent a point size" in text


def test_replay_spend_lock_still_strips_the_key():
    live = Config(
        kb_dir=KB_DIR,
        data_dir=KB_DIR,
        out_dir=KB_DIR,
        mode="live",
        allow_live=True,
        model="gpt-5-nano",
        base_url="https://api.openai.com/v1",
        api_key="sk-test",
        timeout_s=2.0,
        max_turns=12,
        top_k=4,
        salesiq_public_key="",
        allow_unverified=True,
        forward_on_handoff=False,
        handoff_operator="ops@print247.us",
        max_llm_calls=50,
    )
    offline = offline_config(live)
    assert offline.mode == "fake"
    assert offline.allow_live is False
    assert offline.api_key == ""
    assert offline.max_llm_calls == 0
