from __future__ import annotations

import re
from dataclasses import dataclass, field

from . import canon
from .llm import LLMClient, REPLY_SCHEMA
from .personas import PERSONAS, persona_for
from .state import (
    ConversationState,
    asks_if_bot,
    family_of,
    is_goodbye,
    is_job_pitch,
    is_price_objection,
    is_question,
    normalize_finish,
    size_is_unknown,
    wants_recommendation,
)

HANDOFF_LINES = {
    "human": "Of course — let me bring a packaging specialist into the chat.",
    "complex": "Let me bring a packaging specialist in to cover the rest with you.",
    "max_turns": "Let me bring a packaging specialist in to help finish this with you.",
    "quote": "Thanks — I have everything I need. The team will email your quote with the pricing and next steps.",
    "stalled": "Let me bring a packaging specialist in to help with the rest of this.",
    "declined": "No problem — let me bring a packaging specialist in to help with the rest.",
}

REPHRASES = {
    "product": "Which product are you looking to have made: boxes, bags, labels or something else?",
    "sizes": "Could you share the size you need, in inches or cm?",
    "style": "Which style are you leaning toward for this order?",
    "finishes": "Which finish would you like: matte, gloss or soft touch?",
    "quantity": "Roughly how many units are you planning for the first run?",
    "skus": "How many separate designs are going on this order?",
    "material": "Is there a particular material or special feature you want included?",
    "extras": "Would you like a zipper or tear notch added?",
    "use_case": "What are you packing, or what is this order for?",
    "name": "Who am I speaking with?",
    "email": "Where should the quote go — which email works best?",
    "phone": "What number is best if the team needs to reach you?",
}

RULE_TEXT = """RULES FOR EVERY REPLY
1. Answer what they asked first, in the written words you were given, before asking anything.
2. One question per message. Never join two asks with "and".
3. Ask at most one new question, and only about a field in the ASK SET in the chat state. Never ask about anything in the DO NOT ASK SET, not even to confirm it.
4. Never give a price, a fee, a discount, a delivery date or a production date.
5. Never say you will check, confirm, verify, find out or get back to them. The quote covers it.
6. No markdown, bullets, headings or emoji. Plain chat text.
7. Keep it under about 45 words unless a written answer needs the room.
8. Use only the written answers and KB excerpts. Do not invent facts, sizes, materials or claims.
9. Do not call a product waterproof, food safe, durable or eco-friendly unless the excerpt says it.
10. Do not introduce yourself or greet again after the first message.
11. If they ask whether you are an AI, say you are an AI assistant helping the Print247 team.
12. For banners there is no minimum order. For everything else the standard minimum is 1,000 per size, or 500 each with multiple designs, and smaller runs are possible.
13. If the quantity they just gave is below the standard minimum, say smaller runs are possible and still ask the next question.
14. If they already gave a detail, do not ask for it again.
15. If they ask for a recommendation, or name what they are packing and ask what to use, name one specific option from the KB excerpts, give one short reason it fits, and say the team confirms the exact fit with the quote.
16. If they are unsure about size, explain there is no standard size — everything is custom made and sized around their product — then ask what they are packing.
17. If they ask which styles or options you offer, answer with those options from the written answers or KB, then ask one field from the ASK SET.
18. If they ask which product a question is about, name their product first (for example "For your stand-up bags"), then repeat the open question.
19. Return only the JSON object the schema asks for."""


@dataclass
class Composed:
    reply: str
    asked: str = ""
    fields: dict[str, str] = field(default_factory=dict)
    source: str = "heuristic"


def _topic_answer(key: str, family: str, overrides: dict[str, str] | None) -> str:
    if key == "moq" and family == "banners":
        return "Banners have no minimum — you can order any quantity."
    if key == "styles":
        if family == "bags":
            return "Bag styles include stand-up, flat, flat-bottom, side gusset and pinch bottom."
        if family == "boxes":
            return "Box styles include display, mailer, gift, kraft, square, cosmetic and apparel boxes."
    if key == "materials":
        if family == "bags":
            return "For bags and pouches we use PET, PE, kraft and foil films."
        if family == "labels":
            return "Our labels are printed on PP white vinyl."
        if family == "boxes":
            return "Our boxes are board, never film."
    return canon.effective_answer(key, overrides)


def _ack(state: ConversationState, visitor: str) -> str:
    last = state.last_question
    if last == "name" and state.fields["name"].value:
        return f"Thanks, {state.fields['name'].value.split()[0]}."
    if last == "email" and state.fields["email"].value:
        return "Got it, email noted."
    if last == "phone" and state.fields["phone"].value:
        return "Got it."
    if last == "product" and state.fields["product"].value:
        return "Got it."
    if last == "style" and state.fields["style"].value:
        return "Got it."
    if last in {"sizes", "quantity", "skus"} and state.fields[last].value:
        return "Got it."
    if normalize_finish(visitor):
        return "Got it."
    if re.fullmatch(r"\s*(?:yes|yeah|yep|sure|ok(?:ay)?|sounds good|no|nope|none|that'?s right)\s*[.!]*", visitor, re.I):
        return "Understood."
    return ""


def _question_text(state: ConversationState, expected: tuple[str, str] | None) -> str:
    if not expected:
        return ""
    key, base = expected
    if key == "sizes" and base.startswith("Is that in inches"):
        return base
    attempts = state.fields[key].attempts if key in state.fields else 0
    if attempts >= 1 and key in REPHRASES:
        return REPHRASES[key]
    return base


CLARIFY_FIELDS = {"sizes", "style", "finishes", "quantity", "skus", "material", "extras"}


def clarify_reply(state: ConversationState) -> str:
    """Answer "for what? bag or box?" with the product the question is about."""
    key = state.last_question
    if key not in CLARIFY_FIELDS or key not in state.fields or state.fields[key].done:
        return ""
    product = str(state.fields["product"].value or "").strip()
    if not product:
        return ""
    style = str(state.fields["style"].value or "").strip()
    target = f"your {style} {product}" if style and style != "no preference" else f"your {product}"
    question = state.question_for(key)
    if not question:
        return ""
    return f"For {target}. {question}"


def heuristic_turn(
    state: ConversationState,
    visitor: str,
    expected: tuple[str, str] | None,
    *,
    handoff_reason: str = "",
    overrides: dict[str, str] | None = None,
    unclear: bool = False,
) -> Composed:
    family = state.family()
    persona = persona_for(state.persona) or PERSONAS[0]
    parts: list[str] = []
    asked = ""

    if state.turn_count == 0:
        parts.append(f"Hi, I'm {persona.first}.")

    if asks_if_bot(visitor):
        parts.append("I'm an AI assistant helping the Print247 team.")

    topics = canon.detect_topics(visitor)
    if handoff_reason:
        topics = topics[:2]
    asked_family = family_of(visitor)
    for key in topics:
        answer_family = asked_family if key == "styles" and asked_family in {"bags", "boxes"} else family
        answer = _topic_answer(key, answer_family, overrides)
        if answer not in parts:
            parts.append(answer)

    if handoff_reason:
        parts.append(HANDOFF_LINES.get(handoff_reason, HANDOFF_LINES["stalled"]))
        return Composed(reply=" ".join(parts).strip(), asked="", source="heuristic")

    if (
        family == "boxes"
        and state.last_question == "style"
        and state.fields["style"].value == "no preference"
    ):
        parts.append("No problem — box styles include mailer, gift, kraft and display boxes.")

    if state.last_question == "quantity" and state.quantity_below_standard():
        answer = _topic_answer("moq", family, overrides)
        if answer not in parts:
            parts.append(answer)

    if size_is_unknown(visitor) and (
        state.last_question == "sizes" or re.search(r"\bsizes?\b", visitor, re.I)
    ):
        parts.append(
            "There's no standard size — everything is custom made, and the team "
            "sizes it around your product."
        )
        if expected and expected[0] != "sizes":
            parts.append(_question_text(state, expected))
            asked = expected[0]
        elif len(visitor.split()) <= 8:
            parts.append("What are you packing inside it?")
            asked = "sizes"
        return Composed(reply=" ".join(parts).strip(), asked=asked, source="heuristic")

    if is_job_pitch(visitor):
        parts.append("Thanks, but we're not looking for those services.")
        parts.append(_question_text(state, expected) or "What are you looking to have made?")
        return Composed(reply=" ".join(parts).strip(), asked=expected[0] if expected else "product", source="heuristic")

    if is_price_objection(visitor):
        parts.append("Understood — the quote is built around the quantity and specs you need.")

    if not topics:
        if state.last_question == "quantity" and state.quantity_below_standard():
            ack = ""
        else:
            ack = _ack(state, visitor)
        if ack:
            parts.append(ack)
        elif unclear:
            parts.append("I didn't quite catch that.")
        elif is_goodbye(visitor) and not state.specs_done():
            parts.append("Thanks for reaching out.")

    question = _question_text(state, expected)
    if (
        "styles" in topics
        and expected
        and expected[0] == "style"
        and asked_family in {"bags", "boxes"}
        and asked_family != family
    ):
        # They asked about another product's styles; the base question names
        # the product they are actually ordering, so it cannot be misread.
        question = expected[1]
    if question:
        parts.append(question)
        asked = expected[0] if expected else ""

    if not parts:
        parts.append("What are you looking to have made — boxes, bags, labels, or something else?")
        asked = "product"

    return Composed(reply=" ".join(parts).strip(), asked=asked, source="heuristic")


def _strip_signoff(text: str) -> str:
    return text.replace(" [needs sign-off: answer exactly as written]", "")


def kb_block(chunks) -> str:
    if not chunks:
        return "(no matching knowledge base excerpts)"
    lines = []
    for index, item in enumerate(chunks, start=1):
        chunk = getattr(item, "chunk", item)
        lines.append(
            f"[{index}] {chunk.title} — {chunk.section or 'general'} ({chunk.source or chunk.doc_id})\n{chunk.text}"
        )
    return "\n\n".join(lines)


# Some judged-correct chats used production facts that conflict with canon
# (e.g. the old "based in Houston" line); they must never be fed back as examples.
STALE_EXAMPLE_TOKENS = ("houston",)


def select_examples(examples: list[dict], family: str, limit: int = 3) -> list[dict]:
    safe = [
        item
        for item in examples
        if not any(token in str(item.get("reply", "")).lower() for token in STALE_EXAMPLE_TOKENS)
    ]
    same = [item for item in safe if item.get("family") == family]
    other = [item for item in safe if item.get("family") != family]
    same_count = min(len(same), max(0, limit - 1))
    picked = same[:same_count] + other[: limit - same_count]
    if len(picked) < limit:
        picked += same[same_count:][: limit - len(picked)]
    return picked[:limit]


def golden_block(examples: list[dict]) -> str:
    if not examples:
        return "(none)"
    lines = []
    for index, item in enumerate(examples, start=1):
        lines.append(
            f"Example {index}\nVisitor: {item.get('visitor', '')}\nReply: {item.get('reply', '')}"
        )
    return "\n\n".join(lines)


def build_system(
    state: ConversationState,
    chunks,
    *,
    overrides: dict[str, str] | None = None,
    examples: list[dict] | None = None,
) -> str:
    persona = persona_for(state.persona) or PERSONAS[0]
    return "\n\n".join(
        [
            f"You are {persona.name}, a sales rep on the Print247 website chat. "
            f"Your tone is {persona.tone}. You are one of nine people answering chats in rotation.",
            RULE_TEXT,
            "WRITTEN ANSWERS — use these words, do not invent alternatives:\n"
            + _strip_signoff(canon.facts_for_prompt()),
            "VERIFIED KB EXCERPTS for this turn:\n" + kb_block(chunks),
            "EXAMPLES OF CORRECT REPLIES from past chats:\n" + golden_block(examples or []),
        ]
    )


def build_user(
    state: ConversationState,
    visitor: str,
    _expected: tuple[str, str] | None,
    *,
    asked_if_bot: bool = False,
) -> str:
    # `_expected` is the fake-mode sentence for this turn. It is not injected.
    # The ASK SET below is the constraint, and the model chooses within it.
    transcript = "\n".join(
        f"{'Bot' if message.author == 'ai' else 'Visitor'}: {message.text}"
        for message in state.messages[-10:]
        if message.author != "system"
    )
    topics = canon.detect_topics(visitor)
    lines = [
        f"CHAT STATE\n{state.summary()}",
        f"\nTRANSCRIPT (last messages)\n{transcript}",
        f"\nTheir latest message: {visitor}",
        f"Topics their message asks about: {', '.join(topics) if topics else 'none recognised'}",
        (
            "They are asking for a recommendation: name one specific option from the KB excerpts, "
            "say in one short clause why it fits, then ask one field from the ASK SET."
            if wants_recommendation(visitor)
            else ""
        ),
        "ASK SET CONSTRAINT — binding. Ask at most one new question, and only about a field "
        "listed after 'You may ask about'. Anything listed after 'Do not ask about' is off "
        "limits, even as a confirmation.\n"
        + state.ask_constraint(),
        (
            "They asked whether you are a bot: answer honestly and briefly, then continue."
            if asked_if_bot
            else ""
        ),
        "\nWrite the next message as JSON. In `fields`, repeat only details the visitor stated in this chat, exactly as they stated them; leave everything else empty.",
    ]
    return "\n".join(line for line in lines if line != "")


def live_turn(
    client: LLMClient,
    state: ConversationState,
    visitor: str,
    expected: tuple[str, str] | None,
    chunks,
    *,
    overrides: dict[str, str] | None = None,
    examples: list[dict] | None = None,
    asked_if_bot: bool = False,
    correction: str = "",
) -> Composed:
    system = build_system(state, chunks, overrides=overrides, examples=examples)
    user = build_user(state, visitor, expected, asked_if_bot=asked_if_bot)
    if correction:
        user = f"{user}\n\nCORRECTION FROM THE VERIFIER — fix these and rewrite:\n{correction}"
    parsed = client.complete_json(system, user, REPLY_SCHEMA)
    reply = str(parsed.get("reply") or "").strip()
    asked = str(parsed.get("asked") or "").strip()
    fields = {str(key): str(value) for key, value in (parsed.get("fields") or {}).items() if value}
    return Composed(reply=reply, asked=asked, fields=fields, source="live")
