from __future__ import annotations

import re
from dataclasses import dataclass, field

from . import canon
from .llm import LLMClient, REPLY_SCHEMA
from .personas import PERSONAS, persona_for
from .state import (
    ConversationState,
    asks_if_bot,
    asks_to_share_reference,
    continue_ask,
    family_of,
    is_goodbye,
    is_job_pitch,
    is_meta_question,
    CATALOGUE_OPTION_FIELDS,
    is_option_request,
    refuses_contact,
    is_price_objection,
    is_question,
    is_visitor_greeting,
    normalize_finish,
    size_is_unknown,
    valid_email,
    wants_recommendation,
)

SINGLE_QUESTION_RULE = (
    "You MUST ask ONLY ONE single question per message about ONLY ONE checklist field. "
    "NEVER combine fields in one sentence (forbidden: size and quantity together, "
    "style and finish together, material and SKUs together). Pick the highest-priority "
    "missing field from the ASK SET and ask only about that."
)

HANDOFF_LINES = {
    "human": "Of course — let me bring a packaging specialist into the chat.",
    "complex": "Let me bring a packaging specialist in to cover the rest with you.",
    "max_turns": "Let me bring a packaging specialist in to help finish this with you.",
    "quote": "Thanks — I have everything I need. The team will email your quote with the pricing and next steps.",
    "stalled": "Let me bring a packaging specialist in to help with the rest of this.",
    "declined": "No problem — let me bring a packaging specialist in to help with the rest.",
}

# Conversational finish set for custom boxes — do not volunteer other primer finishes.
BOX_PRIMARY_FINISHES = (
    "matte lamination",
    "gloss lamination",
    "soft touch lamination",
    "spot UV",
    "foil printing",
)
BOX_PRIMARY_FINISHES_TEXT = (
    "matte lamination, gloss lamination, soft touch lamination, spot UV, and foil printing"
)

REPHRASES = {
    "product": "Which product are you looking to have made: boxes, bags, labels or something else?",
    "sizes": "Could you share the size you need — for example 3x6 ft, or in inches?",
    "style": "Which style are you leaning toward for this order?",
    "finishes": (
        "Which finish would you like: matte lamination, gloss lamination, "
        "soft touch lamination, spot UV, or foil printing?"
    ),
    "quantity": "Roughly how many units are you planning for the first run?",
    "skus": "How many separate designs are going on this order?",
    "material": "Is there a particular material or special feature you want included?",
    "extras": "Would you like a zipper or tear notch added?",
    "use_case": "What are you packing, or what is this order for?",
    "name": "Who am I speaking with?",
    "email": "I can send the quote by email when we're done — what address should we use?",
    "phone": "What number is best if the team needs to reach you?",
}

RULE_TEXT = f"""{SINGLE_QUESTION_RULE}

You decide what to do next. You may: answer what they asked; ask the one thing that most blocks
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
environmental claim. Those come only from the FACTS block, word for word. Do not use these words
as a claim, even as a feeling or a benefit: eco-friendly, biodegradable, compostable, recyclable,
food safe, waterproof, FDA, BPA, certified. Repeating a catalogue style name that contains one of
those words is allowed. Saying the product has that property is not. Contact details: offer only
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

If you are asking for contact details, shipping info, or how many designs they have, focus ONLY on that ask. Do NOT re-assert or re-emit proposed_configs for styles/materials/finishes that were discussed in previous turns unless you are actively presenting a new recommendation. When that field is open, ask about designs in plain language (for example "How many total designs do you have?"). Never say "SKU" or "SKUs" to the visitor — they may not know that word.

If the user is just saying hello, asking off-topic questions, or providing impossible specs (like a size with any zero dimension: 0x0, 0x15, 10x0x5, or 0), answer naturally using your own reasoning. In these cases, you MUST leave proposed_configs completely EMPTY. End with the one allowed question so the conversation comes back to the order.

Do not open a later message with Good Morning or Hello on your own. If they just said good morning or hello, answer that greeting in a few words, then ask the one open question. A greeting is not their product.

When a user asks for examples, options, or suggestions (including "give me options", "show me options", "what do you have"), answer the OPEN ASK SET field first. If Material is open, list the family's material options from FACTS / CATALOGUE (for labels: PP white vinyl is the standard — say that and ask whether to proceed). If Style is open, list styles. If Finish is open, list finishes for this family only. Do not stall, do not jump to designs/email, and do not mix finish names into a material answer. Emit proposed_configs only for options you actually name. NEVER invent names that are not in the primer.

When listing finish options for custom boxes, use ONLY these official box finishes: matte lamination, gloss lamination, soft touch lamination, spot UV, and foil printing. Do not volunteer drip off, embossing, varnish, AQ coating, or finishes that belong to bags, pouches, or labels. If the visitor already named another boxes-primer finish by name, you may confirm it; otherwise stay inside that official list.

If the user asks for alternative materials when only one standard material exists for a product family (for example PP white vinyl for labels, as stated in FACTS), politely explain that this product specifically uses our standard high-grade material for best results, and ask if they would like to proceed with it. Reason in your own words from FACTS and the CATALOGUE PRIMER — do not invent a second stock, do not emit a fake style such as N/A, do not restate locked finishes in proposed_configs, do not crash into a fallback pattern, and NEVER jump to asking for an email on that turn. Leave proposed_configs empty, or name only that single standard material.

Stay inside the active product family from the GOAL. If the order is labels, never mention bag or box styles or materials. If it is boxes, never mention bag or label details. Recommendations and catalogue lists use only that family's vocabulary.

After Product and Use Case are known, ask ONCE for their email (soft ask for the quote) before size/quantity/style. If they give it, save it and continue. If they skip, refuse, or answer a product field instead, continue size and the rest — do not stall on email. Phone waits until product details are done. Re-ask email only when the quote is ready if it is still empty. Never jump to phone or handoff while Material, Finish, Designs, or other open product-spec fields are unresolved after the soft email turn.

Once a style or finish is accepted, it is locked. Do not ask for it again, and do not put it in fields_proposed or proposed_configs.

When the visitor is unsure, undecided, deferring, or asking you/the team to decide later about the
open checklist field — judge that from their meaning, not from a fixed phrase list — set that one
field in `fields` to exactly "to be confirmed", acknowledge briefly that the team will confirm it,
and ask the next ASK SET field. Never re-ask the same field on that turn. Use "to be confirmed"
only for sizes, style, finishes, material, designs, extras, use case, or quantity — never for
product, email, phone, or name.

When they ask how to reach you, the first sentence must be exactly: "You can reach the team at Support@print247.us or +1 (832) 807-3429." Then ask the next missing checklist field in the same message.

If they say they do not have an email, refuse to share one, or otherwise decline contact details, treat that as a waiver: acknowledge it, you may share the support contact from FACTS once, do not ask for their email or phone again, and do not trap them in an email loop.

If they give an email that is malformed or incomplete (missing @, missing domain, or otherwise not a real address), tell them that email does not look right and ask again for a valid email. Do not store it and do not move on to phone or handoff.

Never ask about something they already told you. You may only ask about fields in the ASK SET;
anything in the DO NOT ASK SET is off limits even as a confirmation.

Reference images: when they ask if they can add, attach, upload, or share a reference image,
answer YES in the first sentence and invite them to use the chat attach control. Do not ignore
that ask and do not only repeat the previous checklist question. After the invite, you may briefly
keep the one open ASK SET question.

When a reference image is already on this turn (GOAL says they shared one, or their message is
"[shared a reference image]"), never silently accept it and never ignore it. Correlate what is
visible STRICTLY with the highest-priority open ASK SET field only: size → look for printed
dimensions only if clearly readable (never invent sizes); style → construction/shape using
exact catalogue style names for this family; finish → sheen/texture using exact catalogue
finish names for this family (for boxes: matte lamination, gloss lamination, soft touch
lamination, spot UV, foil printing); material → substrate using catalogue material names.
Ask them conversationally before locking anything, for example: "I see the reference image you
shared! It looks like a [catalogue term for the open field]. Should I use this for your order?"
— that is one yes/no question, not a promise to check later. If the open detail is not clearly
readable, say so politely and ask them to clarify that one field — do not ignore the image, and
leave proposed_configs empty unless you are naming a visible catalogue option for them to accept.

NEVER append, quote, or paraphrase the standard MOQ sentence. For banners there is no minimum
order. For everything else the standard minimum is 1,000 per size, or 500 each with multiple
designs, and smaller runs are possible. State that minimum ONLY when they explicitly ask what
the minimum or MOQ is, in words like "what is your minimum" or "do you have an MOQ". If they
just give a quantity such as 300, accept that number and do not mention the minimum, the MOQ,
1,000, or smaller runs at all.

Style: plain chat text, no markdown, no emoji, roughly 25-60 words. Return only the JSON object
the schema asks for. The ASK SET is the only list of questions."""


@dataclass
class Composed:
    reply: str
    asked: str = ""
    fields: dict[str, str] = field(default_factory=dict)
    source: str = "heuristic"
    move: str = ""
    # None means this reply was not a model emit. An empty list means the model
    # chose not to name a configuration (a greeting, an aside, a correction).
    proposed_configs: list | None = None
    fields_proposed: list = field(default_factory=list)
    bases: dict[str, str] = field(default_factory=dict)


def _topic_answer(key: str, family: str, overrides: dict[str, str] | None) -> str:
    """Family-scoped catalogue lines for fallbacks and option requests.

    When the goal already has a product family, never leak another family's
    styles or materials into the reply.
    """
    if key == "moq" and family == "banners":
        return "Banners have no minimum — you can order any quantity."
    if key == "styles":
        scoped = {
            "bags": "Bag styles include stand-up, flat, flat-bottom, side gusset and pinch bottom.",
            "boxes": "Box styles include display, mailer, gift and kraft boxes.",
            "labels": (
                "Label styles include bottle labels, product labels, die-cut stickers "
                "and vinyl labels."
            ),
            "banners": (
                "Banner styles include vinyl banners, pull-up banners, flags and window decals."
            ),
            "business_cards": (
                "Business card styles include standard, folded, foil accent and matte cards."
            ),
            "print": "Print styles include flyers, brochures, posters, booklets and postcards.",
        }
        if family in scoped:
            return scoped[family]
        if family != "unknown":
            return ""
    if key == "materials":
        scoped = {
            "bags": "For bags and pouches we use PET, PE, kraft and foil films.",
            "labels": (
                "For labels we use PP white vinyl as the standard stock "
                "for best print results."
            ),
            "boxes": "Our boxes are board, never film.",
            "banners": "Banners use vinyl, polyester, foamcore or corrugated plastic.",
            "business_cards": (
                "Business cards use cardstock and specialty stocks such as kraft or acrylic."
            ),
            "print": "Print products use cardstock and gloss or uncoated paper stocks.",
        }
        if family in scoped:
            return scoped[family]
        if family != "unknown":
            return ""
    if key == "finishes":
        scoped = {
            "boxes": (
                "For custom boxes, finishes include "
                f"{BOX_PRIMARY_FINISHES_TEXT}."
            ),
            "bags": (
                "Bag and pouch finishes include matte, gloss, soft touch, spot UV "
                "and foil printing."
            ),
            "labels": (
                "Label finishes include matte, gloss, soft touch, spot UV and foil printing."
            ),
        }
        if family in scoped:
            return scoped[family]
        if family != "unknown":
            return (
                "Finishes include matte lamination, gloss lamination, soft touch "
                "lamination, spot UV and foil printing."
            )
    # Multi-family canon lines are only for early turns before a family is known.
    return canon.effective_answer(key, overrides)


def disclosure_line(persona_name: str) -> str:
    """D-1, one sentence: an AI assistant under this persona, then back to the order."""
    persona = persona_for(persona_name) or PERSONAS[0]
    return f"I'm an AI assistant working under the name {persona.first} for Print247."


def _ack(state: ConversationState, visitor: str) -> str:
    last = state.last_question
    if last == "name" and state.fields["name"].value:
        return f"Thanks, {state.fields['name'].value.split()[0]}."
    if last == "email" and valid_email(state.fields["email"].value):
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
    if key == "sizes" and state.size_needs_unit():
        return state.question_for("sizes")
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

    if is_visitor_greeting(visitor):
        question = _question_text(state, expected) or "What are you looking to have made — boxes, bags, labels, or something else?"
        return Composed(
            reply=question,
            asked=expected[0] if expected else "product",
            source="heuristic",
        )

    if asks_to_share_reference(visitor):
        parts.append(
            "Yes — please attach your reference image with the attach control in the chat. "
            "When it arrives, we can match the visible details to your order together."
        )
        # Keep the same open question already on the table (do not jump fields).
        focused = continue_ask(state) or expected
        question = _question_text(state, focused)
        if question:
            parts.append(question)
            asked = focused[0] if focused else ""
        return Composed(reply=" ".join(parts).strip(), asked=asked, source="heuristic")

    topics = canon.topics_to_answer(visitor)
    if handoff_reason == "quote":
        # Closing the quote is not a request for the facility or the public phone line.
        topics = [
            key
            for key in topics
            if key not in {"contact", "location"}
            or (key == "contact" and canon.asks_for_our_contact(visitor))
            or (key == "location" and canon.asks_for_location(visitor))
        ]
    if handoff_reason:
        topics = topics[:2]
    asked_family = family_of(visitor)
    for key in topics:
        # Only switch family for an explicit styles ask about bags/boxes. Never
        # dump bag/box styles while the order is labels (or any other family).
        if key == "styles" and asked_family in {"bags", "boxes"} and (
            family in {"unknown", asked_family}
        ):
            answer_family = asked_family
        else:
            answer_family = family
        answer = _topic_answer(key, answer_family, overrides)
        if answer and answer not in parts:
            parts.append(answer)

    if handoff_reason:
        parts.append(HANDOFF_LINES.get(handoff_reason, HANDOFF_LINES["stalled"]))
        return Composed(reply=" ".join(parts).strip(), asked="", source="heuristic")

    style_suggest = (
        "styles" in topics
        or wants_recommendation(visitor)
        and re.search(r"\bstyles?\b", visitor, re.I)
    )
    finish_suggest = (
        wants_recommendation(visitor) or is_option_request(visitor)
    ) and re.search(r"\bfinishes?\b", visitor, re.I)
    # Dynamic: open catalogue field + no concrete pick (any wording, not just
    # "give me options") → show that field's menu.
    offer_for = str(state.flags.get("offer_options_for") or "").strip()
    if offer_for not in CATALOGUE_OPTION_FIELDS:
        offer_for = ""

    if (
        offer_for
        or is_option_request(visitor)
        or style_suggest
        or finish_suggest
    ):
        asked_key = offer_for or state.last_question
        catalogue = ""
        if (
            asked_key == "material"
            or "materials" in topics
        ) and not style_suggest and not finish_suggest:
            catalogue = _topic_answer("materials", family, overrides)
        elif asked_key == "quantity" and not style_suggest and not finish_suggest:
            catalogue = ""
        elif asked_key == "finishes" or finish_suggest:
            catalogue = _topic_answer(
                "finishes", family if family != "unknown" else "boxes", overrides
            )
        elif asked_key == "style" or style_suggest or "styles" in topics:
            catalogue = _topic_answer(
                "styles", family if family != "unknown" else "boxes", overrides
            )
        elif family != "unknown":
            catalogue = _topic_answer("styles", family, overrides)
        else:
            catalogue = _topic_answer("styles", "boxes", overrides)
        if catalogue and catalogue not in parts:
            parts.append(catalogue)
        if (
            catalogue
            and asked_key in CATALOGUE_OPTION_FIELDS
            and (not expected or expected[0] != asked_key)
        ):
            expected = (asked_key, state.question_for(asked_key) or "")
        if catalogue and asked_key == "material" and family == "labels":
            parts.append("Would you like to proceed with PP white vinyl?")
            return Composed(reply=" ".join(parts).strip(), asked="material", source="heuristic")
        if catalogue and asked_key == "style":
            follow = state.question_for("style") or "Which of those styles do you want?"
            parts.append(follow)
            return Composed(reply=" ".join(parts).strip(), asked="style", source="heuristic")
        if catalogue and asked_key == "finishes":
            follow = state.question_for("finishes") or "Which finish do you prefer?"
            parts.append(follow)
            return Composed(reply=" ".join(parts).strip(), asked="finishes", source="heuristic")

    if (
        family == "boxes"
        and state.last_question == "style"
        and state.fields["style"].value == "no preference"
    ):
        parts.append("No problem — box styles include mailer, gift, kraft and display boxes.")

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
    if asks_to_share_reference(visitor):
        return "reference_share"
    if refuses_contact(visitor):
        return "refusal"
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
            SINGLE_QUESTION_RULE,
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


def _candidate_block(registry, state: ConversationState, chunks) -> str:
    """D-11. Boxes and bags may be named only from the retrieved offering rows."""
    if registry is None:
        return ""
    family = state.family()
    rows = registry.candidate_offerings(family, chunks)
    if not rows:
        return ""
    lines = [
        "CANDIDATE SET — hard filter. This family is boxes or bags, so a recommendation "
        "may use only a style, material, finish, insert, or extra from the rows below. "
        "Do not invent a gauge, a point size, or a name that is not on one of these rows.",
    ]
    if family == "boxes":
        lines.append(
            "BOX FINISH LISTING — when you list finish options in the reply, use only: "
            f"{BOX_PRIMARY_FINISHES_TEXT}. Other finish names on the rows stay available "
            "only if the visitor already asked for that finish by name."
        )
    for row in rows:
        parts = []
        if row.styles:
            parts.append("style: " + "; ".join(row.styles))
        if row.materials:
            parts.append("material: " + "; ".join(row.materials))
        if row.finishes:
            finishes = row.finishes
            if family == "boxes":
                primary = {
                    f.casefold() for f in BOX_PRIMARY_FINISHES
                }
                preferred = tuple(
                    f for f in finishes if f.casefold() in primary
                )
                finishes = preferred or BOX_PRIMARY_FINISHES
            parts.append("finish: " + "; ".join(finishes))
        if row.inserts:
            parts.append("insert: " + "; ".join(row.inserts))
        if row.extras:
            parts.append("extra: " + "; ".join(row.extras))
        if parts:
            lines.append("- " + " | ".join(parts))
    return "\n".join(lines)


def build_user(
    state: ConversationState,
    visitor: str,
    _expected: tuple[str, str] | None,
    *,
    asked_if_bot: bool = False,
    chunks=(),
    examples: list[dict] | None = None,
    registry=None,
) -> str:
    # `_expected` is the fake-mode sentence for this turn. It is not injected.
    # The ASK SET below is the constraint, and the model chooses within it.
    transcript = "\n".join(
        f"{'Bot' if message.author == 'ai' else 'Visitor'}: {message.text}"
        for message in state.messages[-10:]
        if message.author != "system"
    )
    topics = canon.topics_to_answer(visitor)
    lines = [
        f"GOAL\n{state.summary()}",
        "ASK SET CONSTRAINT — binding. "
        + SINGLE_QUESTION_RULE
        + " Ask only about the highest priority field listed after 'You may ask about'. "
        "Anything listed after 'Do not ask about' is off limits, even as a confirmation.\n"
        + state.ask_constraint(),
        "FACTS — Tier B, verbatim. offerable: true may be volunteered; "
        "offerable: false only when they asked.\n"
        + _strip_signoff(canon.facts_for_prompt()),
        "FAMILY DETAIL\n" + kb_block(chunks),
        _candidate_block(registry, state, chunks),
        "EXAMPLES OF CORRECT REPLIES\n" + golden_block(examples or []),
        f"TRANSCRIPT (last messages)\n{transcript}",
        f"Their latest message: {visitor}",
        f"Intent: {_intent(visitor)}",
        f"Topics their message asks about: {', '.join(topics) if topics else 'none recognised'}",
        (
            ""
            if canon.asks_for_minimum(visitor)
            else "They did not ask what the minimum is. Do not mention MOQ, minimum, "
            "1,000 per size, or smaller runs."
        ),
        (
            "GOAL flag offer_options_for / open Style with no concrete pick: list ONLY exact "
            "styles from CATALOGUE PRIMER / FAMILY DETAIL for the ACTIVE family. Emit "
            "proposed_configs for each named style. Do not invent names, do not store their "
            "message as the style, ask which style they want (asked=style). No finish/SKU/email."
            if (
                str(state.flags.get("offer_options_for") or "") == "style"
                or (
                    (is_option_request(visitor) or "styles" in topics)
                    and state.last_question == "style"
                )
            )
            else ""
        ),
        (
            "GOAL flag offer_options_for=material / open Material with no concrete pick: list "
            "family materials from FACTS (labels → PP white vinyl standard). Ask whether to "
            "proceed, keep proposed_configs empty or that material only, asked=material. "
            "No finishes, designs, or email on this turn."
            if (
                str(state.flags.get("offer_options_for") or "") == "material"
                or (
                    state.last_question == "material"
                    and (is_option_request(visitor) or "materials" in topics or wants_recommendation(visitor))
                )
                or ("materials" in topics and (wants_recommendation(visitor) or is_option_request(visitor)))
            )
            else ""
        ),
        (
            "GOAL flag offer_options_for=finishes / open Finish with no concrete pick: list ONLY "
            "this family's finishes from FACTS / CATALOGUE. Emit proposed_configs, asked=finishes."
            if (
                str(state.flags.get("offer_options_for") or "") == "finishes"
                or (
                    state.last_question == "finishes"
                    and (is_option_request(visitor) or wants_recommendation(visitor)
                         or re.search(r"\bfinishes?\b", visitor, re.I))
                )
            )
            else ""
        ),
        (
            "They asked about finishes or finish options. For custom boxes, list ONLY: "
            f"{BOX_PRIMARY_FINISHES_TEXT}. Do not mention drip off or finishes from other "
            "product families. Emit proposed_configs using those exact finish strings, then ask "
            "one ASK SET field."
            if (
                re.search(r"\bfinishes?\b", visitor, re.I)
                and (wants_recommendation(visitor) or is_option_request(visitor)
                     or state.last_question == "finishes")
                and state.family() in {"boxes", "unknown"}
            )
            else ""
        ),
        (
            "They asked how to reach you. The first sentence must be exactly: "
            '"You can reach the team at Support@print247.us or +1 (832) 807-3429." '
            "Then ask the single highest-priority field still in the ASK SET. "
            "After the one soft email ask, do not re-ask email while Designs, Material, or "
            "Finish are still open — continue those fields. Ask designs in plain language; "
            "never say SKU to the visitor."
            if canon.asks_for_our_contact(visitor)
            else ""
        ),
        (
            "They declined to share their email/phone. Acknowledge that, do not ask for their "
            "email or phone again, and do not hand off just because they refused. If they also "
            "asked for OUR contact or address, answer those from FACTS (support email/phone and "
            "Rosenberg when they asked for the address), then continue with one ASK SET field."
            if refuses_contact(visitor)
            else ""
        ),
        (
            "They are asking for a recommendation: name one specific option from the catalogue, "
            "say in one short clause why it fits, then ask one field from the ASK SET."
            if (
                wants_recommendation(visitor)
                and "materials" not in topics
                and "styles" not in topics
                and not re.search(r"\b(?:styles?|finishes?)\b", visitor, re.I)
            )
            else ""
        ),
        (
            "They asked whether you are a bot: use the one disclosure sentence, then continue "
            "with what they were asking about."
            if asked_if_bot
            else ""
        ),
        (
            "They asked if they can add/attach/upload a reference image. First sentence: yes, "
            "invite them to use the chat attach control. Then repeat the SAME open question already "
            "on the table (the last checklist ask), not a different field. Do not ignore their "
            "image ask. Leave proposed_configs empty."
            if asks_to_share_reference(visitor)
            else ""
        ),
        (
            "They shared a reference image this turn. Acknowledge it warmly, correlate visible "
            "cues with the top open ASK SET field, and ask one confirmation or clarification "
            "question. Never invent dimensions. If the open detail is unclear in the image, say "
            "so and ask them to clarify that field."
            if (
                "[shared a reference image]" in visitor.lower()
                or bool(state.flags.get("reference_image_this_turn"))
            )
            else ""
        ),
        "Write the next message as JSON. `proposed_configs` has one object per option the reply "
        "names, and is completely empty when you are only saying hello, answering something "
        "off-topic, or correcting an impossible spec such as a zero dimension. Copy style, "
        "material, finish, insert and extras character for character from the "
        "CATALOGUE PRIMER; leave a field empty when the reply does not name it. Do not invent a "
        "point size, a gauge, or a style name. If the visitor is unsure about the open ASK SET "
        "field (any wording), put exactly \"to be confirmed\" in `fields` for that field, do not "
        "re-ask it, and ask the next ASK SET field. If you are asking for contact details, shipping "
        "info, or how many designs they have, focus ONLY on that ask. Never say SKU to the visitor. "
        "Do NOT re-assert or re-emit "
        "proposed_configs for styles/materials/finishes that were discussed in previous turns "
        "unless you are actively presenting a new recommendation. `fields_proposed` repeats only "
        "details the visitor stated, or a catalogue size, each with its basis. Leave everything else empty.",
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
        registry=registry,
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
