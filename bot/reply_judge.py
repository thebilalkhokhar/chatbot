"""Outbound reply judge: meaning check before the visitor sees the draft.

Hard guards still own safety (price, banned claims, format). This pass owns
intent mismatches that phrase regex cannot cover — especially deferral /
uncertainty on the open checklist field while the draft re-asks it.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from .llm import LLMClient, LLMError
from .state import (
    TO_BE_CONFIRMED,
    UNCERTAIN_WAIVE_FIELDS,
    ConversationState,
    is_field_waiver_value,
    is_finish_none_token,
    is_to_be_confirmed,
)

log = logging.getLogger("chatbot.reply_judge")

# Short HTTP budget — fail open if the turn is already tight.
JUDGE_S = 3.0

JUDGE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "ok": {
            "type": "boolean",
            "description": "True only if the draft is fine to send as-is.",
        },
        "reason": {
            "type": "string",
            "description": "Empty when ok; otherwise a short fix instruction for the composer.",
        },
    },
    "required": ["ok", "reason"],
}


@dataclass(frozen=True)
class JudgeVerdict:
    ok: bool
    reason: str = ""


def waiver_fields_reasked(
    *,
    asked: str,
    fields: dict[str, str] | None,
    last_question: str,
) -> str:
    """Deterministic: model waived the open field in `fields` but still asks it."""
    focus = str(last_question or "").strip()
    if not focus or focus not in UNCERTAIN_WAIVE_FIELDS:
        return ""
    value = str((fields or {}).get(focus) or "").strip()
    # Catalogue finish "none" is a no-coating waiver, not a settled coating pick.
    if focus == "finishes" and is_finish_none_token(value):
        value = TO_BE_CONFIRMED
    if not is_field_waiver_value(value):
        return ""
    asked_key = str(asked or "").strip()
    if asked_key != focus:
        return ""
    token = "to be confirmed" if is_to_be_confirmed(value) else "no preference"
    return (
        f"fields.{focus} is already \"{token}\" (visitor deferred / unsure). "
        f"Do not set asked={focus}. Acknowledge briefly that the team will confirm it, "
        "ask the next ASK SET field, and keep that waiver in fields."
    )


def settled_field_reasked(*, asked: str, state: ConversationState) -> str:
    """Deterministic: checklist field is already settled in state but draft still asks it.

    Covers the live path where the model re-asks after a soft decline while backup
    (or an earlier turn) already waived / locked the field — reply must move on.
    """
    asked_key = str(asked or "").strip()
    if not asked_key or asked_key not in state.fields:
        return ""
    field = state.fields[asked_key]
    if not field.done:
        return ""
    if asked_key == "sizes" and state.size_needs_unit():
        return ""
    token = " ".join(str(field.value or "").split()) or "settled"
    return (
        f"{asked_key} is already settled ({token!r}). Do not ask {asked_key} again. "
        "Acknowledge briefly if needed, ask the next ASK SET field, and keep the "
        "settled value."
    )


def _judge_system() -> str:
    return "\n".join(
        [
            "You judge one packaging sales-chat draft before it is sent.",
            "Return JSON: {\"ok\": true|false, \"reason\": \"...\"}.",
            "ok=true only when the draft matches the visitor's intent for this turn.",
            "Fail (ok=false) when:",
            "- The visitor deferred, was unsure, had no preference, declined specials, "
            "or asked the team to decide later about the OPEN field (judge slang and "
            "elongated chat spelling by meaning), but the draft re-asks that same field "
            "or treats their message as unanswered.",
            "- The visitor clearly asked for options/suggestions on the open catalogue "
            "field, but the draft does not list concrete options.",
            "- A field is marked suggested and they affirmed it, but the draft still "
            "asks that field or offers more alternatives for it.",
            "- A field is marked suggested and they declined / said no preference without "
            "asking for alternatives, but the draft keeps pushing that same suggestion.",
            "- Finish fields: catalogue \"none\" means no coating / team confirms — if the "
            "draft sets finishes=none (or to be confirmed) but still asks finish again, fail.",
            "Pass (ok=true) when the draft is a reasonable next sales step, even if terse.",
            "reason must be empty when ok=true. When ok=false, reason is a short imperative "
            "fix for the composer (what to change), not a scolding.",
            "Do not invent policy, prices, or catalogue facts. Do not fail for style tone alone.",
        ]
    )


def judge_reply(
    client: LLMClient,
    *,
    visitor: str,
    reply: str,
    open_field: str,
    asked: str,
    fields: dict[str, str] | None,
    ms_left: float,
) -> JudgeVerdict:
    """LLM intent check. Raises LLMError on transport/parse failure; caller fails open."""
    timeout_s = min(JUDGE_S, max(0.0, ms_left / 1000.0))
    if timeout_s < 0.25:
        log.info("reply judge skipped: only %.0fms left", ms_left)
        return JudgeVerdict(ok=True)

    field_lines = []
    for key, value in (fields or {}).items():
        text = str(value or "").strip()
        if text:
            field_lines.append(f"- {key}: {text}")
    fields_block = "\n".join(field_lines) if field_lines else "(none)"

    user = "\n".join(
        [
            f"Open checklist field: {open_field or '(none)'}",
            f"Draft asked=: {asked or '(none)'}",
            f"Visitor message:\n{visitor}",
            f"Draft reply:\n{reply}",
            f"Draft fields:\n{fields_block}",
        ]
    )
    parsed = client.complete_json(
        _judge_system(),
        user,
        JUDGE_SCHEMA,
        name="chat_reply_judge",
        timeout_s=timeout_s,
    )
    ok = bool(parsed.get("ok"))
    reason = str(parsed.get("reason") or "").strip()
    if ok:
        return JudgeVerdict(ok=True)
    if not reason:
        reason = (
            "The draft does not match the visitor's intent for the open checklist field. "
            "Fix the reply and fields, then continue."
        )
    return JudgeVerdict(ok=False, reason=reason)


def merge_corrections(*parts: str) -> str:
    chunks = [str(part).strip() for part in parts if str(part or "").strip()]
    return "\n".join(chunks)
