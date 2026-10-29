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
WANTS_HUMAN = re.compile(
    r"\b(human|person|agent|representative|rep\b|real (?:person|human)|someone else|speak to (?:a|an|someone|sales|support|rep)|talk to (?:a|an|someone|sales|support|rep)|operator|manager|customer service|live support|live chat|live agent)\b"
    r"|\b(?:don'?t|do not|not|no|stop|hate)\s+(?:want\s+to\s+)?(?:talk(?:ing)?\s*(?:to)?\s+|speak(?:ing)?\s*(?:to)?\s+|chat(?:ting)?\s*(?:with)?\s+)?(?:an?\s+)?(?:ai|bot|robo[a-z]*t|automated|machine)\b"
    r"|\b(?:are you|is this)\s+(?:an?\s+)?(?:ai|bot|robot)\b",
    re.I,
)
ASKS_IF_BOT = re.compile(
    r"\b(?:are you|r u|is this|am i (?:talking|speaking|chatting) (?:to|with))\s+(?:an?\s+|the\s+)?(?:real\s+)?(?:ai|bot|robo[a-z]*t|chat ?bot|automated|machine|human|person)\b",
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


def tidy_size(text: str) -> str:
    return re.sub(r"\s+", " ", str(text)).strip(" .,;")[:60]


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
    value: str = ""
    status: str = "missing"
    attempts: int = 0
    source: str = ""

    @property
    def done(self) -> bool:
        return self.status in {"answered", "needs_confirmation"} and bool(self.value)

    def to_dict(self) -> dict:
        return {
            "value": self.value,
            "status": self.status,
            "attempts": self.attempts,
            "source": self.source,
        }

    @classmethod
    def from_dict(cls, data: dict | None) -> "FieldValue":
        data = data or {}
        return cls(
            value=str(data.get("value", "")),
            status=str(data.get("status", "missing")),
            attempts=int(data.get("attempts", 0)),
            source=str(data.get("source", "")),
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

    def set_field(self, key: str, value: str, source: str = "visitor") -> None:
        if key not in self.fields:
            self.fields[key] = FieldValue()
        self.fields[key].value = str(value).strip()
        self.fields[key].source = source

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
        return True

    def complete(self) -> bool:
        return self.specs_done() and self.reachable()

    def script(self) -> list[tuple[str, str]]:
        family = self.family()
        return SCRIPTS.get(family, [])

    def question_for(self, key: str) -> str:
        if key == "sizes":
            sizes = self.fields["sizes"]
            if (
                sizes.value
                and not sizes.done
                and not size_is_unknown(sizes.value)
                and not size_has_unit(sizes.value)
            ):
                return "Is that in inches, cm or mm?"
        for field_key, question in self.script():
            if field_key == key:
                return question
        return ""

    def repair_fields(self) -> list[str]:
        # Older turns could store the visitor's question in a free-text field
        # (style, material, extras). Clear those values so the script re-asks.
        repaired: list[str] = []
        for key in ("style", "material", "extras"):
            field_value = self.fields[key]
            if field_value.value and is_question(field_value.value):
                field_value.value = ""
                field_value.status = "missing"
                field_value.attempts = min(field_value.attempts, 1)
                repaired.append(key)
        return repaired

    def next_question(self) -> tuple[str, str] | None:
        if self.handoff:
            return None
        family = self.family()
        if family == "unknown":
            product = self.fields["product"]
            if product.done or product.attempts >= 2:
                return None
            return "product", PRODUCT_QUESTION

        sizes = self.fields["sizes"]
        if (
            sizes.value
            and not sizes.done
            and not size_is_unknown(sizes.value)
            and not size_has_unit(sizes.value)
            and not self.flags.get("unit_asked")
        ):
            return "sizes", "Is that in inches, cm or mm?"

        for key, question in self.script():
            if key == "skus" and self.is_plain():
                continue
            value = self.fields[key]
            if value.done or value.attempts >= 2:
                continue
            return key, question

        for key in BLOCKING_FIELDS:
            if not self.fields[key].done:
                return None

        contact = self.next_contact_question()
        return contact

    def finalize_stalled(self) -> list[str]:
        noted: list[str] = []
        sizes = self.fields["sizes"]
        if (
            sizes.value
            and not size_has_unit(sizes.value)
            and self.flags.get("unit_asked")
            and not sizes.done
        ):
            sizes.status = "needs_confirmation"
            noted.append("sizes")
        return noted

    def next_contact_question(self) -> tuple[str, str] | None:
        email = self.fields["email"]
        phone = self.fields["phone"]
        if self.reachable():
            return None
        if email.attempts < 2:
            return "email", "What is the best email to send the quote to?"
        if phone.attempts < 2:
            return "phone", "What is the best phone number to reach you on?"
        return None

    def missing_for_prompt(self) -> list[str]:
        relevant = {key for key, _ in self.script()} | set(BLOCKING_FIELDS)
        missing = []
        for key in FIELD_LABELS:
            value = self.fields[key]
            if value.done:
                continue
            if key in BLOCKING_FIELDS:
                missing.append(f"{FIELD_LABELS[key]} (blocking)")
            elif key in CONTACT_FIELDS:
                if not self.reachable() and key != "name":
                    missing.append(FIELD_LABELS[key])
            elif key in relevant:
                missing.append(FIELD_LABELS[key])
        return missing

    def known_for_prompt(self) -> str:
        parts = []
        for key in FIELD_LABELS:
            value = self.fields[key]
            if value.value:
                parts.append(f"{FIELD_LABELS[key]}: {value.value}")
        return "; ".join(parts) if parts else "nothing yet"

    def summary(self) -> str:
        next_q = self.next_question()
        lines = [
            f"Persona: {self.persona}",
            f"Family: {self.family()}",
            f"Known: {self.known_for_prompt()}",
            f"Missing: {', '.join(self.missing_for_prompt()) or 'none'}",
            f"Turn: {self.turn_count + 1}",
            f"Next question: {next_q[1] if next_q else '(none — contact or handoff)'}",
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
    if key in {"style", "material", "extras", "name"}:
        if key == "extras" and candidate.lower() in {"yes", "no", "none", "both", "neither"}:
            return True
        tokens = [token for token in re.findall(r"[a-z0-9]+", candidate.lower()) if len(token) > 2]
        return any(token in visitor for token in tokens)
    return True


def apply_field_updates(
    state: ConversationState, updates: dict[str, Any], visitor_text: str
) -> tuple[dict[str, str], dict[str, str]]:
    accepted: dict[str, str] = {}
    rejected: dict[str, str] = {}
    for key, raw in (updates or {}).items():
        if key not in state.fields or raw is None:
            continue
        value = str(raw).strip()
        if not value:
            continue
        if key == "product" and state.fields["product"].done and is_question(visitor_text):
            # "what style of boxes do you have" mentions boxes, but it is a
            # question about their existing order, not a switch to boxes.
            rejected[key] = value
            continue
        if key == "style":
            normalized_style = normalize_style(value)
            if is_question(visitor_text) and not normalized_style:
                rejected[key] = value
                continue
            if normalized_style:
                value = normalized_style
        if key == "material" and is_question(visitor_text):
            material_match = MATERIAL_HINTS.search(value)
            if not material_match:
                rejected[key] = value
                continue
            value = material_match.group(0)
        if key == "extras" and is_question(visitor_text):
            if value.lower() not in {"yes", "no", "none", "both", "neither"}:
                rejected[key] = value
                continue
        if key == "sizes":
            value = tidy_size(value)
            if not size_has_unit(value) and size_has_unit(visitor_text):
                value = tidy_size(visitor_text)
            if not size_has_unit(value) and not size_is_unknown(value) and value:
                state.flags["size_pending_unit"] = value
            if size_is_unknown(visitor_text) and size_is_unknown(value):
                state.set_field("sizes", "to be confirmed", "visitor")
                state.fields["sizes"].status = "needs_confirmation"
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
            state.set_field(key, "no preference", "visitor")
            state.fields[key].status = "answered"
            accepted[key] = "no preference"
            continue
        if not traceable(key, value, visitor_text, state):
            rejected[key] = value
            continue
        state.set_field(key, value, "visitor")
        field_value = state.fields[key]
        if key in {"sizes"} and not size_has_unit(value) and not size_is_unknown(value):
            field_value.status = "missing"
            # A new unitless size needs its own unit question, even if one was
            # already asked for an earlier value.
            state.flags.pop("unit_asked", None)
        elif key == "sizes" and size_has_unit(value):
            state.flags.pop("size_pending_unit", None)
            field_value.status = "answered"
        elif key == "email" and not valid_email(value):
            field_value.status = "missing"
        elif key == "phone" and not valid_phone(value):
            field_value.status = "missing"
        else:
            field_value.status = "answered"
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
    elif last_question in {"material", "extras"} and not is_question(value):
        updates.setdefault(last_question, value.strip()[:80])

    if is_plain(value):
        state.flags["plain"] = True
    if BANNER_RE.search(value):
        state.flags["banner"] = True
    return updates


def reset_attempts_for_new_turn(state: ConversationState) -> None:
    state.flags.pop("asked_this_turn", None)
