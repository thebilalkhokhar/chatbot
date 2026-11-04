"""Phase 3 boundary tests. Fake mode: the guards and the prompt, no paid calls."""

from pathlib import Path

from chatbot.bot import canon, guards
from chatbot.bot.capability import Exclusion, Offering, Registry
from chatbot.bot.composer import build_system
from chatbot.bot.kb import ScoredChunk
from chatbot.bot.llm import REPLY_SCHEMA
from chatbot.bot.state import STATUS_VISITOR, ConversationState

KB_DIR = Path(__file__).resolve().parents[2] / "kb"


def _registry() -> Registry:
    return Registry.load(KB_DIR)


def _state(*visitor: str) -> ConversationState:
    state = ConversationState(id="p3", persona="Ethan Wilson")
    for text in visitor:
        state.add("visitor", text)
    return state


def _excluded() -> Registry:
    return Registry(
        vocabulary={
            "boxes": {
                "style": ("Mailer Boxes", "Gift Boxes"),
                "material": ("kraft", "rigid cardboard"),
                "finish": ("matte",),
            }
        },
        offerings=(
            Offering(
                family="boxes",
                styles=("Mailer Boxes",),
                materials=("kraft",),
                finishes=("matte",),
                approved="sales",
                scope="page",
                source="test",
            ),
        ),
        exclusions=(
            Exclusion(
                family="boxes",
                kind="pair",
                styles=("Gift Boxes",),
                materials=("kraft",),
                reason="kraft is not used for gift boxes",
                source="test",
            ),
        ),
    )


def test_schema_carries_move_configs_and_basis():
    assert set(REPLY_SCHEMA["required"]) >= {"reply", "move", "proposed_configs", "fields_proposed"}
    item = REPLY_SCHEMA["properties"]["proposed_configs"]["items"]["properties"]
    assert "basis" in item and "size_source" in item
    assert "basis" in REPLY_SCHEMA["properties"]["fields_proposed"]["items"]["properties"]


def test_there_is_no_sizing_calculator():
    bot = Path(__file__).resolve().parents[1] / "bot"
    assert not (bot / "sizing.py").exists()
    assert not (KB_DIR / "capabilities" / "sizing-rules.md").exists()


def test_prefix_is_stable_and_facts_carry_offerable_flags():
    registry = _registry()
    first = ConversationState(id="a", persona="Ethan Wilson")
    second = ConversationState(id="b", persona="Ethan Wilson")
    second.set_field("product", "boxes")
    assert build_system(first, registry) == build_system(second, registry)
    text = canon.facts_for_prompt()
    assert "[offerable: true]" in text
    assert "[offerable: false]" in text
    assert canon.OPERATOR_EMAIL in text


def test_rigid_foil_asserted_blocks_and_a_hedged_unknown_passes():
    registry = _registry()
    state = _state("hello")
    blocked = guards.check_reply(
        "We make rigid boxes with foil stamping.",
        state,
        visitor_text="hello",
        registry=registry,
        proposed_configs=[
            {"family": "boxes", "material": "rigid cardboard", "finish": ["foil stamping"]}
        ],
    )
    assert "unsupported_configuration" in blocked.codes()
    assert not blocked.ok

    passed = guards.check_reply(
        "Foil on a rigid gift box is something the team would confirm.",
        state,
        visitor_text="hello",
        registry=registry,
        proposed_configs=[{"family": "boxes", "material": ["rigid cardboard", "foil"]}],
    )
    assert "unsupported_configuration" not in passed.codes()
    assert "unknown_capability_unhedged" not in passed.codes()
    assert "excluded_combination" not in passed.codes()
    assert passed.ok


def test_price_food_safe_and_uncited_judgement():
    registry = _registry()
    state = _state("hello")
    price = guards.check_reply("That'll be $180.", state, visitor_text="hello", registry=registry)
    assert "price_given" in price.codes()
    assert not price.ok

    food = guards.check_reply("It's food safe.", state, visitor_text="hello", registry=registry)
    assert "unsupported_claim" in food.codes()
    blocked = next(issue for issue in food.issues if issue.code == "unsupported_claim")
    assert blocked.severity == "block"
    assert not food.ok

    judgement = guards.check_reply(
        "A rigid box keeps the jar upright.",
        state,
        visitor_text="hello",
        registry=registry,
    )
    assert "unsupported_claim" not in judgement.codes()
    assert "unsanctioned_dimension" not in judgement.codes()
    assert judgement.ok


def test_sizing_policy_allows_only_catalogue_rows_and_the_visitors_number():
    registry = _registry()
    state = _state("hello")
    invented = guards.check_reply(
        "Usually 8x6x4 is typical for a jar.",
        state,
        visitor_text="hello",
        registry=registry,
    )
    assert "unsanctioned_dimension" in invented.codes()
    assert not invented.ok

    listed = guards.check_reply(
        "We list a 23 x 66 pull-up; the team confirms the fit. What are you packing?",
        state,
        visitor_text="hello",
        registry=registry,
    )
    assert "unsanctioned_dimension" not in listed.codes()
    assert listed.ok

    fit = guards.check_reply(
        "The 23 x 66 we list will fit your jar.",
        state,
        visitor_text="hello",
        registry=registry,
    )
    assert "unsanctioned_dimension" in fit.codes()
    assert not fit.ok

    ask = guards.check_reply(
        "Send me your product's measurements and the team will confirm the size.",
        state,
        visitor_text="hello",
        registry=registry,
    )
    assert "unsanctioned_dimension" not in ask.codes()
    assert ask.ok

    echoed = _state("8 x 6 x 4")
    echoed.set_field("sizes", "8 x 6 x 4", raw="8 x 6 x 4", status=STATUS_VISITOR)
    echo = guards.check_reply(
        "Your 8 x 6 x 4 is noted, and the team confirms the final size.",
        echoed,
        visitor_text="8 x 6 x 4",
        registry=registry,
    )
    assert "unsanctioned_dimension" not in echo.codes()
    assert echo.ok


def test_two_options_in_prose_and_one_config_is_a_mismatch():
    registry = _registry()
    state = _state("hello")
    result = guards.check_reply(
        "A mailer box or a tuck box would both work.",
        state,
        visitor_text="hello",
        registry=registry,
        proposed_configs=[{"family": "boxes", "style": "Mailer Boxes"}],
    )
    assert "reply_config_mismatch" in result.codes()
    assert not result.ok


def test_an_empty_config_list_is_not_rejected():
    registry = _registry()
    state = _state("hello")
    result = guards.check_reply(
        "Good morning. A size of 0x0 cannot be made — what measurements should we use?",
        state,
        visitor_text="good morning, the size is 0x0",
        registry=registry,
        proposed_configs=[],
    )
    assert "reply_config_mismatch" not in result.codes()
    assert "unknown_option" not in result.codes()
    assert "unknown_capability_unhedged" not in result.codes()
    assert "unsupported_configuration" not in result.codes()
    assert "unstructured_recommendation" not in result.codes()
    assert result.ok


def test_rewrite_is_reconciled_again():
    registry = _registry()
    state = _state("hello")
    first = guards.check_reply("That'll be $180.", state, visitor_text="hello", registry=registry, proposed_configs=[])
    assert not first.ok
    second = guards.check_reply(
        "A mailer box or a tuck box would both work.",
        state,
        visitor_text="hello",
        registry=registry,
        proposed_configs=[{"family": "boxes", "style": "Mailer Boxes"}],
    )
    assert "reply_config_mismatch" in second.codes()
    assert not second.ok


def test_unknown_option_and_excluded_pair_and_the_alternative():
    registry = _registry()
    state = _state("hello")
    unknown = guards.check_reply(
        "A unicorn box would work.",
        state,
        visitor_text="hello",
        registry=registry,
        proposed_configs=[{"family": "boxes", "style": "unicorn box"}],
    )
    assert "unknown_option" in unknown.codes()
    assert not unknown.ok

    local = _excluded()
    asserted = guards.check_reply(
        "We make kraft gift boxes.",
        state,
        visitor_text="hello",
        registry=local,
        proposed_configs=[{"family": "boxes", "style": "Gift Boxes", "material": "kraft"}],
    )
    assert "excluded_combination" in asserted.codes()
    assert not asserted.ok

    refused = guards.check_reply(
        "We don't make kraft gift boxes.",
        state,
        visitor_text="hello",
        registry=local,
        proposed_configs=[{"family": "boxes", "style": "Gift Boxes", "material": "kraft"}],
    )
    assert "excluded_combination" not in refused.codes()
    assert "nearest_alternative_missing" in refused.codes()
    assert refused.ok

    offered = guards.check_reply(
        "We don't make kraft gift boxes. A mailer box in kraft with a matte finish is the closest.",
        state,
        visitor_text="hello",
        registry=local,
        proposed_configs=[
            {"family": "boxes", "style": "Gift Boxes", "material": "kraft"},
            {"family": "boxes", "style": "Mailer Boxes", "material": "kraft", "finish": ["matte"]},
        ],
    )
    assert "excluded_combination" not in offered.codes()
    assert "nearest_alternative_missing" not in offered.codes()
    assert offered.ok


def test_operator_email_blocks_and_hours_wait_to_be_asked():
    state = _state("hello")
    leaked = guards.check_reply(
        "Email johnhenry.it@print247.us and the team will take it from there.",
        state,
        visitor_text="hello",
    )
    assert "contact_offered_unasked" in leaked.codes()
    assert not leaked.ok

    houston = guards.check_reply("We are based in Houston.", state, visitor_text="where are you located?")
    assert "contact_offered_unasked" in houston.codes()
    assert not houston.ok

    hours = guards.check_reply(
        "Our office is open Monday to Friday, 9am to 5pm.",
        state,
        visitor_text="hello",
    )
    blocked = next(issue for issue in hours.issues if issue.code == "contact_offered_unasked")
    assert blocked.severity == "block"
    assert not hours.ok

    asked = guards.check_reply(
        "Our office is open Monday to Friday, 9am to 5pm.",
        state,
        visitor_text="what are your office hours?",
    )
    assert "contact_offered_unasked" not in asked.codes()


def test_paypal_only_conflicts_with_canon():
    state = _state("hello")
    result = guards.check_reply("We accept PayPal only.", state, visitor_text="hello")
    assert "canon_conflict" in result.codes()
    assert "tier_b_hallucination" in result.codes()
    assert not result.ok


def test_a_non_tier_b_number_is_a_warning_and_a_minimum_still_blocks():
    state = _state("hello")
    soft = guards.check_reply("We have been printing for 42 years.", state, visitor_text="hello")
    assert "untraceable_number" in soft.codes()
    assert soft.ok
    hard = guards.check_reply("Our minimum is 750 units.", state, visitor_text="What is your MOQ?")
    assert "untraceable_number" in hard.codes()
    assert not hard.ok


def test_team_confirms_is_not_a_promise_to_check():
    state = _state("hello")
    result = guards.check_reply(
        "The team confirms the exact fit with your quote. What are you packing?",
        state,
        visitor_text="hello",
    )
    assert "promise_to_check" not in result.codes()


def test_recommendation_blocks_once_the_use_case_is_known():
    state = _state("coffee")
    state.set_field("use_case", "coffee", status=STATUS_VISITOR)
    result = guards.check_reply(
        "What size do you need?",
        state,
        visitor_text="what packaging do you recommend for coffee?",
    )
    assert "recommendation_unanswered" in result.codes()
    assert not result.ok


def test_catalogue_context_keeps_the_detected_family(orchestrator, kb_index):
    boxes = next(
        chunk for chunk in kb_index.chunks if "boxes" in chunk.families and "banners" not in chunk.families
    )
    banners = next(
        chunk for chunk in kb_index.chunks if "banners" in chunk.families and "boxes" not in chunk.families
    )
    state = ConversationState(id="fam", persona="Ethan Wilson")
    state.set_field("product", "boxes")
    picked = orchestrator._prompt_chunks(
        [ScoredChunk(chunk=boxes, score=1.0), ScoredChunk(chunk=banners, score=1.0)],
        state,
    )
    assert [item.chunk.id for item in picked] == [boxes.id]


def test_a_meta_question_gets_the_fixed_line_and_not_a_topic_lecture(orchestrator):
    state = ConversationState(id="meta", persona="Ethan Wilson")
    state.add("visitor", "why are you asking me that")
    reply = orchestrator._safe_fallback(state, ("product", "What are you looking to have made?"), "")
    lowered = reply.lower()
    assert "fair question" in lowered
    assert "pdf" not in lowered
    assert "eps" not in lowered
