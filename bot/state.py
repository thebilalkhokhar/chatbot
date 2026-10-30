from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

FAMILIES = ("bags", "boxes", "labels", "banners", "business_cards", "print", "unknown")

FAMILY_PRODUCT = {
    "bags": "bags",
    "boxes": "boxes",
    "labels": "labels",
    "banners": "banners",
    "business_cards": "business cards",
    "print": "print products",
}

FIELD_LABELS = {
    "product": "Product",
    "use_case": "What it is for",
    "style": "Style",
    "sizes": "Size",
    "finishes": "Finish",
    "quantity": "Quantity",
    "skus": "Designs / SKUs",
    "material": "Material / special features",
    "extras": "Extras",
    "name": "Name",
    "email": "Email",
    "phone": "Phone",
}

BLOCKING_FIELDS = ("product", "sizes", "quantity")
CONTACT_FIELDS = ("email", "phone", "name")
# Facts the customer alone can supply: the model may repeat them, never propose them.
CUSTOMER_ONLY_FIELDS = ("sizes", "email", "phone", "name", "quantity", "skus")
# A contact detail typed into one of these is a misplaced answer, not a
# description of the job, and must not settle the field.
PROSE_FIELDS = ("product", "style", "material", "finishes", "extras", "use_case", "name")

# PLAN_V2 Section 3.1: status says how far a value travelled, basis (Section 4.8)
# says where it came from. v1's single "answered" flag could not tell a customer's
# own number from one the bot proposed, which is what the re-ask guard needs.
STATUS_UNKNOWN = "unknown"
STATUS_VISITOR = "visitor"
STATUS_SUGGESTED = "suggested"
STATUS_CONFIRMED = "confirmed"
STATUS_WAIVED = "waived"
GOAL_STATUSES = (STATUS_UNKNOWN, STATUS_VISITOR, STATUS_SUGGESTED, STATUS_CONFIRMED, STATUS_WAIVED)

BASIS_CANON = "canon"
BASIS_CATALOGUE = "catalogue"
BASIS_MODEL = "model_knowledge"
BASIS_VISITOR = "visitor"
GOAL_BASES = (BASIS_CANON, BASIS_CATALOGUE, BASIS_MODEL, BASIS_VISITOR)

# A value in one of these statuses satisfies the field: nobody asks it again.
SETTLED_STATUSES = frozenset({STATUS_VISITOR, STATUS_CONFIRMED, STATUS_WAIVED})
# Only these count as "the customer told us", which is what a re-ask is judged against.
STATED_STATUSES = frozenset({STATUS_VISITOR, STATUS_CONFIRMED})

# v1 status names, so old SQLite records and replay artifacts still load.
LEGACY_STATUSES = {
    "missing": STATUS_UNKNOWN,
    "answered": STATUS_VISITOR,
    "needs_confirmation": STATUS_WAIVED,
}
# A v1 record only ever held customer-supplied values; a model echo was stored the same way.
LEGACY_SOURCES = {"visitor": BASIS_VISITOR, "model": BASIS_MODEL, "llm": BASIS_MODEL}

USE_CASE_QUESTION = "What will be inside it, or who is it going to?"
EMAIL_QUESTION = "What is the best email to send the quote to?"
PHONE_QUESTION = "What is the best phone number to reach you on?"

# Section 3.4. Highest decision impact first. The ask-set is this order, filtered
# to fields that are still missing and that change the recommendation or the quote.
# `use_case` always qualifies and is deliberately not in `BLOCKING_FIELDS`: putting
# it there would stall every chat that never names the contents.
ASK_PRIORITY = (
    "product",
    "use_case",
    "sizes",
    "quantity",
    "style",
    "material",
    "finishes",
    "skus",
    "extras",
    "email",
    "phone",
)
ALWAYS_ASK_FIELDS = frozenset({"product", "use_case", "sizes", "quantity"})
# Nice-to-haves and contact. Rule 6: while a quote-blocking field is empty the
# model does not ask these. finish / skus / extras are named in rule 3; style and
# material are the same class in Section 3.1 (they change the option, not the quote).
AFTER_BLOCKING_FIELDS = frozenset(
    {"style", "material", "finishes", "skus", "extras", "email", "phone"}
)

# Wording catalogue only. Phase 2b: this dict does not choose the next question —
# `ConversationState.ask_set` does. `question_for` reads a sentence from here when
# a field has been selected, and nowhere else consults the order of these lists.
SCRIPTS: dict[str, list[tuple[str, str]]] = {
    "bags": [
        ("sizes", "What bag size are you looking for?"),
        ("style", "What style of bag do you need: flat, stand-up or flat-bottom?"),
        ("finishes", "What finish do you prefer: matte, gloss or soft touch?"),
        ("quantity", "What quantity are you looking to order for your first run?"),
        ("skus", "How many total designs or SKUs do you have?"),
        ("extras", "Do you want me to add a zipper and tear notch?"),
        ("material", "Do you have any specific material or special features in mind?"),
    ],
    "boxes": [
        ("sizes", "What box size are you looking for?"),
        ("style", "What style of box do you need, or can you share a reference image?"),
        ("finishes", "What finish do you prefer: matte, gloss or soft touch?"),
        ("quantity", "What quantity are you looking to order for your first run?"),
        ("skus", "How many total designs or SKUs do you have?"),
        ("material", "Do you have any specific material or special features in mind?"),
    ],
    "labels": [
        ("sizes", "What label size are you looking for?"),
        ("finishes", "What finish do you prefer: matte, gloss or soft touch?"),
        ("quantity", "What quantity are you looking to order for your first run?"),
        ("skus", "How many total designs or SKUs do you have?"),
        ("material", "Do you have any specific material or special features in mind?"),
    ],
    "banners": [
        ("sizes", "What banner size are you looking for?"),
        ("quantity", "How many banners do you need?"),
        ("finishes", "What finish do you prefer: matte, gloss or soft touch?"),
        ("material", "Do you need single-sided or double-sided printing?"),
    ],
    "business_cards": [
        ("sizes", "What business card size are you looking for?"),
        ("quantity", "What quantity are you looking to order for your first run?"),
        ("finishes", "What finish do you prefer: matte, gloss or soft touch?"),
        ("material", "Any special paper stock in mind?"),
    ],
    "print": [
        ("sizes", "What size are you looking for?"),
        ("quantity", "What quantity are you looking to order?"),
        ("finishes", "What finish do you prefer: matte, gloss or soft touch?"),
        ("material", "Any special paper or finishing in mind?"),
    ],
}

# Last-resort sentences for a field the selected family's script does not list.
# The script line wins whenever one exists.
FALLBACK_QUESTIONS = {
    "sizes": "What size are you looking for?",
    "quantity": "What quantity are you looking to order for your first run?",
    "style": "What style do you need?",
    "finishes": "What finish do you prefer: matte, gloss or soft touch?",
    "skus": "How many total designs or SKUs do you have?",
    "material": "Do you have any specific material or special features in mind?",
    "extras": "Do you want any extras on this order?",
    "name": "Who am I speaking with?",
}

PRODUCT_QUESTION = "What are you looking to have made — boxes, bags, labels, or something else?"

BANNER_RE = re.compile(
    r"\b(banners?|signs?|signage|pull[- ]?ups?|roll[- ]?ups?|pop[- ]?ups?(?!\s*(?:box|boxes|card|cards|book|books|carton|cartons|mailer|mailers)\b)|retractables?|backdrops?|step[- ]and[- ]repeat|x[- ]?stands?)\b",
    re.I,
)
BUSINESS_CARD_RE = re.compile(r"\bbusiness cards?\b", re.I)
LABEL_RE = re.compile(r"\b(labels?|stickers?|decals?|die[- ]?cut)\b", re.I)
BAG_RE = re.compile(r"\b(bags?|pouch(?:es)?|mylar|stand[- ]?up|flat[- ]?bottom|doypack|zipper|tear notch)\b", re.I)
BOX_RE = re.compile(
    r"\b(box(?:es)?|cartons?|mailers?|rigid|corrugated|folding carton|tuck|"
    r"(?:display\s+)?trays?|countertop displays?)\b",
    re.I,
)
PRINT_RE = re.compile(r"\b(flyers?|brochures?|postcards?|booklets?|folders?|magnets?|invitations?|greeting cards?)\b", re.I)
PLAIN_RE = re.compile(
    r"\b(plain|blank|unprinted|un-printed|non-printed|not printed|no[- ]print(?:ing)?|without (?:any )?(?:print(?:ing)?|logo|branding)|no (?:logo|branding)|no[- ]design(?!\s+(?:yet|ready|file|files|done)\b))\b",
    re.I,
)
SIZE_UNKNOWN_RE = re.compile(r"\b(no idea|not sure|don'?t know|dunno|whatever|any size|you decide|standard)\b", re.I)
UNIT_ONLY_RE = re.compile(
    r"^\s*(?:in(?:ch(?:es)?)?|\"|cm|mm|centimet(?:er|re)s?|millimet(?:er|re)s?)\s*[.!]*\s*$",
    re.I,
)
CONTACT_REFUSAL_RE = re.compile(
    r"^\s*(?:no|nope)\s*[.!]*\s*$"
    r"|\b(?:no|nope)\b[^.?!]{0,40}\b(?:want|need|give|share|provide|interested)\b"
    r"|\bdon[’'`;]?t\s+(?:want|email|call|contact)\b|\bdo\s+not\s+want\b"
    r"|\bnot\s+interested\b|\bno\s+thanks?(?:\s+you)?\b|\bi'?ll\s+pass\b"
    r"|\bskip\s+(?:it|that|this)\b|\bno\s+(?:email|phone|number)\b"
    r"|\bstop\s+asking\b|\bleave\s+me\s+alone\b",
    re.I,
)
UNSPECIFIED_RE = re.compile(
    r"^\s*(?:"
    r"(?:i\s+)?(?:don'?t|dont)\s+have(?:\s+(?:a|any|one))?"
    r"(?:\s+(?:reference|image|design|idea|preference)){0,2}"
    r"|(?:i\s+)?(?:don'?t|dont)\s+know|not\s+sure|unsure|no\s+(?:idea|clue|preference|reference)"
    r"|dunno|idk|no|nope|none|nothing(?:\s+specific)?|whatever|anything|any"
    r")\s*[.!]*\s*$",
    re.I,
)
SIZE_UNIT_RE = re.compile(
    r'(?:\d(?:\.\d+)?\s*(?:in|inch|inches|"|cm|mm|oz|ml|g|grams?|lb|ft)\b|\b(?:inches|centimet(?:er|re)s?|millimet(?:er|re)s?|cm|mm|oz|ml|grams?)\b)',
    re.I,
)
SIZE_DIM_RE = re.compile(
    r"(\d+(?:\.\d+)?)\s*(?:x|×|by)\s*(\d+(?:\.\d+)?)(?:\s*(?:x|×|by)\s*(\d+(?:\.\d+)?))?\s*(in(?:ch(?:es)?)?|\"|cm|mm|oz|ml|g|grams?|lb|ft)?",
    re.I,
)
SINGLE_SIZE_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(in(?:ch(?:es)?)?|\"|cm|mm|oz|ml|g|grams?|lb|ft)\b", re.I)
QTY_RE = re.compile(
    r"(\d[\d,]*(?:\.\d+)?)\s*(k|thousand|pcs|pieces|units|bags?|boxes?|labels?|stickers?|pouch(?:es)?|banners?|cards?)?\b",
    re.I,
)
# A number only counts as an order quantity when it sits next to a unit word.
# "2 count gummy pouch" is a pack size, not an order of two pouches.
QTY_UNIT_RE = re.compile(
    r"(\d[\d,]*(?:\.\d+)?)\s*(k|thousand|pcs|pieces|units|bags?|boxes?|labels?|stickers?|pouch(?:es)?|banners?|cards?)\b",
    re.I,
)
BARE_QTY_RE = re.compile(
    r"^\s*(?:around|about|approx\.?|roughly|~)?\s*(\d[\d,]*(?:\.\d+)?)\s*(k|thousand)?\s*"
    r"(?:units?|pcs|pieces)?\s*[.!]?\s*$",
    re.I,
)
EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b")
PHONE_RE = re.compile(r"(?<!\d)(?:\+?1[\s.\-]?)?(?:\(?\d{3}\)?[\s.\-]?)\d{3}[\s.\-]?\d{4}(?!\d)")
FINISH_WORDS = {
    "matte": ("matte", "matt"),
    "gloss": ("gloss", "glass", "glossy"),
    "soft touch": ("soft touch", "soft-touch", "suede"),
    "spot uv": ("spot uv", "spot-uv"),
    "foil": ("foil", "gold foil", "silver foil"),
    "embossing": ("emboss", "embossing"),
    "none": ("none", "no finish", "no preference", "whatever", "standard"),
}
STYLE_HINTS = re.compile(
    r"\b(flat|stand[- ]?up|standup|flat[- ]?bottom|gusset|pillow|quad|doypack|side seal|"
    r"tuck|mailer|rigid|folding|drawer|sleeve|window|lid|two[- ]piece|auto[- ]bottom|"
    r"straight|reverse|candle|display|zip(?:per|lock)?)\b",
    re.I,
)
# Longest/most specific first: "flat-bottom" must win over "flat", and
# "side gusset" over the generic "gusset".
STYLE_VALUES = (
    ("stand-up", ("stand-up", "stand up", "standup", "doypack")),
    ("flat-bottom", ("flat-bottom", "flat bottom", "flatbottom")),
    ("flat", ("flat pouch", "flat", "3-side seal", "three-side seal", "three side seal", "side seal")),
    ("side gusset", ("side gusset", "side-gusset")),
    ("pinch bottom", ("pinch bottom", "pinch-bottom")),
    ("mailer", ("mailer",)),
    ("rigid", ("rigid",)),
    ("folding carton", ("folding carton", "folding")),
    ("display", ("display",)),
    ("gift", ("gift",)),
    ("window", ("window",)),
    ("tuck", ("tuck",)),
    ("drawer", ("drawer",)),
    ("sleeve", ("sleeve",)),
    ("pillow", ("pillow",)),
    ("gusset", ("gusset",)),
)
MATERIAL_HINTS = re.compile(
    r"\b(pet|mpet|rpet|kraft|foil|metali[sz]ed|paper|cardstock|card stock|corrugated|"
    r"vinyl|bopp|pp|pe|plastic|clear|holographic|silver|gold|white)\b",
    re.I,
)
# Section 3.1: `use_case` is the field v1 has no place for, which is the structural
# reason the bot never asks what is being packed. Two shapes of answer: a sales
# channel, or the thing that goes inside.
USE_CASE_NOUN_RE = re.compile(
    r"\b(?:for my|for our|to pack|packing|packed with|holds|holding|filled with|going inside|goes inside|"
    r"use case|intended for|for shipping|for storing|for sending|for mailing|for selling|for wrapping|for gifting)\s+"
    r"([a-z][a-z0-9 &'\-]{2,48}?)(?=\s*(?:[,.!?]|\band\b|\bbut\b|\bso\b|\bbecause\b|\bin\b|\bwith\b|\bthat\b|\bplease\b|\bthanks\b|$))",
    re.I,
)
USE_CASE_CHANNEL_RE = re.compile(
    r"\b(e[- ]?commerce|retail|wholesale|in[- ]store|brick[- ]and[- ]mortar|subscription|"
    r"mail[- ]order|shipping|trade show|product launch|moving|storage|gifting|gift)\b",
    re.I,
)
USE_CASE_STOP_WORDS = {"the", "a", "an", "my", "our", "their", "some", "any", "new", "old", "own"}
AFFIRMATION_UNIT = (
    r"yes|yeah|yep|yup|sure|ok(?:ay)?|that works|that'?s (?:right|fine|good|it)|"
    r"sounds? (?:good|right)|looks good|correct|exactly|perfect|fine by me|"
    r"(?:i'?|we'|w-)ll go with (?:that|it|this)"
)
AFFIRMATION_RE = re.compile(
    rf"\s*(?:{AFFIRMATION_UNIT})(?:[,\s]+(?:{AFFIRMATION_UNIT}))*[.!?]*\s*",
    re.I,
)
WANTS_HUMAN = re.compile(
    r"\b(human|person|agent|representative|rep\b|real (?:person|human)|someone else|speak to (?:a|an|someone|sales|support|rep)|talk to (?:a|an|someone|sales|support|rep)|operator|manager|customer service|live support|live chat|live agent)\b"
    r"|\b(?:don'?t|do not|not|no|stop|hate)\s+(?:want\s+to\s+)?(?:talk(?:ing)?\s*(?:to)?\s+|speak(?:ing)?\s*(?:to)?\s+|chat(?:ting)?\s*(?:with)?\s+)?(?:an?\s+)?(?:ai|bot|robo[a-z]*t|automated|machine)\b"
    r"|\b(?:are you|is this)\s+(?:an?\s+)?(?:ai|bot|robot)\b",
    re.I,
)
ASKS_IF_BOT = re.compile(
    r"\b(?:are you|r u|is this|am i (?:talking|speaking|chatting) (?:to|with))\s+(?:an?\s+|the\s+)?(?:real\s+)?(?:ai|bot|robo[a-z]*t|chat ?bot|automated|machine|human|person)\b"
    # The Ethan incident had no "are you": "you said you are ethan now you called ai".
    r"|\byou called (?:me\s+)?(?:an?\s+)?ai\b"
    r"|\bcalled (?:you|yourself) (?:an?\s+)?(?:ai|a bot|a chatbot)\b",
    re.I,
)
GOODBYE_RE = re.compile(r"\b(bye|goodbye|thanks?|thank you|that'?s all|nothing else|thats it|that is it)\b", re.I)
PRICE_OBJECTION_RE = re.compile(r"\b(expensive|too much|over budget|cheaper|discount|lower price)\b", re.I)
JOB_PITCH_RE = re.compile(
    r"\b(we (?:offer|provide) (?:seo|web|digital marketing|software|development)|i am a (?:developer|designer|freelancer)|we are a (?:agency|software company))\b",
    re.I,
)
QUESTION_START_RE = re.compile(
    r"^\s*(?:what|how|where|when|why|who|which|can|could|do|does|did|is|are|will|would|should|any)\b",
    re.I,
)

RECOMMENDATION_RE = re.compile(
    r"\b(?:suggest|recommend)\b"
    r"|\bwhat(?:'s| is) (?:the )?best\b"
    r"|\bwhat (?:packaging|box(?:es)?|bags?|pouches?|materials?|styles?)\b[^.?!]{0,40}\bbest\b"
    r"|\bbest (?:option|choice|fit|box(?:es)?|bags?|pouches?|packaging|materials?|styles?)\b"
    r"|\bwhich (?:packaging|box(?:es)?|bags?|pouches?|materials?|styles?|option|one)\b"
    r"|\bshould i (?:use|choose|pick|get|go with)\b"
    r"|\bhelp me (?:choose|pick|decide)\b"
    r"|\bwhat (?:packaging|box(?:es)?|bags?|pouches?|materials?|styles?) (?:should|would|do you)\b",
    re.I,
)


def wants_recommendation(text: str) -> bool:
    return bool(RECOMMENDATION_RE.search(str(text or "")))


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def family_of(product: str = "", texts: tuple[str, ...] = ()) -> str:
    blob = " ".join([product, *texts]).strip()
    if not blob:
        return "unknown"
    if BANNER_RE.search(blob):
        return "banners"
    if BUSINESS_CARD_RE.search(blob):
        return "business_cards"
    found: list[str] = []
    if LABEL_RE.search(blob):
        found.append("labels")
    if BAG_RE.search(blob):
        found.append("bags")
    if BOX_RE.search(blob):
        found.append("boxes")
    if PRINT_RE.search(blob):
        found.append("print")
    unique = list(dict.fromkeys(found))
    return unique[0] if len(unique) == 1 else ("unknown" if len(unique) > 1 else "unknown")


def is_plain(text: str) -> bool:
    return bool(PLAIN_RE.search(str(text or "")))


def size_has_unit(text: str) -> bool:
    return bool(SIZE_UNIT_RE.search(str(text or "")))


def size_is_unknown(text: str) -> bool:
    return bool(SIZE_UNKNOWN_RE.search(str(text or "")))


def refuses_contact(text: str) -> bool:
    return bool(CONTACT_REFUSAL_RE.search(str(text or "")))


# Section 3.4 rule 1: "inches" and "in" are the same answer and "4 x 6" is "4x6",
# so stored values are folded to one shape. Dimension *order* is the customer's:
# "6x4 in" and "4x6x2" are different things (Section 3.1), and the gusset in
# "8x12+4" sits where it means something. Their exact wording stays in
# `raw_visitor_text`.
UNIT_FORMS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("in", ("inch", "inches", "in")),
    ("cm", ("centimeter", "centimeters", "centimetre", "centimetres", "cm")),
    ("mm", ("millimeter", "millimeters", "millimetre", "millimetres", "mm")),
    ("oz", ("ounce", "ounces", "oz")),
    ("ml", ("milliliter", "milliliters", "millilitre", "millilitres", "ml")),
    ("g", ("gram", "grams", "g")),
    ("lb", ("lb", "lbs", "pound", "pounds")),
    ("ft", ("ft", "foot", "feet")),
)
DIM_SET_RE = re.compile(
    r"^(\d+(?:\.\d+)?)"
    r"(?:\s*(?:x|×|\*|by)\s*(\d+(?:\.\d+)?))?"
    r"(?:\s*(?:x|×|\*|by)\s*(\d+(?:\.\d+)?))?"
    r"(?:\s*(.+))?$",
    re.I,
)


def _canonical_unit(token: str) -> str:
    value = token.strip().strip('."').lower()
    for canonical, forms in UNIT_FORMS:
        if value in forms:
            return canonical
    return ""


def _spell_units(text: str) -> str:
    for canonical, forms in UNIT_FORMS:
        pattern = re.compile(r"\b(?:%s)\b" % "|".join(re.escape(item) for item in forms), re.I)
        text = pattern.sub(canonical, text)
    return text


def _trim_number(value: str) -> str:
    return f"{float(value):.2f}".rstrip("0").rstrip(".")


def normalise_size(text: str) -> str:
    value = re.sub(r"\s+", " ", str(text or "")).strip(" .,;")
    if not value:
        return ""
    # An inch mark is a unit, but it belongs to the whole set: 24" x 36" is
    # "24x36 in", not "24 in x 36 in".
    quoted = '"' in value
    value = re.sub(r'(?<=\d)\s*"', " ", value)
    match = DIM_SET_RE.match(value)
    numbers = [item for item in (match.group(1), match.group(2), match.group(3)) if item] if match else []
    tail = (match.group(4) or "").strip() if match else ""
    if numbers and (not tail or _canonical_unit(tail)):
        # A plain LxW or LxWxH set: one shape, in the order they wrote it.
        unit = _canonical_unit(tail) or ("in" if quoted else "")
        size = "x".join(_trim_number(item) for item in numbers)
        return f"{size} {unit}".strip()[:60]
    return _spell_units(value)[:60]


def parse_quantity(text: str) -> int | None:
    match = QTY_RE.search(str(text or "").replace(",", ""))
    if not match:
        return None
    try:
        value = float(match.group(1))
    except ValueError:
        return None
    unit = (match.group(2) or "").lower()
    if unit in {"k", "thousand"}:
        value *= 1000
    if value <= 0 or value > 100_000_000:
        return None
    return int(value)


def normalize_finish(text: str) -> str | None:
    lowered = str(text or "").lower()
    for label, words in FINISH_WORDS.items():
        if any(word in lowered for word in words):
            return label
    return None


def use_case_from(text: str) -> str:
    """What it is for: the thing going inside, or the channel it sells through."""
    value = str(text or "")
    match = USE_CASE_NOUN_RE.search(value)
    if match:
        phrase = re.sub(r"\s+", " ", match.group(1)).strip(" .,;:")
        words = [word for word in phrase.lower().split() if word not in USE_CASE_STOP_WORDS]
        if words and family_of(phrase) == "unknown":
            return phrase.lower()[:60]
    channel = USE_CASE_CHANNEL_RE.search(value)
    if channel:
        return re.sub(r"\s+", " ", channel.group(0).lower())[:60]
    return ""


def normalize_style(text: str) -> str | None:
    lowered = str(text or "").lower()
    for label, words in STYLE_VALUES:
        if any(re.search(rf"\b{re.escape(word)}\b", lowered) for word in words):
            return label
    return None


def valid_email(text: str) -> bool:
    return bool(EMAIL_RE.fullmatch(str(text or "").strip()))


def valid_phone(text: str) -> bool:
    digits = re.sub(r"\D", "", str(text or ""))
    return 10 <= len(digits) <= 15


def looks_like_contact(text: str) -> bool:
    """An address or a number is contact detail, never a material, style or name."""
    value = str(text or "").strip()
    if EMAIL_RE.search(value):
        return True
    digits = re.sub(r"\D", "", value)
    return bool(value) and 10 <= len(digits) <= 15 and bool(re.fullmatch(r"[+\d][\d\s().-]{8,}", value))


def is_question(text: str) -> bool:
    value = str(text or "").strip()
    return "?" in value or bool(QUESTION_START_RE.search(value))


CONTEXT_QUESTION_RE = re.compile(
    r"\bfor (?:what|which|whom)\b"
    r"|\b(?:bags?|boxes?|labels?|pouches?)\s+(?:or|vs\.?|versus)\s+(?:bags?|boxes?|labels?|pouches?)\b"
    r"|\bwhich (?:one|product|item)\b"
    r"|\bwhat (?:product|item) (?:is|was) (?:that|it) for\b"
    r"|\bwhat(?:'s| is)? (?:that|this|it) for\b"
    r"|\bwhat do you mean\b"
    r"|\b(?:sorry|wait),?\s+(?:what|which)\b",
    re.I,
)


def is_context_question(text: str) -> bool:
    value = str(text or "")
    return is_question(value) and bool(CONTEXT_QUESTION_RE.search(value))


def wants_human(text: str) -> bool:
    return bool(WANTS_HUMAN.search(re.sub(r"\S+@\S+", " ", str(text or ""))))


def asks_if_bot(text: str) -> bool:
    return bool(ASKS_IF_BOT.search(str(text or "")))


META_QUESTION_RE = re.compile(
    r"\bwhy are you asking\b"
    r"|\bwhy do you (?:need|want|ask)\b"
    r"|\b(?:this is|you(?:'re| are)) (?:useless|not helping|annoying)\b"
    r"|\bstop asking\b"
    r"|\bi (?:have|got) a complaint\b",
    re.I,
)


def is_meta_question(text: str) -> bool:
    """Identity, a complaint, or 'why are you asking' — answer it before any ask."""
    return asks_if_bot(text) or bool(META_QUESTION_RE.search(str(text or "")))


def is_goodbye(text: str) -> bool:
    value = str(text or "").strip()
    return len(value.split()) <= 6 and bool(GOODBYE_RE.search(value))


def is_price_objection(text: str) -> bool:
    return bool(PRICE_OBJECTION_RE.search(str(text or "")))


def is_job_pitch(text: str) -> bool:
    return bool(JOB_PITCH_RE.search(str(text or "")))


def moq_for(family: str, skus: int = 1) -> int:
    if family == "banners":
        return 1
    return 500 if skus >= 2 else 1000


def below_moq(quantity: int | None, family: str, skus: int = 1) -> bool:
    if quantity is None or family == "banners":
        return False
    return quantity < moq_for(family, skus)


@dataclass
class FieldValue:
    """One `GoalState` entry: value, the words it came in, where it came from, how far it travelled."""

    value: str = ""
    status: str = STATUS_UNKNOWN
    attempts: int = 0
    raw_visitor_text: str = ""
    basis: str = ""

    @property
    def done(self) -> bool:
        """Settled: the field needs no further ask, even if the team still has to confirm it."""
        return bool(self.value) and self.status in SETTLED_STATUSES

    @property
    def stated(self) -> bool:
        """The customer said it (or agreed to it) — asking again is the `redundant_ask` failure."""
        return bool(self.value) and self.status in STATED_STATUSES

    def to_dict(self) -> dict:
        return {
            "value": self.value,
            "status": self.status,
            "attempts": self.attempts,
            "raw_visitor_text": self.raw_visitor_text,
            "basis": self.basis,
        }

    @classmethod
    def from_dict(cls, data: dict | None) -> "FieldValue":
        data = data or {}
        status = str(data.get("status", STATUS_UNKNOWN))
        status = LEGACY_STATUSES.get(status, status)
        basis = str(data.get("basis", ""))
        if not basis:
            # v1 records carried `source` instead; every v1 write came from the visitor.
            legacy = str(data.get("source", ""))
            basis = LEGACY_SOURCES.get(legacy, BASIS_VISITOR if status != STATUS_UNKNOWN else "")
        return cls(
            value=str(data.get("value", "")),
            status=status,
            attempts=int(data.get("attempts", 0)),
            raw_visitor_text=str(data.get("raw_visitor_text", "")),
            basis=basis,
        )


@dataclass
class Message:
    author: str
    text: str
    at: str = field(default_factory=now_iso)

    def to_dict(self) -> dict:
        return {"author": self.author, "text": self.text, "at": self.at}


@dataclass
class ConversationState:
    id: str
    persona: str
    created_at: str = field(default_factory=now_iso)
    updated_at: str = field(default_factory=now_iso)
    messages: list[Message] = field(default_factory=list)
    fields: dict[str, FieldValue] = field(default_factory=dict)
    flags: dict[str, Any] = field(default_factory=dict)
    handoff: str = ""
    turn_count: int = 0
    last_question: str = ""

    def __post_init__(self) -> None:
        for key in FIELD_LABELS:
            self.fields.setdefault(key, FieldValue())

    def add(self, author: str, text: str) -> None:
        self.messages.append(Message(author=author, text=str(text)))
        self.updated_at = now_iso()
        if author == "ai":
            self.turn_count += 1

    def visitor_texts(self) -> list[str]:
        return [m.text for m in self.messages if m.author == "visitor"]

    def bot_texts(self) -> list[str]:
        return [m.text for m in self.messages if m.author == "ai"]

    def last_visitor(self) -> str:
        for message in reversed(self.messages):
            if message.author == "visitor":
                return message.text
        return ""

    def last_bot(self) -> str:
        for message in reversed(self.messages):
            if message.author == "ai":
                return message.text
        return ""

    def set_field(
        self,
        key: str,
        value: str,
        basis: str = BASIS_VISITOR,
        *,
        raw: str = "",
        status: str | None = None,
    ) -> None:
        if key not in self.fields:
            self.fields[key] = FieldValue()
        field_value = self.fields[key]
        field_value.value = str(value).strip()
        field_value.basis = basis
        # `raw_visitor_text` holds the customer's own words. A value the model
        # proposed has none, and must not borrow the proposal text to fill it in.
        field_value.raw_visitor_text = str(
            raw if raw or basis != BASIS_VISITOR else value
        ).strip()[:200]
        if status is not None:
            field_value.status = status

    def size_needs_unit(self) -> bool:
        """A number the visitor gave without a unit — still the visitor's size, not yet usable."""
        sizes = self.fields["sizes"]
        return (
            bool(sizes.value)
            and sizes.status == STATUS_VISITOR
            and not size_has_unit(sizes.value)
            and not size_is_unknown(sizes.value)
        )

    def family(self) -> str:
        product = self.fields["product"].value
        if product:
            return family_of(product)
        return family_of("", tuple(self.visitor_texts()[-4:]))

    def is_plain(self) -> bool:
        return bool(self.flags.get("plain")) or is_plain(" ".join(self.visitor_texts()[-4:]))

    def quantity_below_standard(self) -> bool:
        if self.family() in {"unknown", "banners"}:
            return False
        quantity = self.fields["quantity"].value
        if not quantity or not str(quantity).isdigit():
            return False
        qty = int(quantity)
        if qty < 500:
            return True
        if self.is_plain():
            return qty < 1000
        skus = self.fields["skus"].value
        if skus and str(skus).isdigit():
            return qty < (500 if int(skus) >= 2 else 1000)
        return False

    def reachable(self) -> bool:
        return self.fields["email"].done or self.fields["phone"].done

    def specs_done(self) -> bool:
        for key in BLOCKING_FIELDS:
            value = self.fields[key]
            if not value.done:
                return False
        return not self.size_needs_unit()

    def complete(self) -> bool:
        return self.specs_done() and self.reachable()

    def script(self) -> list[tuple[str, str]]:
        """The family's wording catalogue. Order here is not the order we ask in."""
        family = self.family()
        return SCRIPTS.get(family, [])

    def blocking_open(self) -> bool:
        """A quote-blocking field is still empty. `use_case` is not one of them."""
        for key in BLOCKING_FIELDS:
            if key == "sizes" and self.size_needs_unit():
                return True
            if not self.fields[key].done:
                return True
        return False

    def _askable(self, key: str, blocking_open: bool, family_fields: set[str]) -> bool:
        value = self.fields[key]
        # A number without a unit is still the visitor's size, and still askable once.
        if key == "sizes" and self.size_needs_unit() and not self.flags.get("unit_asked"):
            return True
        # `suggested` waits on a yes/no, not a fresh question. `done` includes a waiver.
        # Two attempts is the existing cap; offering the field again would re-ask it.
        if value.status == STATUS_SUGGESTED or value.done or value.attempts >= 2:
            return False
        if key in ALWAYS_ASK_FIELDS:
            return True
        if blocking_open or key not in AFTER_BLOCKING_FIELDS:
            return False
        if key in {"email", "phone"}:
            if self.reachable():
                return False
            # Email twice, then phone — the same contact order as before, just no longer
            # gated on walking the script to the end.
            if key == "phone" and not self.fields["email"].done and self.fields["email"].attempts < 2:
                return False
            return True
        if key == "skus" and self.is_plain():
            return False
        return key in family_fields

    def ask_set(self) -> list[str]:
        """Missing fields that materially change the recommendation or the quote.

        Section 3.4. Injected into the prompt as the only fields that may be asked.
        With no family yet, the only legal ask is which product — anything else
        assumes an answer the visitor has not given.
        """
        if self.handoff:
            return []
        if self.family() == "unknown":
            if self._askable("product", True, set()):
                return ["product"]
            return []
        blocking_open = self.blocking_open()
        family_fields = {key for key, _question in self.script()}
        return [
            key
            for key in ASK_PRIORITY
            if key in self.fields and self._askable(key, blocking_open, family_fields)
        ]

    def do_not_ask(self) -> list[tuple[str, str]]:
        """Settled fields with the visitor's own words. Off limits, even as a confirmation."""
        denied: list[tuple[str, str]] = []
        for key in FIELD_LABELS:
            value = self.fields.get(key)
            if value is None or not (value.stated or value.status == STATUS_WAIVED):
                continue
            # The number is known; the unit is not. Asking which unit is still legal.
            if key == "sizes" and self.size_needs_unit() and not self.flags.get("unit_asked"):
                continue
            words = " ".join((value.raw_visitor_text or value.value).split())
            if words:
                denied.append((key, words))
        return denied

    def ask_constraint(self) -> str:
        """The hard prompt lines from Section 3.4: allowed asks, then their words."""
        allowed = self.ask_set()
        ask = ", ".join(allowed) if allowed else "(nothing — do not ask a new question)"
        denied = self.do_not_ask()
        if denied:
            parts = []
            for key, words in denied:
                shown = words.replace('"', "'")
                if len(shown) > 80:
                    shown = shown[:77] + "..."
                parts.append(f'{key} (they said "{shown}")')
            deny = ", ".join(parts)
        else:
            deny = "(nothing yet)"
        return f"You may ask about: {ask}.\nDo not ask about: {deny}."

    def question_for(self, key: str) -> str:
        """Wording for a field the ask-set already selected. The script is one source."""
        if key == "use_case":
            return USE_CASE_QUESTION
        if key == "product":
            return PRODUCT_QUESTION
        if key == "email":
            return EMAIL_QUESTION
        if key == "phone":
            return PHONE_QUESTION
        if key == "sizes" and self.size_needs_unit():
            return "Is that in inches, cm or mm?"
        for field_key, question in self.script():
            if field_key == key:
                return question
        return FALLBACK_QUESTIONS.get(key, "")

    def repair_fields(self) -> list[str]:
        # Older turns could store the visitor's question in a free-text field
        # (style, material, extras). Clear those so the field can be asked again.
        repaired: list[str] = []
        for key in ("style", "material", "extras"):
            field_value = self.fields[key]
            if field_value.value and is_question(field_value.value):
                field_value.value = ""
                field_value.raw_visitor_text = ""
                field_value.status = STATUS_UNKNOWN
                field_value.attempts = min(field_value.attempts, 1)
                repaired.append(key)
        return repaired

    def confirm_suggested(self, visitor_text: str) -> list[str]:
        """Propose-and-confirm (Section 8): a bare yes makes the bot's proposal the customer's answer."""
        pending = self.fields.get(self.last_question)
        if pending is None or pending.status != STATUS_SUGGESTED or not pending.value:
            return []
        if not AFFIRMATION_RE.fullmatch(str(visitor_text or "")):
            return []
        pending.status = STATUS_CONFIRMED
        pending.basis = BASIS_VISITOR
        pending.raw_visitor_text = str(visitor_text).strip()[:200]
        return [self.last_question]

    def next_question(self) -> tuple[str, str] | None:
        """The single highest-impact ask, for fake mode and the wording fallback.

        The live prompt shows the whole ask-set and the model picks. This is not
        a script position: `SCRIPTS` only supplies the sentence, via `question_for`.
        """
        if self.handoff:
            return None
        for key in self.ask_set():
            question = self.question_for(key)
            if question:
                return key, question
        if self.blocking_open():
            return None
        return self.next_contact_question()

    def finalize_stalled(self) -> list[str]:
        """The unit follow-up gets exactly one turn; after it, the size is the team's to confirm."""
        noted: list[str] = []
        if self.size_needs_unit() and self.flags.get("unit_asked"):
            self.fields["sizes"].status = STATUS_WAIVED
            noted.append("sizes")
        return noted

    def next_contact_question(self) -> tuple[str, str] | None:
        email = self.fields["email"]
        phone = self.fields["phone"]
        if self.reachable():
            return None
        if email.attempts < 2:
            return "email", EMAIL_QUESTION
        if phone.attempts < 2:
            return "phone", PHONE_QUESTION
        return None

    def missing_for_prompt(self) -> list[str]:
        relevant = {key for key, _ in self.script()} | set(BLOCKING_FIELDS) | {"use_case"}
        missing = []
        for key in FIELD_LABELS:
            value = self.fields[key]
            if value.done and not (key == "sizes" and self.size_needs_unit()):
                continue
            if key in BLOCKING_FIELDS:
                missing.append(f"{FIELD_LABELS[key]} (blocking)")
            elif key == "use_case":
                missing.append(f"{FIELD_LABELS[key]} (needed for a recommendation)")
            elif key in CONTACT_FIELDS:
                if not self.reachable() and key != "name":
                    missing.append(FIELD_LABELS[key])
            elif key in relevant:
                missing.append(FIELD_LABELS[key])
        return missing

    def known_for_prompt(self) -> str:
        """Every value carries how far it travelled and where it came from — Section 3.1's two axes."""
        parts = []
        for key in FIELD_LABELS:
            field_value = self.fields[key]
            if not field_value.value:
                continue
            markers: list[str] = []
            if field_value.status != STATUS_VISITOR:
                markers.append(field_value.status)
            if field_value.basis and field_value.basis != BASIS_VISITOR:
                markers.append(field_value.basis)
            suffix = f" [{'/'.join(markers)}]" if markers else ""
            parts.append(f"{FIELD_LABELS[key]}: {field_value.value}{suffix}")
        return "; ".join(parts) if parts else "nothing yet"

    def summary(self) -> str:
        lines = [
            f"Persona: {self.persona}",
            f"Family: {self.family()}",
            f"Known: {self.known_for_prompt()}",
            f"Missing: {', '.join(self.missing_for_prompt()) or 'none'}",
            f"Turn: {self.turn_count + 1}",
            self.ask_constraint(),
        ]
        if self.flags.get("minimum_stated"):
            lines.append("Minimum already stated once: do not repeat it.")
        if self.flags.get("size_no_standard_explained"):
            lines.append("Already explained there is no standard size: do not explain again.")
        if self.flags.get("plain"):
            lines.append("Plain/unprinted order: do not ask for designs or SKUs.")
        return "\n".join(lines)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "persona": self.persona,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "messages": [m.to_dict() for m in self.messages],
            "fields": {k: v.to_dict() for k, v in self.fields.items()},
            "flags": dict(self.flags),
            "handoff": self.handoff,
            "turn_count": self.turn_count,
            "last_question": self.last_question,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ConversationState":
        state = cls(
            id=str(data["id"]),
            persona=str(data.get("persona", "Alex Kane")),
            created_at=str(data.get("created_at", now_iso())),
            updated_at=str(data.get("updated_at", now_iso())),
            messages=[Message(**item) for item in data.get("messages", [])],
            fields={key: FieldValue.from_dict(value) for key, value in data.get("fields", {}).items()},
            flags=dict(data.get("flags", {})),
            handoff=str(data.get("handoff", "")),
            turn_count=int(data.get("turn_count", 0)),
            last_question=str(data.get("last_question", "")),
        )
        return state

    def clone(self) -> "ConversationState":
        return ConversationState.from_dict(self.to_dict())


def traceable(key: str, value: str, visitor_text: str, state: ConversationState) -> bool:
    visitor = str(visitor_text or "").lower()
    candidate = str(value or "").strip()
    if not candidate:
        return False
    if key == "email":
        return bool(EMAIL_RE.search(visitor)) and EMAIL_RE.search(visitor).group(0).lower() == candidate.lower()
    if key == "phone":
        visitor_digits = re.sub(r"\D", "", visitor)
        value_digits = re.sub(r"\D", "", candidate)
        return bool(value_digits) and value_digits in visitor_digits
    if key == "quantity":
        number = re.sub(r"[^\d]", "", candidate)
        return bool(number) and number in re.sub(r"[^\d]", "", visitor)
    if key == "skus":
        number = re.sub(r"[^\d]", "", candidate)
        return bool(number) and (number in re.sub(r"[^\d]", "", visitor) or candidate == "1")
    if key == "sizes":
        pending = str(state.flags.get("size_pending_unit") or "").strip()
        if pending and UNIT_ONLY_RE.match(visitor) and candidate.startswith(pending):
            return True
        numbers = re.findall(r"\d+(?:\.\d+)?", candidate)
        return bool(numbers) and all(number in visitor for number in numbers)
    if key == "finishes":
        normalized = normalize_finish(candidate)
        if normalized == "none":
            return any(word in visitor for word in FINISH_WORDS["none"])
        return bool(normalized) and normalized in {"matte", "gloss", "soft touch", "spot uv", "foil", "embossing"}
    if key == "product":
        family = family_of(candidate)
        return family != "unknown" or any(token in visitor for token in candidate.lower().split())
    if key in {"style", "material", "extras", "name", "use_case"}:
        if key == "extras" and candidate.lower() in {"yes", "no", "none", "both", "neither"}:
            return True
        tokens = [token for token in re.findall(r"[a-z0-9]+", candidate.lower()) if len(token) > 2]
        return any(token in visitor for token in tokens)
    return True


def apply_field_updates(
    state: ConversationState,
    updates: dict[str, Any],
    visitor_text: str,
    *,
    source: str = "visitor",
    bases: dict[str, str] | None = None,
) -> tuple[dict[str, str], dict[str, str]]:
    """Write accepted values with their provenance: whose words, which epistemic class, how far travelled.

    `source="model"` marks the bot's own proposal, which becomes `suggested` (Section 3.1) so a
    re-ask guard can tell it from something the customer said. Sizes, contact details and numbers
    never take that status — they are only ever the customer's facts or a catalogue row.
    """
    from .guards import question_as_answer

    accepted: dict[str, str] = {}
    rejected: dict[str, str] = {}
    visitor_lower = str(visitor_text or "").lower()
    suggested_basis = BASIS_MODEL if source == "model" else BASIS_VISITOR
    for key, raw in (updates or {}).items():
        if key not in state.fields or raw is None:
            continue
        incoming = str(raw).strip()
        value = incoming
        echoed = bool(incoming) and incoming.lower() in visitor_lower
        # A number, a size or a contact detail is the customer's fact or nothing;
        # anything the model repeats back that they already said stays theirs.
        # A size the model quotes from a printed row is `catalogue`, never `suggested`.
        stated_basis = str((bases or {}).get(key) or "")
        basis = BASIS_VISITOR if echoed or key in CUSTOMER_ONLY_FIELDS else suggested_basis
        if stated_basis in GOAL_BASES and not echoed and key not in CUSTOMER_ONLY_FIELDS:
            basis = stated_basis
        if key == "sizes" and stated_basis == BASIS_CATALOGUE and not echoed:
            basis = BASIS_CATALOGUE
        # `raw_visitor_text` is the customer's own wording. A model proposal they
        # have not agreed to has no wording of theirs to carry yet.
        raw_text = incoming if echoed else ("" if basis == BASIS_MODEL else str(visitor_text or "").strip())
        if not value:
            continue
        if key in PROSE_FIELDS and looks_like_contact(value):
            rejected[key] = value
            continue
        # A question is not an answer. "your address" must not fill style.
        if basis == BASIS_VISITOR and question_as_answer(str(visitor_text or ""), key):
            rejected[key] = value
            continue
        if key == "product" and state.fields["product"].done and is_question(visitor_text):
            # "what style of boxes do you have" mentions boxes, but it is a
            # question about their existing order, not a switch to boxes.
            rejected[key] = value
            continue
        if key == "style":
            normalized_style = normalize_style(value)
            if is_question(visitor_text) and not normalized_style and basis == BASIS_VISITOR:
                rejected[key] = value
                continue
            if normalized_style:
                value = normalized_style
        if key == "material" and is_question(visitor_text) and basis == BASIS_VISITOR:
            material_match = MATERIAL_HINTS.search(value)
            if not material_match:
                rejected[key] = value
                continue
            value = material_match.group(0)
        if key == "extras" and is_question(visitor_text) and basis == BASIS_VISITOR:
            if value.lower() not in {"yes", "no", "none", "both", "neither"}:
                rejected[key] = value
                continue
        if key == "sizes":
            value = normalise_size(value)
            if not size_has_unit(value) and size_has_unit(visitor_text):
                value = normalise_size(visitor_text)
            if not size_has_unit(value) and not size_is_unknown(value) and value:
                state.flags["size_pending_unit"] = value
            if size_is_unknown(visitor_text) and size_is_unknown(value):
                # "No idea" is a waiver, not an answer: the team sizes it, the bot stops asking.
                state.set_field(key, "to be confirmed", BASIS_VISITOR, raw=visitor_text, status=STATUS_WAIVED)
                accepted[key] = "to be confirmed"
                continue
        if key == "quantity":
            looks_like_size = bool(SIZE_DIM_RE.search(visitor_text)) and not re.search(
                r"\b(pcs|pieces|units|bags?|boxes?|labels?|pouch(?:es)?|banners?|cards?|k|thousand)\b",
                visitor_text.lower(),
            )
            if state.last_question != "quantity" and looks_like_size:
                rejected[key] = value
                continue
            number = parse_quantity(value)
            if number is None:
                rejected[key] = value
                continue
            value = str(number)
        if key == "finishes":
            normalized = normalize_finish(value) or value
            value = normalized
        if key == "skus":
            number = parse_quantity(value)
            if number is not None:
                value = str(number)
        if key in {"style", "material"} and UNSPECIFIED_RE.search(visitor_text):
            state.set_field(key, "no preference", BASIS_VISITOR, raw=visitor_text, status=STATUS_WAIVED)
            accepted[key] = "no preference"
            continue
        if basis == BASIS_VISITOR and not traceable(key, value, visitor_text, state):
            # A customer answer must be the customer's own words. A model proposal
            # is allowed to invent a value, because it is recorded as `suggested`
            # and never reaches the quote sheet until the customer confirms it.
            rejected[key] = value
            continue
        state.set_field(key, value, basis, raw=raw_text)
        field_value = state.fields[key]
        if key == "sizes":
            # Section 4.4: a size is only ever the customer's number or a printed
            # catalogue row, so it never carries the model's `suggested` status.
            field_value.status = STATUS_VISITOR
            if size_has_unit(value):
                state.flags.pop("size_pending_unit", None)
            elif not size_is_unknown(value):
                state.flags.pop("unit_asked", None)
        elif basis == BASIS_MODEL:
            field_value.status = STATUS_SUGGESTED
        elif key == "email" and not valid_email(value):
            field_value.status = STATUS_UNKNOWN
        elif key == "phone" and not valid_phone(value):
            field_value.status = STATUS_UNKNOWN
        else:
            field_value.status = STATUS_VISITOR
        accepted[key] = value
    return accepted, rejected


def extract_fields(text: str, last_question: str, state: ConversationState) -> dict[str, str]:
    value = str(text or "")
    lowered = value.lower()
    updates: dict[str, str] = {}

    email = EMAIL_RE.search(value)
    if email:
        updates["email"] = email.group(0)
    phone = PHONE_RE.search(value)
    if phone and not email:
        updates["phone"] = phone.group(0)

    name = re.search(r"\bmy name is\s+([A-Za-z][\w'-]+)", value, re.I)
    if name:
        updates["name"] = name.group(1)

    family = family_of(value)
    if family != "unknown" and (not is_question(value) or not state.fields["product"].done):
        updates["product"] = FAMILY_PRODUCT.get(family, value.strip()[:60])

    use_case = use_case_from(value)
    if use_case and not is_question(value):
        updates["use_case"] = use_case

    style = normalize_style(value)
    if style and not is_question(value):
        updates["style"] = style

    if last_question == "sizes" or SIZE_DIM_RE.search(value) or SINGLE_SIZE_RE.search(value):
        pending_size = str(state.flags.get("size_pending_unit") or "").strip()
        size_match = SIZE_DIM_RE.search(value) or SINGLE_SIZE_RE.search(value)
        if last_question == "sizes" and pending_size and UNIT_ONLY_RE.match(value):
            updates["sizes"] = f"{pending_size} {value.strip()}"
        elif size_match:
            updates["sizes"] = size_match.group(0)
        elif size_is_unknown(value):
            updates["sizes"] = value.strip()[:60]

    if last_question == "quantity":
        number = parse_quantity(value)
        if number is not None and not email and not phone:
            updates["quantity"] = str(number)
    elif not email and not phone:
        number: int | None = None
        with_unit = QTY_UNIT_RE.search(value)
        if with_unit:
            number = parse_quantity(with_unit.group(0))
        elif last_question in {"", "product", "style", "finishes", "material", "extras"}:
            bare = BARE_QTY_RE.match(value)
            if bare:
                candidate = parse_quantity(bare.group(0))
                number = candidate if candidate is not None and candidate >= 100 else None
        if number is not None:
            updates["quantity"] = str(number)

    material = MATERIAL_HINTS.search(value)
    if material and len(value.split()) <= 6 and last_question != "style":
        updates.setdefault("material", material.group(0))

    finish = normalize_finish(value)
    if finish and (last_question == "finishes" or finish != "none"):
        updates["finishes"] = finish

    if last_question == "skus" or re.search(r"\b(designs?|skus?)\b", lowered):
        match = re.search(r"(\d+)\s*(?:designs?|skus?)", lowered)
        if match:
            updates["skus"] = match.group(1)
        elif last_question == "skus":
            number = parse_quantity(value)
            if number is not None:
                updates["skus"] = str(number)

    if last_question == "style":
        # A finish or material answer is not a style. Keep it as a note and let
        # the style question stand, instead of filling the field with "gloss".
        # A question ("what style of boxes do you have") is answered, not stored.
        if is_question(value):
            pass
        elif STYLE_HINTS.search(value) or (not finish and not MATERIAL_HINTS.search(value)):
            updates.setdefault("style", normalize_style(value) or value.strip()[:80])
    elif last_question in {"material", "extras", "use_case"} and not is_question(value):
        # "Yes" confirms a proposal; it does not describe what they are packing.
        if last_question != "use_case" or not AFFIRMATION_RE.fullmatch(value):
            updates.setdefault(last_question, value.strip()[:80])

    if is_plain(value):
        state.flags["plain"] = True
    if BANNER_RE.search(value):
        state.flags["banner"] = True
    return updates


def reset_attempts_for_new_turn(state: ConversationState) -> None:
    state.flags.pop("asked_this_turn", None)
