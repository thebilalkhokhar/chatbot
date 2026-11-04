from __future__ import annotations

from chatbot.bot.reply_judge import (
    JudgeVerdict,
    merge_corrections,
    waiver_fields_reasked,
)
from chatbot.bot.state import (
    STATUS_VISITOR,
    TO_BE_CONFIRMED,
    ConversationState,
    apply_field_updates,
)


def test_waiver_fields_reasked_catches_tbc_still_asking():
    detail = waiver_fields_reasked(
        asked="finishes",
        fields={"finishes": TO_BE_CONFIRMED},
        last_question="finishes",
    )
    assert "finishes" in detail
    assert TO_BE_CONFIRMED in detail


def test_waiver_fields_reasked_allows_next_field():
    assert (
        waiver_fields_reasked(
            asked="material",
            fields={"finishes": TO_BE_CONFIRMED},
            last_question="finishes",
        )
        == ""
    )


def test_waiver_fields_reasked_style_no_preference():
    detail = waiver_fields_reasked(
        asked="style",
        fields={"style": "no preference"},
        last_question="style",
    )
    assert "no preference" in detail


def test_merge_corrections_skips_blanks():
    assert merge_corrections("", "fix A", "  ", "fix B") == "fix A\nfix B"


def test_model_tbc_on_finish_accepted_even_if_visitor_says_no_idea():
    """Model open-field TBC must not be regex-vetoed by 'idea' inside 'no idea'."""
    state = ConversationState(id="judge-tbc", persona="Alex Kane")
    state.fields["product"].value = "boxes"
    state.fields["product"].status = STATUS_VISITOR
    state.last_question = "finishes"
    accepted, rejected = apply_field_updates(
        state,
        {"finishes": TO_BE_CONFIRMED},
        "No idea",
        source="model",
    )
    assert accepted.get("finishes") == TO_BE_CONFIRMED
    assert rejected == {}
    assert state.fields["finishes"].status == "waived"


def test_model_no_preference_on_style_accepted_for_open_field():
    state = ConversationState(id="judge-style", persona="Alex Kane")
    state.fields["product"].value = "boxes"
    state.fields["product"].status = STATUS_VISITOR
    state.last_question = "style"
    accepted, rejected = apply_field_updates(
        state,
        {"style": "no preference"},
        "whatever you think",
        source="model",
    )
    assert accepted.get("style") == "no preference"
    assert rejected == {}
    assert state.fields["style"].status == "waived"


def test_model_cannot_tbc_side_field_while_another_is_open():
    state = ConversationState(id="judge-side", persona="Alex Kane")
    state.fields["product"].value = "boxes"
    state.fields["product"].status = STATUS_VISITOR
    state.last_question = "quantity"
    accepted, rejected = apply_field_updates(
        state,
        {"finishes": TO_BE_CONFIRMED, "quantity": "500"},
        "500",
        source="model",
    )
    assert accepted.get("quantity") == "500"
    assert "finishes" in rejected
    assert not state.fields["finishes"].done


def test_judge_verdict_defaults():
    assert JudgeVerdict(ok=True).reason == ""
    assert JudgeVerdict(ok=False, reason="fix it").reason == "fix it"
