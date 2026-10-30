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
    is_meta_question,
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

RULE_TEXT = """You decide what to do next. You may: answer what they asked; ask the one thing that most blocks
their quote; propose a specific option and ask them to confirm it; or offer the contact details the
FACTS block marks as offerable so the conversation can move forward.

You know packaging. Use that knowledge. When a customer tells you what they are packing, work out
what that product needs — protection, presentation, how it will be shipped and handled — and say what
you would make for it and why, in plain words.

Your judgement decides which of our options fits. It never decides what we offer. The option
list comes from the CATALOGUE PRIMER and the catalogue chunks in this message and nowhere else: not
from the wider internet, not from packaging generally, not from what other companies do. Choose among
the styles, materials, gauges, finishes and inserts listed there, and honour its combination rules. If
an idea is not listed, do not present it as something we make: describe the need, offer the closest
listed option, and say the team will confirm the build.

NEVER state, estimate or imply: a price, a fee, a discount, a minimum order number, a production
or delivery date, a shipping time, payment terms, a refund promise, or any safety, food-contact or
environmental claim. Those come only from the FACTS block, word for word. Contact details: offer only
what the FACTS block marks offerable (phone, support email); state the address or hours only if asked.
Everything else about packaging is yours to discuss.

Sizes: you do not work out sizes. If asked for one, say the right size depends on the product's own
dimensions, its shape and how it has to be packed; ask them for those measurements so you can point
them at the right style; say the packaging team confirms the final size. You may name a size only when
it is printed in our CATALOGUE or when the customer gave it to you — and a catalogue size is never
presented as a guaranteed fit for their product. Do not do dimension arithmetic, do not offer a
"typical" size, do not say "usually" or "most people take", and do not say internal or external unless
the catalogue row itself says which.

When you answer, mark where it came from: FACTS, CATALOGUE, YOUR_JUDGEMENT, or THEM.

Never ask about something they already told you. You may only ask about fields in the ASK SET;
anything in the DO NOT ASK SET is off limits even as a confirmation.

For banners there is no minimum order. For everything else the standard minimum is 1,000 per size,
or 500 each with multiple designs, and smaller runs are possible. If they already gave a quantity
below that, say smaller runs are possible and still ask one field from the ASK SET.

Style: plain chat text, no markdown, no emoji, roughly 25-60 words, at most one new question per
message. Return only the JSON object the schema asks for. The ASK SET is the only list of questions."""


@dataclass
class Composed:
    reply: str
    asked: str = ""
    fields: dict[str, str] = field(default_factory=dict)
    source: str = "heuristic"
    move: str = ""
    # None means this reply was not a model emit. An empty list means the model
    # named no configuration, which the registry guards are allowed to reject.
    proposed_configs: list | None = None
    fields_proposed: list = field(default_factory=list)
    bases: dict[str, str] = field(default_factory=dict)


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


def disclosure_line(persona_name: str) -> str:
    """D-1, one sentence: an AI assistant under this persona, then back to the order."""
    persona = persona_for(persona_name) or PERSONAS[0]
    return f"I'm an AI assistant working under the name {persona.first} for Print247."


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

    # Identity is a fixed route. The word "ai" must not pull the artwork answer
    # ("AI, PDF, EPS..."), which is what the Ethan transcript lectured about.
    if asks_if_bot(visitor):
        parts.append(disclosure_line(state.persona))
        question = _question_text(state, expected)
        if question:
            parts.append(question)
            asked = expected[0] if expected else ""
        return Composed(reply=" ".join(parts).strip(), asked=asked, source="heuristic")

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


def _allowlist_block(registry) -> str:
    if registry is None:
        return "COMPLIANCE ALLOW-LIST\n(not loaded)"
    lines = ["COMPLIANCE ALLOW-LIST — these sentences only, verbatim:"]
    for claim in registry.claims:
        lines.append(f"- ({claim.family}) {claim.say}")
    if registry.bans:
        lines.append("NEVER assert: " + "; ".join(ban.claim for ban in registry.bans))
    return "\n".join(lines)


def _intent(visitor: str) -> str:
    if asks_if_bot(visitor):
        return "identity"
    if is_meta_question(visitor):
        return "meta"
    if wants_recommendation(visitor):
        return "recommendation"
    if is_question(visitor):
        return "question"
    return "order"


def build_system(state: ConversationState, registry=None) -> str:
    """Cacheable prefix. Identical for every turn of one persona: no transcript, no ask-set."""
    persona = persona_for(state.persona) or PERSONAS[0]
    disclosure = disclosure_line(persona.name)
    identity = (
        f"Identity (approved policy, D-1 = option B): you are {persona.name} and you stay that "
        "person for the whole chat — same name, same tone, from greeting to handoff. Never "
        "volunteer that you are an AI, and never raise the subject yourself. If the customer asks "
        "directly, answer honestly in one plain sentence: you are an AI assistant working under "
        f"this name for Print247. The sentence is exactly: \"{disclosure}\" Never claim to be a "
        "human and never deny being one. After that sentence, continue with whatever they were "
        "actually asking about — the disclosure is one line, not a lecture."
    )
    primer = registry.render_primer() if registry is not None else "CATALOGUE PRIMER\n(not loaded)"
    return "\n\n".join(
        [
            f"You are {persona.name}. You work at Print247, a custom packaging and printing company "
            f"in Rosenberg, Texas. You are chatting with a customer on their website. Your tone is "
            f"{persona.tone}. Your job is to understand what they need well enough that the quoting "
            "team can send an accurate price, and to make that conversation feel like a knowledgeable "
            "shopkeeper helping them, not a form.",
            identity,
            RULE_TEXT,
            primer,
            _allowlist_block(registry),
        ]
    )


def build_user(
    state: ConversationState,
    visitor: str,
    _expected: tuple[str, str] | None,
    *,
    asked_if_bot: bool = False,
    chunks=(),
    examples: list[dict] | None = None,
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
        f"GOAL\n{state.summary()}",
        "ASK SET CONSTRAINT — binding. Ask at most one new question, and only about a field "
        "listed after 'You may ask about'. Anything listed after 'Do not ask about' is off "
        "limits, even as a confirmation.\n"
        + state.ask_constraint(),
        "FACTS — Tier B, verbatim. offerable: true may be volunteered; "
        "offerable: false only when they asked.\n"
        + _strip_signoff(canon.facts_for_prompt()),
        "FAMILY DETAIL\n" + kb_block(chunks),
        "EXAMPLES OF CORRECT REPLIES\n" + golden_block(examples or []),
        f"TRANSCRIPT (last messages)\n{transcript}",
        f"Their latest message: {visitor}",
        f"Intent: {_intent(visitor)}",
        f"Topics their message asks about: {', '.join(topics) if topics else 'none recognised'}",
        (
            "They are asking for a recommendation: name one specific option from the catalogue, "
            "say in one short clause why it fits, then ask one field from the ASK SET."
            if wants_recommendation(visitor)
            else ""
        ),
        (
            "They asked whether you are a bot: use the one disclosure sentence, then continue "
            "with what they were asking about."
            if asked_if_bot
            else ""
        ),
        "Write the next message as JSON. `proposed_configs` has one object per option the reply "
        "names. `fields_proposed` repeats only details the visitor stated, or a catalogue size, "
        "each with its basis. Leave everything else empty.",
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
    registry=None,
) -> Composed:
    # Canon overrides are already inside the FACTS block the orchestrator loads.
    _ = overrides
    system = build_system(state, registry)
    user = build_user(
        state,
        visitor,
        expected,
        asked_if_bot=asked_if_bot,
        chunks=chunks,
        examples=examples,
    )
    if correction:
        user = f"{user}\n\nCORRECTION FROM THE VERIFIER — fix these and rewrite:\n{correction}"
    parsed = client.complete_json(system, user, REPLY_SCHEMA)
    reply = str(parsed.get("reply") or "").strip()
    asked = str(parsed.get("asked") or "").strip()
    move = str(parsed.get("move") or "").strip()
    fields = {str(key): str(value) for key, value in (parsed.get("fields") or {}).items() if value}
    proposed = parsed.get("fields_proposed") if isinstance(parsed.get("fields_proposed"), list) else []
    bases: dict[str, str] = {}
    for item in proposed:
        if not isinstance(item, dict):
            continue
        key = str(item.get("key") or "").strip()
        value = str(item.get("value") or "").strip()
        if key and value and key not in fields:
            fields[key] = value
        if key:
            bases[key] = str(item.get("basis") or "")
    configs = parsed.get("proposed_configs")
    if not isinstance(configs, list):
        configs = []
    return Composed(
        reply=reply,
        asked=asked,
        fields=fields,
        source="live",
        move=move,
        proposed_configs=configs,
        fields_proposed=[item for item in proposed if isinstance(item, dict)],
        bases=bases,
    )
