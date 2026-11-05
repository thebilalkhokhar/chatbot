"""Turn router: classify each visitor message before extract / settle / compose.

Kinds (LLM-first meaning + field-shape contracts — not decline phrase lists):

- ask:   they asked something (question, options, topic, meta) → answer first; do not lock
- defer: soft decline / uncertainty on the open waiveable field → settle + next
- pick:  concrete answer for the open field → lock + next
- other: greeting, aside, unclear — existing paths handle it
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from . import canon
from .state import (
    AFFIRMATION_RE,
    CATALOGUE_OPTION_FIELDS,
    UNCERTAIN_WAIVE_FIELDS,
    ConversationState,
    asks_if_bot,
    asks_term_meaning,
    asks_to_share_reference,
    field_shaped_attempt,
    is_meta_question,
    is_option_request,
    is_question,
    is_soft_no_preference,
    is_visitor_greeting,
    needs_language_preference_ack,
    wants_recommendation,
)

TurnKind = Literal["ask", "defer", "pick", "other"]


@dataclass(frozen=True)
class TurnRoute:
    kind: TurnKind
    reason: str = ""


def classify_turn(
    state: ConversationState,
    visitor: str,
    *,
    registry=None,
) -> TurnRoute:
    """Decide ask / defer / pick before field extract mutates checklist state."""
    text = str(visitor or "").strip()
    if not text:
        return TurnRoute("other", "empty")

    focus = str(state.last_question or "").strip()
    family = state.family()

    # --- ask first: questions and option menus beat field settlement ---
    if asks_term_meaning(text) or asks_if_bot(text) or asks_to_share_reference(text):
        return TurnRoute("ask", "side_question")
    if needs_language_preference_ack(state, text):
        return TurnRoute("ask", "language")
    if is_meta_question(text):
        return TurnRoute("ask", "meta")
    if is_option_request(text) or wants_recommendation(text):
        return TurnRoute("ask", "options")
    if canon.topics_to_answer(text):
        return TurnRoute("ask", "topic")
    if is_question(text) and not AFFIRMATION_RE.fullmatch(text):
        # "do you have any other finish?" — answer, do not lock a finish.
        return TurnRoute("ask", "question")

    # --- pick: concrete answer for the open slot (or yes on a suggestion) ---
    pending = None
    for key in ("product", "style", "material", "finishes"):
        field_value = state.fields.get(key)
        if (
            field_value is not None
            and field_value.status == "suggested"
            and str(field_value.value or "").strip()
        ):
            pending = key
            break
    if pending and AFFIRMATION_RE.fullmatch(text):
        return TurnRoute("pick", "confirm_suggested")
    if focus and field_shaped_attempt(
        focus, text, registry=registry, family=family
    ):
        return TurnRoute("pick", f"shaped:{focus}")

    # --- defer: soft-no / uncertainty on an open waiveable field ---
    if focus in UNCERTAIN_WAIVE_FIELDS and not state.fields[focus].done:
        if is_soft_no_preference(text):
            return TurnRoute("defer", "soft_no")
        # Short non-shaped reply on a checklist field — live settles meaning;
        # contract path treats as deferral if they are not asking/picking.
        if len(text.split()) <= 12 and not is_visitor_greeting(text):
            return TurnRoute("defer", "uncertainty")

    if is_visitor_greeting(text):
        return TurnRoute("other", "greeting")
    return TurnRoute("other", "aside")


def catalogue_menu_focus(state: ConversationState, route: TurnRoute) -> str:
    """Open catalogue field to list when this turn is an ask about options."""
    if route.kind != "ask":
        return ""
    focus = str(state.last_question or "").strip()
    if focus in CATALOGUE_OPTION_FIELDS and not state.fields[focus].done:
        return focus
    return ""


def strip_checklist_locks(updates: dict[str, str]) -> dict[str, str]:
    """On ask turns, keep contact/product facts — drop checklist settlements."""
    locked = set(CATALOGUE_OPTION_FIELDS) | {
        "sizes",
        "quantity",
        "skus",
        "extras",
        "use_case",
    }
    return {key: value for key, value in updates.items() if key not in locked}
