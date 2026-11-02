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
    "skus": "Designs",
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
# Open checklist slots the visitor (or live model) may leave for the team.
TO_BE_CONFIRMED = "to be confirmed"
UNCERTAIN_WAIVE_FIELDS = frozenset(
    {"sizes", "style", "finishes", "material", "skus", "extras", "use_case", "quantity"}
)

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
        ("skus", "How many total designs do you have?"),
        ("extras", "Do you want me to add a zipper and tear notch?"),
        ("material", "Do you have any specific material or special features in mind?"),
    ],
    "boxes": [
        ("sizes", "What box size are you looking for?"),
        ("style", "What style of box do you need, or can you share a reference image?"),
        (
            "finishes",
            "What finish do you prefer: matte lamination, gloss lamination, "
            "soft touch lamination, spot UV, or foil printing?",
        ),
        ("quantity", "What quantity are you looking to order for your first run?"),
        ("skus", "How many total designs do you have?"),
        ("material", "Do you have any specific material or special features in mind?"),
    ],
    "labels": [
        ("sizes", "What label size are you looking for?"),
        ("finishes", "What finish do you prefer: matte, gloss or soft touch?"),
        ("quantity", "What quantity are you looking to order for your first run?"),
        ("skus", "How many total designs do you have?"),
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
    "finishes": (
        "What finish do you prefer: matte lamination, gloss lamination, "
        "soft touch lamination, spot UV, or foil printing?"
    ),
    "skus": "How many total designs do you have?",
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
    r"^\s*(?:in(?:ch(?:es)?)?|\"|cm|mm|centimet(?:er|re)s?|millimet(?:er|re)s?"
    r"|ft|foot|feet)\s*[.!]*\s*$",
    re.I,
)
CONTACT_REFUSAL_RE = re.compile(
    r"^\s*(?:no|nope)\s*[.!]*\s*$"
    r"|\b(?:no|nope)\b[^.?!]{0,40}\b(?:want|need|give|share|provide|interested)\b"
    r"|\bdon[’'`;]?t\s+(?:want|email|call|contact)\b|\bdo\s+not\s+want\b"
    r"|\b(?:don[’'`;]?t|do\s+not|dont)\s+want\s+to\s+share\b"
    r"|\b(?:don[’'`;]?t|do\s+not|dont)\s+have\s+(?:an?\s+|any\s+)?(?:e-?mail|phone|number|contact)\b"
    r"|\bi\s+have\s+not\s+any\b"
    r"|\bhave\s+not\s+(?:any|an?\s+e-?mail|a\s+phone|a\s+number)\b"
    r"|\bnot\s+interested\b|\bno\s+thanks?(?:\s+you)?\b|\bi'?ll\s+pass\b"
    r"|\bskip\s+(?:it|that|this)\b|\bno\s+(?:email|phone|number)\b"
    r"|\bstop\s+asking\b|\bleave\s+me\s+alone\b",
    re.I,
)
UNSPECIFIED_RE = re.compile(
    r"^\s*(?:"
    r"(?:i\s+)?(?:don'?t|dont)\s+have(?:\s+(?:a|any|one))?"
    r"(?:\s+(?:reference|image|design|idea|preferences?)){0,2}"
    r"|(?:i\s+)?have\s+no\s+(?:preferences?|idea|clue|reference)"
    r"|(?:i\s+)?(?:don'?t|dont)\s+know|not\s+sure|unsure|no\s+(?:idea|clue|preferences?|reference)"
    r"|dunno|idk|no|nope|none|nothing(?:\s+specific)?|whatever|anything|any"
    r")\s*[.!]*\s*$",
    re.I,
)
SIZE_UNIT_RE = re.compile(
    r'(?:\d(?:\.\d+)?\s*(?:in|inch|inches|"|cm|mm|oz|ml|g|grams?|lb|ft)\b|\b(?:inches|centimet(?:er|re)s?|millimet(?:er|re)s?|cm|mm|oz|ml|grams?)\b)',
    re.I,
)
# Multipliers visitors type between numbers: 2x2, 2×2, 2*2, 2 by 2, 2 X 2.
DIM_SEP = r"(?:x|×|\*|by)"
SIZE_DIM_RE = re.compile(
    rf"(\d+(?:\.\d+)?)\s*{DIM_SEP}\s*(\d+(?:\.\d+)?)(?:\s*{DIM_SEP}\s*(\d+(?:\.\d+)?))?"
    rf"\s*(in(?:ch(?:es)?)?|\"|cm|mm|oz|ml|g|grams?|lb|ft)?",
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
    # Longer catalogue forms first so "matte lamination" does not collapse to "matte".
    "matte lamination": ("matte lamination",),
    "gloss lamination": ("gloss lamination",),
    "soft touch lamination": ("soft touch lamination", "soft-touch lamination"),
    "foil printing": ("foil printing", "foil stamping"),
    "spot uv": ("spot uv", "spot-uv"),
    "matte": ("matte", "matt"),
    "gloss": ("gloss", "glass", "glossy"),
    "soft touch": ("soft touch", "soft-touch", "suede"),
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
USE_CASE_TAIL = (
    r"([a-z0-9][a-z0-9 &'\-]{1,48}?)"
    r"(?=\s*(?:[,.!?]|\band\b|\bbut\b|\bso\b|\bbecause\b|\bin\b|\bwith\b|\bthat\b|\bplease\b|\bthanks\b|$))"
)
USE_CASE_NOUN_RE = re.compile(
    r"\b(?:for my|for our|to pack|packing|packed with|holds|holding|filled with|going inside|goes inside|"
    r"use case|intended for|for shipping|for storing|for sending|for mailing|for selling|for wrapping|for gifting)\s+"
    + USE_CASE_TAIL,
    re.I,
)
# Product token shared by "X for Y" / "Y X" head-noun resolution and use-case extractors.
_PRODUCT_HEAD_ALTS = (
    r"labels?|stickers?|decals?|bags?|pouch(?:es)?|mylar|boxes?|cartons?|mailers?|"
    r"banners?|signs?|business cards?|cards?"
)
# "{product} for {purpose}" — labels for whisky bottles, boxes for candles.
# Excludes "for example" / "for instance"; purpose may name another family (pizza box).
# Group 1 stays the purpose (USE_CASE_TAIL); product token is non-capturing.
USE_CASE_PRODUCT_FOR_RE = re.compile(
    r"\b(?:(?:custom|plain|blank|printed|die[- ]?cut)\s+)*"
    rf"(?:{_PRODUCT_HEAD_ALTS})\s+for\s+"
    r"(?!example\b|instance\b|now\b|sale\b|me\b|us\b|you\b)"
    + USE_CASE_TAIL,
    re.I,
)
# Head product only (group 1), for multi-family attachment: labels for … box → labels.
PRODUCT_FOR_HEAD_RE = re.compile(
    r"\b(?:(?:custom|plain|blank|printed|die[- ]?cut)\s+)*"
    rf"({_PRODUCT_HEAD_ALTS})\s+for\s+"
    r"(?!example\b|instance\b|now\b|sale\b|me\b|us\b|you\b)",
    re.I,
)
# "{purpose} {product}" — whiskey bottle label, honey jar stickers.
# Banners/signs omitted: "parking sign" is the product name, not a use case.
USE_CASE_PURPOSE_PRODUCT_RE = re.compile(
    r"\b([a-z][a-z0-9 &'\-]{1,40}?)\s+"
    r"(labels?|stickers?|decals?|bags?|pouch(?:es)?|boxes?|cartons?|mailers?|"
    r"business cards?)\b",
    re.I,
)
USE_CASE_PURPOSE_BLOCKLIST = frozenset(
    {
        "custom",
        "plain",
        "blank",
        "printed",
        "die-cut",
        "die cut",
        "mylar",
        "kraft",
        "matte",
        "gloss",
        "soft touch",
        "stand-up",
        "stand up",
        "flat",
        "flat-bottom",
        "flat bottom",
        "mailer",
        "rigid",
        "need",
        "want",
        "looking",
        "order",
        "some",
        "more",
        "new",
        "best",
        "your",
        "our",
        "my",
    }
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


def _token_family(token: str) -> str:
    """Map a short product span to one family. Does not scan purpose nouns."""
    blob = str(token or "").strip()
    if not blob:
        return "unknown"
    if BUSINESS_CARD_RE.search(blob):
        return "business_cards"
    if BANNER_RE.search(blob):
        return "banners"
    if LABEL_RE.search(blob):
        return "labels"
    if BAG_RE.search(blob):
        return "bags"
    if BOX_RE.search(blob):
        return "boxes"
    if PRINT_RE.search(blob):
        return "print"
    return "unknown"


def family_candidates(product: str = "", texts: tuple[str, ...] = ()) -> list[str]:
    """Product families mentioned, in left-to-right order. Empty when none."""
    blob = " ".join([product, *texts]).strip()
    if not blob:
        return []
    hits: list[tuple[int, str]] = []
    for regex, family in (
        (BUSINESS_CARD_RE, "business_cards"),
        (BANNER_RE, "banners"),
        (LABEL_RE, "labels"),
        (BAG_RE, "bags"),
        (BOX_RE, "boxes"),
        (PRINT_RE, "print"),
    ):
        for match in regex.finditer(blob):
            hits.append((match.start(), family))
    hits.sort(key=lambda item: item[0])
    ordered: list[str] = []
    for _start, family in hits:
        if family not in ordered:
            ordered.append(family)
    return ordered


def headed_product_family(text: str) -> str:
    """Head noun when one product is ordered and another appears only as purpose.

    `labels for my pizza box` / `pizza box labels` → labels, not boxes.
    `boxes and labels` stays unresolved (conjunction, not purpose+product).
    """
    value = str(text or "")
    if not value.strip():
        return "unknown"
    product_for = PRODUCT_FOR_HEAD_RE.search(value)
    if product_for:
        headed = _token_family(product_for.group(1))
        if headed != "unknown":
            return headed
    purpose_product = USE_CASE_PURPOSE_PRODUCT_RE.search(value)
    if purpose_product:
        purpose = purpose_product.group(1)
        # "boxes and labels" / "bags or boxes" — two products, not purpose+head.
        if re.search(r"\b(?:and|or|vs\.?|versus)\b", purpose, re.I):
            return "unknown"
        headed = _token_family(purpose_product.group(2))
        if headed != "unknown":
            return headed
    return "unknown"


def family_of(product: str = "", texts: tuple[str, ...] = ()) -> str:
    blob = " ".join([product, *texts]).strip()
    if not blob:
        return "unknown"
    # Banners / business cards win as whole-product lines (unchanged priority).
    if BANNER_RE.search(blob):
        return "banners"
    if BUSINESS_CARD_RE.search(blob):
        return "business_cards"
    unique = family_candidates(product, texts)
    # family_candidates also records banners/cards; drop them here — already handled.
    unique = [name for name in unique if name not in {"banners", "business_cards"}]
    if len(unique) == 1:
        return unique[0]
    if not unique:
        return "unknown"
    headed = headed_product_family(blob)
    if headed != "unknown" and headed in unique:
        return headed
    return "unknown"


def product_disambiguation_question(candidates: list[str]) -> str:
    """Hybrid confirm when several families appear with no clear head noun."""
    labels = [FAMILY_PRODUCT.get(name, name.replace("_", " ")) for name in candidates[:3]]
    if not labels:
        return PRODUCT_QUESTION
    if len(labels) == 1:
        return f"Just to confirm — are you looking for {labels[0]}?"
    if len(labels) == 2:
        return f"Just to confirm — are you looking for {labels[0]}, or {labels[1]}?"
    leading = ", ".join(labels[:-1])
    return f"Just to confirm — are you looking for {leading}, or {labels[-1]}?"


def is_plain(text: str) -> bool:
    return bool(PLAIN_RE.search(str(text or "")))


def size_has_unit(text: str) -> bool:
    return bool(SIZE_UNIT_RE.search(str(text or "")))


def size_is_unknown(text: str) -> bool:
    return bool(SIZE_UNKNOWN_RE.search(str(text or "")))


def is_to_be_confirmed(value: str) -> bool:
    """True when a field is explicitly left for the team (LLM or size-unknown path)."""
    folded = re.sub(r"\s+", " ", str(value or "").strip().lower())
    return folded in {
        TO_BE_CONFIRMED,
        "tbc",
        "needs confirmation",
        "to-be-confirmed",
        "needs_confirmation",
    }


# Numeric / freeform fields: no catalogue menu — non-answers defer to the team.
SHAPED_DEFER_FIELDS = frozenset({"sizes", "quantity", "skus"})
# Catalogue fields: non-answers get an options list (not phrase matching, not TBC).
CATALOGUE_OPTION_FIELDS = frozenset({"style", "material", "finishes"})


def field_shaped_attempt(key: str, visitor: str) -> bool:
    """True when the message looks like a real attempt to answer this field."""
    value = str(visitor or "").strip()
    if not value:
        return False
    if key == "sizes":
        # Concrete size only. "not sure" / "no preference" are waivers handled by
        # extract or defer — they must not look like a finished size answer.
        size_text = normalise_dimension_separators(value)
        return bool(
            SIZE_DIM_RE.search(size_text)
            or SINGLE_SIZE_RE.search(value)
            or UNIT_ONLY_RE.match(value)
        )
    if key == "quantity":
        return parse_quantity(value) is not None or bool(BARE_QTY_RE.match(value))
    if key == "finishes":
        return normalize_finish(value) is not None
    if key == "material":
        return bool(MATERIAL_HINTS.search(value))
    if key == "style":
        return bool(normalize_style(value) or STYLE_HINTS.search(value))
    if key == "skus":
        return bool(re.search(r"\d+", value))
    return False


def fields_asked_in_bot_text(text: str) -> list[str]:
    """Checklist fields a bot message appears to ask about (may be more than one)."""
    from .guards import all_asked_fields

    return [key for key in all_asked_fields(text) if key in SHAPED_DEFER_FIELDS]


def _visitor_side_turn(text: str) -> bool:
    """True for greetings, meta, bare acks — not a field answer or options ask."""
    value = str(text or "").strip()
    if not value:
        return True
    if is_visitor_greeting(value) or is_goodbye(value):
        return True
    if is_context_question(value) or is_meta_question(value) or wants_human(value):
        return True
    if asks_to_share_reference(value) or asks_if_bot(value):
        return True
    if AFFIRMATION_RE.fullmatch(value) or re.fullmatch(
        r"\s*(?:hm+|h+m+|ok(?:ay)?|alright|right|got it|cool|thanks?)\s*[.!]?\s*",
        value,
        re.I,
    ):
        return True
    return False


def needs_catalogue_options(
    state: "ConversationState",
    visitor: str,
    accepted: dict[str, str],
) -> str:
    """Open style/material/finish + no concrete pick → list options (any wording).

    Dynamic: does not require \"give me options\" / \"choices\". A catalogue
    question that was not answered with a named option gets the menu.
    """
    key = str(state.last_question or "").strip()
    if key not in CATALOGUE_OPTION_FIELDS:
        return ""
    if key in accepted or state.fields[key].done:
        return ""
    text = str(visitor or "").strip()
    if not text or _visitor_side_turn(text):
        return ""
    if UNSPECIFIED_RE.match(text):
        # "not sure" / "no preference" → waiver path, not a catalogue dump.
        return ""
    if field_shaped_attempt(key, text):
        return ""
    from . import canon
    from .guards import question_as_answer

    if question_as_answer(text, key) or canon.topics_to_answer(text):
        return ""
    if is_question(text) and not is_option_request(text) and not wants_recommendation(text):
        # Real question for us (MOQ, address, …) — answer that path instead.
        return ""
    return key


def defer_unanswered_open_field(
    state: "ConversationState",
    visitor: str,
    accepted: dict[str, str],
) -> list[str]:
    """If they were asked size/qty/SKUs and did not answer, waive as to-be-confirmed.

    Catalogue fields (style/material/finish) are not deferred here — those use
    needs_catalogue_options so any non-pick wording gets a menu, not a hardcode list.
    """
    text = str(visitor or "").strip()
    if not text or _visitor_side_turn(text):
        return []
    if is_question(text):
        return []
    if is_option_request(text) or wants_recommendation(text):
        return []
    if needs_catalogue_options(state, text, accepted):
        return []

    primary = str(state.last_question or "").strip()
    candidates: list[str] = []
    if primary in SHAPED_DEFER_FIELDS:
        candidates.append(primary)
    for key in fields_asked_in_bot_text(state.last_bot()):
        if key in SHAPED_DEFER_FIELDS and key not in candidates:
            candidates.append(key)
    if not candidates:
        return []

    from . import canon
    from .guards import question_as_answer

    if any(question_as_answer(text, key) for key in candidates) or canon.topics_to_answer(text):
        return []
    if any(field_shaped_attempt(key, text) for key in candidates):
        return []
    if any(other not in candidates for other in accepted):
        return []

    deferred: list[str] = []
    for key in candidates:
        if key in accepted or state.fields[key].done:
            continue
        state.set_field(
            key,
            TO_BE_CONFIRMED,
            BASIS_VISITOR,
            raw=text,
            status=STATUS_WAIVED,
        )
        if key == "sizes":
            state.flags.pop("size_pending_unit", None)
            state.flags.pop("unit_asked", None)
        accepted[key] = TO_BE_CONFIRMED
        deferred.append(key)
    return deferred


def size_has_zero_dimension(text: str) -> bool:
    """True when width, length, or depth is zero.

    `0x0` is not the only impossible size. `0x15`, `10x0x5`, and a bare `0`
    are the same failure: a dimension of zero cannot be made.
    """
    value = re.sub(r"\s+", " ", str(text or "")).strip(" .,;")
    if not value:
        return False
    value = normalise_dimension_separators(value)
    numbers: list[str] = []
    match = SIZE_DIM_RE.search(value)
    if match:
        numbers = [item for item in match.groups()[:3] if item]
    else:
        folded = re.sub(r'(?<=\d)\s*"', " ", value)
        dim = DIM_SET_RE.match(folded)
        if dim:
            numbers = [item for item in (dim.group(1), dim.group(2), dim.group(3)) if item]
            tail = (dim.group(4) or "").strip()
            # "A4" and prose do not start with a digit. A leftover word after one
            # number ("2 count") is not a size, so it is not a zero dimension.
            if not dim.group(2) and tail and not _canonical_unit(tail):
                return False
        elif re.fullmatch(r"0+(?:\.0+)?", value):
            return True
    try:
        return any(float(item) == 0 for item in numbers)
    except ValueError:
        return False


def refuses_contact(text: str) -> bool:
    return bool(CONTACT_REFUSAL_RE.search(str(text or "")))


def contact_fields_refused(text: str, last_question: str) -> bool:
    """A refusal to give contact details, not a question about ours.

    "I have not any" only counts while email or phone is the open question.
    "I don't have an email" and "I don't want to share" count on their own.
    """
    value = str(text or "")
    if EMAIL_RE.search(value):
        return False
    if not refuses_contact(value):
        return False
    if last_question in {"email", "phone", "name"}:
        return True
    return bool(re.search(r"\b(?:e-?mail|phone|number|contact|share)\b", value, re.I))


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
    rf"^(\d+(?:\.\d+)?)"
    rf"(?:\s*{DIM_SEP}\s*(\d+(?:\.\d+)?))?"
    rf"(?:\s*{DIM_SEP}\s*(\d+(?:\.\d+)?))?"
    rf"(?:\s*(.+))?$",
    re.I,
)
# *, ×, and the word "by" between digits → a plain x, so extraction and
# normalisation share one shape before the LxW regex runs.
DIM_SEP_NORMALIZE_RE = re.compile(
    rf"(?<=\d)\s*(?:×|\*|\bby\b)\s*(?=\d)",
    re.I,
)


def normalise_dimension_separators(text: str) -> str:
    """Fold *, ×, and 'by' between numbers into x (e.g. 2*2 → 2x2, 2 by 2 → 2x2)."""
    return DIM_SEP_NORMALIZE_RE.sub("x", str(text or ""))


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
    value = normalise_dimension_separators(value)
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


def _use_case_phrase(raw: str, *, allow_packaging_nouns: bool = False) -> str:
    phrase = re.sub(r"\s+", " ", str(raw or "")).strip(" .,;:")
    words = [word for word in phrase.lower().split() if word not in USE_CASE_STOP_WORDS]
    if not words:
        return ""
    cleaned = " ".join(words)
    # A bare product family ("boxes", "coffee bags") is the product, not the use case —
    # unless it is the purpose after an ordered head product (labels for pizza box).
    if not allow_packaging_nouns:
        if family_of(phrase) != "unknown" or family_of(cleaned) != "unknown":
            return ""
    return cleaned[:60]


def use_case_from(text: str) -> str:
    """What it is for: the thing going inside, or the channel it sells through."""
    value = str(text or "")
    # When the message orders a head product (`labels for …`), keep purpose nouns
    # even if they name another family (pizza box, shipping bags). Prefer the
    # `{product} for {purpose}` span over `for shipping …` so "stickers for
    # shipping bags" keeps "shipping bags", not a bare "bags".
    headed = headed_product_family(value)
    if headed != "unknown":
        product_for = USE_CASE_PRODUCT_FOR_RE.search(value)
        if product_for:
            phrase = _use_case_phrase(product_for.group(1), allow_packaging_nouns=True)
            if phrase:
                return phrase
    noun = USE_CASE_NOUN_RE.search(value)
    if noun:
        phrase = _use_case_phrase(noun.group(1), allow_packaging_nouns=False)
        if phrase:
            return phrase
    product_for = USE_CASE_PRODUCT_FOR_RE.search(value)
    if product_for:
        phrase = _use_case_phrase(product_for.group(1), allow_packaging_nouns=False)
        if phrase:
            return phrase
    purpose = USE_CASE_PURPOSE_PRODUCT_RE.search(value)
    if purpose and not re.search(r"\b(?:and|or|vs\.?|versus)\b", purpose.group(1), re.I):
        phrase = _use_case_phrase(purpose.group(1), allow_packaging_nouns=True)
        words = phrase.split() if phrase else []
        lead_blocked = {
            "i",
            "we",
            "you",
            "looking",
            "need",
            "want",
            "order",
            "get",
            "buy",
            "make",
            "print",
            "custom",
            "plain",
            "blank",
            "printed",
        }
        if (
            phrase
            and phrase not in USE_CASE_PURPOSE_BLOCKLIST
            and words
            and not any(word in lead_blocked for word in words)
            and not all(word in USE_CASE_PURPOSE_BLOCKLIST for word in words)
        ):
            return phrase
    channel = USE_CASE_CHANNEL_RE.search(value)
    if channel:
        return re.sub(r"\s+", " ", channel.group(0).lower())[:60]
    return ""


def field_ask_name(key: str) -> str:
    """Prompt-facing field name: underscores become spaces so the model never says use_case."""
    return str(key or "").replace("_", " ")


def field_clarify_phrase(key: str) -> str:
    """Natural phrase for 'I couldn't make out …' — never 'the What it is for'."""
    phrases = {
        "use_case": "what this is for",
        "sizes": "the size",
        "quantity": "the quantity",
        "style": "the style",
        "finishes": "the finish",
        "material": "the material",
        "skus": "how many designs",
        "product": "which product",
        "extras": "the extras",
        "name": "the name",
        "email": "the email",
        "phone": "the phone number",
    }
    return phrases.get(key, f"the {field_ask_name(key)}")


def continue_ask(state: "ConversationState") -> tuple[str, str] | None:
    """Prefer the question already on the table when it is still askable."""
    last = str(state.last_question or "").strip()
    if last == "sizes" and state.size_needs_unit():
        question = state.question_for("sizes")
        return ("sizes", question) if question else None
    if last and last in state.ask_set():
        question = state.question_for(last)
        if question:
            return last, question
    return state.next_question()


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


VISITOR_GREETING_RE = re.compile(
    r"^\s*(?:good\s+(?:morning|afternoon|evening|day)|morning|afternoon|evening|hi|hello|hey)"
    r"(?:\s+there)?\s*[!.]*\s*$",
    re.I,
)


def is_visitor_greeting(text: str) -> bool:
    """The whole message is a hello. It is not a product, a size, or any other answer."""
    return bool(VISITOR_GREETING_RE.match(str(text or "").strip()))


def greeting_ack(text: str) -> str:
    value = str(text or "").lower()
    if "afternoon" in value:
        return "Good afternoon."
    if "evening" in value:
        return "Good evening."
    if "morning" in value:
        return "Good morning."
    return "Hello."


# Only a disambiguation of the question already asked. "Which one?", "for example?"
# and "what do you have?" are option requests and go to the model or the catalogue
# fallback, not this shortcut.
CONTEXT_QUESTION_RE = re.compile(
    r"\bfor (?:what|which|whom)\b"
    r"|\b(?:bags?|boxes?|labels?|pouches?)\s+(?:or|vs\.?|versus)\s+(?:bags?|boxes?|labels?|pouches?)\b",
    re.I,
)
OPTION_REQUEST_RE = re.compile(
    r"\bfor example\b|\bwhat do you have\b|\bwhich ones?\b"
    r"|\b(?:which|what)\s+(?:options?|choices?)\b"
    r"|\bgive\s+(?:me\s+)?(?:the\s+|some\s+|your\s+|a\s+few\s+)?(?:options?|choices?)\b"
    r"|\bshow\s+(?:me\s+)?(?:the\s+|some\s+|your\s+)?(?:options?|choices?)\b"
    r"|\blist\s+(?:the\s+|some\s+|your\s+)?(?:options?|choices?)\b"
    r"|\b(?:options?|choices?)\s+please\b"
    r"|^\s*(?:options?|choices?)\s*[?!.]*\s*$"
    r"|\b(?:any|some|the)\s+(?:options?|choices?)\b"
    r"|\bwhat\s+(?:are\s+)?(?:my|the|our)\s+(?:options?|choices?)\b"
    r"|\b(?:other|alternative)\s+materials?\b"
    r"|\bmaterials?\s+other\s+than\b"
    r"|\bsuggest\s+(?:me\s+)?(?:other\s+|alternative\s+)?materials?\b"
    r"|\b(?:suggest|recommend)\s+(?:me\s+)?(?:the\s+|some\s+|a\s+few\s+)?"
    r"(?:styles?|kinds?|types?|finishes?|options?|choices?)\b"
    r"|\b(?:styles?|kinds?|types?|finishes?)\s+(?:you\s+)?(?:suggest|recommend|offer|have)\b"
    r"|\blist\s+(?:the\s+|some\s+)?(?:styles?|finishes?|options?|choices?)\b"
    r"|\bshow\s+(?:me\s+)?(?:the\s+|some\s+)?(?:styles?|finishes?|options?|choices?)\b",
    re.I,
)
# "Can I add a reference image?" is not an answer and not an artwork-format ask.
REFERENCE_SHARE_RE = re.compile(
    r"\b(?:can i|can we|could i|may i|should i|want to|wanna|let me|"
    r"i(?:'d| would)? like to|is it (?:ok|okay|possible) to)\b"
    r".{0,48}\b(?:add|attach|send|share|upload|provide|include)\b"
    r".{0,48}\b(?:reference|image|photo|picture|artwork|design|file|mockup)\b"
    r"|\b(?:attach|upload|share|send)\b.{0,24}\b(?:a |an |my |the )?"
    r"(?:reference|image|photo|picture|artwork|design|file|mockup)\b"
    r"|\breference image\b",
    re.I,
)


def is_context_question(text: str) -> bool:
    value = str(text or "")
    return is_question(value) and bool(CONTEXT_QUESTION_RE.search(value))


def is_option_request(text: str) -> bool:
    return bool(OPTION_REQUEST_RE.search(str(text or "")))


def asks_to_share_reference(text: str) -> bool:
    """Visitor wants to attach a reference image — invite them, do not ignore."""
    return bool(REFERENCE_SHARE_RE.search(str(text or "")))


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
        product = str(self.fields["product"].value or "").strip()
        if product:
            # Canonical keys / labels (vision and registry) must resolve even when
            # family_of() only matches visitor phrases like "flyer", not "print".
            key = product.lower().replace(" ", "_")
            if key in FAMILIES and key != "unknown":
                return key
            lowered = product.lower()
            for family_key, label in FAMILY_PRODUCT.items():
                if lowered == label or lowered == family_key.replace("_", " "):
                    return family_key
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
        # No design count yet: the single-design minimum is 1,000.
        return qty < 1000

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

    def product_details_open(self) -> bool:
        """Style, material, finish, designs, and extras are still missing for this family."""
        if self.family() == "unknown":
            return True
        family_fields = {key for key, _question in self.script()}
        for key in ("style", "material", "finishes", "skus", "extras"):
            if key not in family_fields:
                continue
            if key == "skus" and self.is_plain():
                continue
            value = self.fields[key]
            if value.status == STATUS_SUGGESTED or value.done or value.attempts >= 2:
                continue
            return True
        return False

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
            # Designs, material and finish come before anyone is asked for an email.
            if self.product_details_open():
                return False
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
            # A vision/model product proposal still needs a yes/no turn; treat it
            # as askable so the chat does not empty the ask-set and stall.
            product = self.fields["product"]
            if product.status == STATUS_SUGGESTED and product.value:
                return ["product"]
            return []
        blocking_open = self.blocking_open()
        family_fields = {key for key, _question in self.script()}
        keys = [
            key
            for key in ASK_PRIORITY
            if key in self.fields and self._askable(key, blocking_open, family_fields)
        ]
        # Suggested slots wait on yes/no. Keep them askable so a confirm reply
        # ("Are you looking for print products…?") is on-script, not a stall warn.
        for key in ("product", "style", "finishes", "material"):
            value = self.fields.get(key)
            if (
                value
                and value.status == STATUS_SUGGESTED
                and value.value
                and key not in keys
            ):
                keys.insert(0, key)
        return keys

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
        ask = (
            ", ".join(field_ask_name(key) for key in allowed)
            if allowed
            else "(nothing — do not ask a new question)"
        )
        denied = self.do_not_ask()
        if denied:
            parts = []
            for key, words in denied:
                shown = words.replace('"', "'")
                if len(shown) > 80:
                    shown = shown[:77] + "..."
                parts.append(f'{field_ask_name(key)} (they said "{shown}")')
            deny = ", ".join(parts)
        else:
            deny = "(nothing yet)"
        lines = [f"You may ask about: {ask}.", f"Do not ask about: {deny}."]
        locked = [key for key, _words in denied if key in {"style", "finishes"}]
        if locked:
            lines.append(
                "Locked, already accepted: "
                + ", ".join(field_ask_name(key) for key in locked)
                + ". Do not ask about them again, and do not put them in fields_proposed or proposed_configs."
            )
        if "sizes" in allowed and self.size_needs_unit():
            lines.append(f"Size unit question, verbatim: {self.question_for('sizes')}")
        return "\n".join(lines)

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
            size = str(self.fields["sizes"].value or "").strip()
            return f"Is {size} in inches, cm, or mm?"
        if key == "sizes":
            preferred = str(self.flags.get("size_preferred_unit") or "").strip()
            if preferred:
                unit_word = {
                    "ft": "feet",
                    "in": "inches",
                    "cm": "cm",
                    "mm": "mm",
                }.get(preferred, preferred)
                return f"What size do you need in {unit_word}? For example 3x6."
        for field_key, question in self.script():
            if field_key == key:
                return question
        return FALLBACK_QUESTIONS.get(key, "")

    def repair_fields(self) -> list[str]:
        # Older turns could store the visitor's question or a material-options
        # ask in a free-text field. Clear those so the field can be asked again.
        repaired: list[str] = []
        for key in ("style", "material", "extras"):
            field_value = self.fields[key]
            stored = str(field_value.value or "")
            if not stored:
                continue
            bad = is_question(stored) or (
                key == "material"
                and (wants_recommendation(stored) or is_option_request(stored))
            )
            if not bad:
                continue
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
        """Close size asks that cannot progress, so the chat does not empty and stall.

        - Unit follow-up already asked once → waive the number for the team.
        - Two failed size asks with no value → same waiver (team confirms size).
        """
        noted: list[str] = []
        sizes = self.fields["sizes"]
        if self.size_needs_unit() and self.flags.get("unit_asked"):
            sizes.status = STATUS_WAIVED
            noted.append("sizes")
        elif (
            not sizes.value
            and sizes.status == STATUS_UNKNOWN
            and sizes.attempts >= 2
        ):
            self.set_field(
                "sizes",
                "to be confirmed",
                BASIS_VISITOR,
                raw="",
                status=STATUS_WAIVED,
            )
            noted.append("sizes")
        return noted

    def next_contact_question(self) -> tuple[str, str] | None:
        if self.product_details_open():
            return None
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
            # Attempt budget spent and not settled: leave the ask-set, not the Missing noise.
            if key == "use_case" and value.attempts >= 2 and not value.done:
                continue
            if key in BLOCKING_FIELDS:
                missing.append(f"{FIELD_LABELS[key]} (blocking)")
            elif key == "use_case":
                missing.append(f"{FIELD_LABELS[key]} (needed for a recommendation)")
            elif key in CONTACT_FIELDS:
                if self.product_details_open():
                    continue
                if not self.reachable() and key != "name":
                    missing.append(FIELD_LABELS[key])
            elif key in relevant:
                if value.attempts >= 2 and key in AFTER_BLOCKING_FIELDS:
                    continue
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
            lines.append("Plain/unprinted order: do not ask for designs.")
        offer_for = str(self.flags.get("offer_options_for") or "").strip()
        if offer_for in CATALOGUE_OPTION_FIELDS:
            lines.append(
                f"offer_options_for={offer_for}: visitor did not pick a concrete "
                f"{offer_for}; list that field's catalogue options now and keep asking it."
            )
        if self.flags.get("reference_image"):
            note = str(self.flags.get("reference_summary") or "").strip()
            if note:
                lines.append(
                    "Visitor shared a reference image (on file for this chat): "
                    f"{note} "
                    "Keep using it as context. Do not ask them to re-send artwork "
                    "or describe the same design again unless they offer a new image."
                )
            else:
                lines.append(
                    "Visitor shared a reference image (on file for this chat). "
                    "Do not ask them to re-send artwork unless they offer a new image."
                )
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
        # "boxes, bags, labels, or something else" is the menu, not a choice.
        # "or" is also inside the word "morning", so a substring check is not enough.
        wanted = family_of(candidate)
        return wanted != "unknown" and family_of(visitor) == wanted
    if key in {"style", "material", "extras", "name", "use_case"}:
        if is_question(candidate) or QUESTION_START_RE.match(candidate.strip()):
            return False
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
    if is_visitor_greeting(visitor_text):
        return accepted, rejected
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
        # Catalogue style/material/finish named by the model is a proposal, not a
        # settled customer fact — otherwise "PP white vinyl" locks in on a qty/SKU
        # turn with raw_visitor_text stolen from "300" / "not sure".
        if (
            source == "model"
            and key in CATALOGUE_OPTION_FIELDS
            and not echoed
            and basis != BASIS_VISITOR
        ):
            basis = BASIS_MODEL
        # `raw_visitor_text` is the customer's own wording. A model proposal they
        # have not agreed to has no wording of theirs to carry yet.
        raw_text = incoming if echoed else ("" if basis == BASIS_MODEL else str(visitor_text or "").strip())
        if not value:
            continue
        if key in {"email", "phone"} and incoming == "declined" and refuses_contact(visitor_text):
            state.set_field(key, "declined", BASIS_VISITOR, raw=visitor_text, status=STATUS_WAIVED)
            accepted[key] = "declined"
            continue
        # Uncertainty waiver: only for the field we just asked. A live model that
        # stamps sizes="to be confirmed" while the visitor answered use case
        # ("coffee beans") must not close size early.
        if key in UNCERTAIN_WAIVE_FIELDS and is_to_be_confirmed(value):
            if key != state.last_question:
                rejected[key] = value
                continue
            state.set_field(
                key,
                TO_BE_CONFIRMED,
                BASIS_VISITOR,
                raw=str(visitor_text or "").strip(),
                status=STATUS_WAIVED,
            )
            if key == "sizes":
                state.flags.pop("size_pending_unit", None)
                state.flags.pop("unit_asked", None)
            accepted[key] = TO_BE_CONFIRMED
            continue
        if key in PROSE_FIELDS and looks_like_contact(value):
            rejected[key] = value
            continue
        if key in PROSE_FIELDS and (is_question(value) or QUESTION_START_RE.match(value)):
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
            # "pizza" is what they are packing, not a box style. Keep a free-text
            # answer only when style is the question they were just asked.
            if (
                not normalized_style
                and not STYLE_HINTS.search(value)
                and not UNSPECIFIED_RE.search(visitor_text)
                and (state.last_question != "style" or basis != BASIS_VISITOR)
            ):
                rejected[key] = value
                continue
            if normalized_style:
                value = normalized_style
        if key == "material" and basis == BASIS_VISITOR and (
            is_question(visitor_text)
            or wants_recommendation(visitor_text)
            or is_option_request(visitor_text)
        ):
            # An alternatives ask is not a material choice — even when it names
            # vinyl while asking for something other than vinyl.
            material_match = MATERIAL_HINTS.search(value)
            if (
                not material_match
                or wants_recommendation(visitor_text)
                or is_option_request(visitor_text)
            ):
                rejected[key] = value
                continue
            value = material_match.group(0)
        if key == "extras" and is_question(visitor_text) and basis == BASIS_VISITOR:
            if value.lower() not in {"yes", "no", "none", "both", "neither"}:
                rejected[key] = value
                continue
        if key == "sizes":
            if size_has_zero_dimension(value):
                rejected[key] = value
                continue
            value = normalise_size(value)
            if size_has_zero_dimension(value):
                rejected[key] = value
                continue
            pending_size = str(state.flags.get("size_pending_unit") or "").strip()
            if pending_size and UNIT_ONLY_RE.match(str(visitor_text or "")):
                value = normalise_size(f"{pending_size} {str(visitor_text).strip()}")
                # The remembered words are the size plus the unit, never the unit alone.
                raw_text = value
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
            looks_like_size = bool(
                SIZE_DIM_RE.search(normalise_dimension_separators(visitor_text))
            ) and not re.search(
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
        # Settled answers stay put. A later size/quantity turn (or a model echo)
        # must not clear or rewrite product, use_case, or any other stated field.
        # Refinement is allowed only while that field is the open question.
        existing = state.fields[key]
        if existing.stated and state.last_question != key:
            refining_size_unit = (
                key == "sizes"
                and state.size_needs_unit()
                and (size_has_unit(value) or size_has_unit(visitor_text))
            )
            if not refining_size_unit:
                rejected[key] = value
                continue
        if (
            key in {"style", "finishes"}
            and basis == BASIS_CATALOGUE
            and not traceable(key, value, visitor_text, state)
        ):
            rejected[key] = value
            continue
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


def extract_fields(
    text: str,
    last_question: str,
    state: ConversationState,
    registry=None,
) -> dict[str, str]:
    value = str(text or "")
    lowered = value.lower()
    # Size probes fold *, ×, and "by" to x so 2*2 / 2 by 2 match like 2x2.
    size_text = normalise_dimension_separators(value)
    updates: dict[str, str] = {}
    if is_visitor_greeting(value):
        return updates

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

    if last_question == "sizes" or SIZE_DIM_RE.search(size_text) or SINGLE_SIZE_RE.search(value):
        pending_size = str(state.flags.get("size_pending_unit") or "").strip()
        size_match = SIZE_DIM_RE.search(size_text) or SINGLE_SIZE_RE.search(value)
        if last_question == "sizes" and pending_size and UNIT_ONLY_RE.match(value):
            updates["sizes"] = f"{pending_size} {value.strip()}"
        elif (
            last_question == "sizes"
            and UNIT_ONLY_RE.match(value)
            and not size_match
            and not pending_size
        ):
            # "feet" / "inches" alone = preferred unit, not a finished size answer.
            unit = _canonical_unit(value.strip().strip("."))
            if unit:
                state.flags["size_preferred_unit"] = unit
                # Unit preference is progress; do not burn the size attempt budget.
                state.fields["sizes"].attempts = min(state.fields["sizes"].attempts, 1)
        elif size_match and not size_has_zero_dimension(size_match.group(0)):
            updates["sizes"] = size_match.group(0)
        elif size_match or (last_question == "sizes" and size_has_zero_dimension(size_text)):
            # A zero dimension is not a size. Leave the field empty so it is asked again.
            pass
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
    # A material said while we were asking for a style is still the material.
    # An alternatives ask that happens to name vinyl is not choosing vinyl.
    if (
        material
        and len(value.split()) <= 6
        and not wants_recommendation(value)
        and not is_option_request(value)
    ):
        word = material.group(0).lower()
        if word == "metallized":
            word = "metalized"
        updates.setdefault("material", word)

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
        # Only a named catalogue style counts. Freeform / "batao kya hai" /
        # "give me options" stays open so needs_catalogue_options can list the menu.
        if not (
            is_question(value)
            or is_option_request(value)
            or wants_recommendation(value)
            or finish
            or MATERIAL_HINTS.search(value)
        ):
            shaped = normalize_style(value)
            if shaped:
                updates.setdefault("style", shaped)
            elif STYLE_HINTS.search(value):
                updates.setdefault("style", value.strip()[:80])
    elif last_question in {"extras", "use_case"} and not is_question(value):
        # material/finishes: only via MATERIAL_HINTS / normalize_finish above —
        # never store arbitrary wording as the pick.
        if last_question == "extras" and (
            wants_recommendation(value) or is_option_request(value)
        ):
            pass
        # "Yes" confirms a proposal; it does not describe what they are packing.
        elif last_question != "use_case" or not AFFIRMATION_RE.fullmatch(value):
            if not (last_question == "use_case" and is_option_request(value)):
                updates.setdefault(last_question, value.strip()[:80])

    if (
        registry is not None
        and not is_question(value)
        and not wants_recommendation(value)
        and not is_option_request(value)
        and len(value.split()) <= 8
    ):
        for field_name, canonical in registry.vocabulary_hits(value, state.family()):
            # Naming the product ("mylar bags") is not choosing a style. A style
            # hit counts only while that question is the one on the table.
            if field_name == "style" and last_question != "style":
                continue
            updates.setdefault(field_name, canonical)
    if last_question == "style" and not normalize_style(value) and not STYLE_HINTS.search(value):
        if any(updates.get(key) for key in ("material", "finishes", "extras")):
            raw_style = str(updates.get("style") or "")
            if raw_style.lower() == value.strip().lower():
                updates.pop("style", None)

    if last_question in UNCERTAIN_WAIVE_FIELDS and UNSPECIFIED_RE.match(value):
        # Unsure / no preference / whatever — on the open field, including size.
        # Style/material keep the legacy "no preference" token; everything else
        # (sizes, finishes, use_case, …) is "to be confirmed" for the team.
        # "no preference" must not be stolen as a finish while size is open.
        updates.pop("finishes", None)
        if last_question in {"style", "material"}:
            updates[last_question] = "no preference"
        else:
            updates[last_question] = TO_BE_CONFIRMED

    if contact_fields_refused(value, last_question):
        for key in ("email", "phone"):
            if not state.fields[key].done:
                updates[key] = "declined"

    if is_plain(value):
        state.flags["plain"] = True
    if BANNER_RE.search(value):
        state.flags["banner"] = True
    return updates


def reset_attempts_for_new_turn(state: ConversationState) -> None:
    state.flags.pop("asked_this_turn", None)
