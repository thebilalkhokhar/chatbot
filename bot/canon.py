from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

CONFIRMED = "confirmed"
NEEDS_SIGNOFF = "needs_signoff"

SHIPPING_COUNTRIES = (
    r"china|india|uk|united kingdom|canada|australia|germany|france|spain|italy|"
    r"netherlands|mexico|brazil|japan|south korea|singapore|malaysia|pakistan|"
    r"bangladesh|philippines|uae|dubai|saudi arabia|south africa|new zealand|"
    r"ireland|europe|asia|africa|middle east"
)


@dataclass(frozen=True)
class CanonFact:
    key: str
    label: str
    answer: str
    source: str
    status: str
    triggers: tuple[str, ...]
    answer_tokens: tuple[str, ...]
    note: str = ""

    def matches(self, text: str) -> bool:
        return any(re.search(pattern, text, re.IGNORECASE) for pattern in self.triggers)


CANON: dict[str, CanonFact] = {
    "moq": CanonFact(
        key="moq",
        label="Minimum order",
        answer=(
            "Our standard MOQ is 1,000 per size (500 each if you have multiple designs), "
            "but we do smaller runs too, so just tell me the quantity you need."
        ),
        source="findings fix #1 + kb/facts/moq.md + production chat wording",
        status=CONFIRMED,
        triggers=(
            r"\bmoq\b",
            r"\bminimum\b",
            r"\bmin\.?\s*(?:order|quantity)\b",
            r"\bsmallest\s+(?:order|run|quantity)\b",
            r"\bleast\s+(?:amount|order|quantity)\b",
            r"\blowest\s+(?:order|quantity)\b",
        ),
        answer_tokens=(r"1,?000", r"\b500\b"),
        note="Production wording: standard MOQ 1,000 per size, 500 each with multiple designs, and smaller runs are accepted. Banners are handled separately.",
    ),
    "turnaround": CanonFact(
        key="turnaround",
        label="Standard turnaround",
        answer="Our standard turnaround is 12-15 business days, including production and delivery.",
        source="kb/facts/turnaround.md",
        status=CONFIRMED,
        triggers=(
            r"\bturn ?around\b",
            r"\blead ?times?\b",
            r"\bproduction time\b",
            r"\bhow long\b",
            r"\btimeline\b",
            r"\bhow (?:fast|soon|quickly)\b",
            r"\bdelivery time\b",
            r"\bhow many days\b",
        ),
        answer_tokens=(r"12\s*[-to]+\s*15\s*business days", r"12-15"),
    ),
    "rush": CanonFact(
        key="rush",
        label="Rush order",
        answer=(
            "Rush orders are possible. The team confirms the production slot and exact "
            "timeline with your quote."
        ),
        source="kb/facts/turnaround.md (policy 5-7 days vs script 10-12 days)",
        status=CONFIRMED,
        triggers=(r"\brush\b", r"\burgent\b", r"\basap\b", r"\bexpedite[ds]?\b", r"\bfaster\b"),
        answer_tokens=(r"rush", r"production slot", r"timeline"),
        note="Never commit a rush date in chat.",
    ),
    "location": CanonFact(
        key="location",
        label="Location",
        answer="Our facility is in Rosenberg, Texas.",
        source="kb/facts/contact.md",
        status=CONFIRMED,
        triggers=(
            r"\bwhere\s+(?:are|is)\s+(?:you|print247|your\s+(?:company|office|factory|facility))\b",
            r"\blocated\b",
            r"\blocation\b",
            r"\bbased\b",
            r"\baddress\b",
        ),
        answer_tokens=(r"rosenberg",),
        note="Signed off 2026-10-30: use Rosenberg (footer facility); Houston and Sylmar are mentions, not confirmed facilities.",
    ),
    "hours": CanonFact(
        key="hours",
        label="Office hours",
        answer="Our office is open Monday to Friday, 9am to 5pm.",
        source="kb/facts/support-hours.md",
        status=CONFIRMED,
        triggers=(
            r"\b(?:office|business|support)\s+hours\b",
            r"\bwhat\s+time\s+(?:are|do)\s+you\b",
            r"\bopen\b",
            r"\bclosed?\b",
            r"\bweekend\b",
            r"\bsaturday\b",
            r"\bsunday\b",
        ),
        answer_tokens=(r"monday", r"9\s*(?:am|:00)", r"friday"),
        note="Signed off 2026-10-30: office hours Mon-Fri 9-5; the 24/7 line is quote-page assistance wording and is not merged.",
    ),
    "payments": CanonFact(
        key="payments",
        label="Payment methods",
        answer=(
            "We accept Visa, Mastercard, American Express, Discover and PayPal, as well as "
            "ACH, Zelle, wire transfer and Zoho Payments."
        ),
        source="kb/facts/payments.md",
        status=CONFIRMED,
        triggers=(
            r"\bpayment\b",
            r"\bpay\b",
            r"\bach\b",
            r"\bzelle\b",
            r"\bwire\b",
            r"\bcredit\b",
            r"\bdebit\b",
            r"\bpaypal\b",
            r"\b(?:visa|mastercard|amex|discover)\b",
        ),
        answer_tokens=(r"\bvisa\b", r"\bpaypal\b", r"\bach\b", r"\bzelle\b", r"\bwire\b", r"\bzoho\b"),
        note="Signed off 2026-10-30: site footer (cards, PayPal) + refund page (ACH, Zelle, wire, Zoho); the 3% card fee is script-only and is not stated.",
    ),
    "shipping": CanonFact(
        key="shipping",
        label="Shipping",
        answer="Shipping is free nationwide via UPS.",
        source="kb/policies/shipping.md",
        status=CONFIRMED,
        triggers=(
            r"\bshipping\b",
            r"\bshipments?\b",
            r"\bdeliver(?:y|ed|ing)?\b",
            r"\bcarrier\b",
            r"\bups\b",
            r"\bfedex\b",
            r"\bnationwide\b",
        ),
        answer_tokens=(r"\bups\b", r"free nationwide", r"shipping is free"),
        note="Nationwide = USA. International questions are handled by intl_shipping; never promise international delivery.",
    ),
    "intl_shipping": CanonFact(
        key="intl_shipping",
        label="International shipping",
        answer=(
            "Shipping is free nationwide via UPS. For delivery outside the USA, the team "
            "will confirm whether delivery is possible and what it costs when they send "
            "the quote."
        ),
        source="kb/policies/shipping.md",
        status=CONFIRMED,
        triggers=(
            r"\binternational(?:ly)?\b",
            r"\boverseas\b",
            r"\babroad\b",
            r"\bworldwide\b",
            r"\boutside\s+(?:the\s+)?(?:usa|us|united states)\b",
            rf"\b(?:ship|shipping|deliver|delivery|send|orders?)\b[^.?!]{{0,40}}\b(?:{SHIPPING_COUNTRIES})\b",
            rf"\b(?:{SHIPPING_COUNTRIES})\b[^.?!]{{0,40}}\b(?:ship|shipping|deliver|delivery|send|orders?)\b",
        ),
        answer_tokens=(
            r"outside the (?:usa|us)",
            r"\byour country\b",
            r"\binternational (?:delivery|orders|shipping)\b",
        ),
        note="KB policy names no international carrier, cost or promise. Answer with the written wording; the quote carries the team's confirmation.",
    ),
    "contact": CanonFact(
        key="contact",
        label="Contact",
        answer="You can reach the team at Support@print247.us or +1 (832) 807-3429.",
        source="kb/facts/contact.md",
        status=CONFIRMED,
        triggers=(r"\bcontact\b", r"\bemail\b", r"\bphone\b", r"\bcall\b", r"\bwhatsapp\b"),
        answer_tokens=(r"support@print247\.us", r"832"),
    ),
    "artwork": CanonFact(
        key="artwork",
        label="Artwork formats",
        answer="AI, PDF, EPS or ZIP files work; business cards also accept PSD.",
        source="kb/facts/artwork.md",
        status=CONFIRMED,
        triggers=(
            r"\bartwork\b",
            r"\bfile format\b",
            r"\bwhich files?\b",
            r"\b(?:ai|pdf|eps|zip|psd)\b",
            r"\bupload\b",
        ),
        answer_tokens=(r"\bai\b", r"\bpdf\b", r"\beps\b", r"\bzip\b", r"\bpsd\b"),
    ),
    "samples": CanonFact(
        key="samples",
        label="Samples and proofs",
        answer=(
            "Samples take 3-4 business days; they come pre-printed rather than with your own "
            "artwork, and digital proofs arrive within 3 days."
        ),
        source="kb/facts/samples.md",
        status=CONFIRMED,
        triggers=(r"\bsamples?\b", r"\bproofs?\b", r"\bmockups?\b", r"\bprototype\b", r"\bdieline\b"),
        answer_tokens=(r"sample", r"proof", r"pre-printed", r"artwork"),
        note="Signed off 2026-10-30: KB wording. Samples are standard pre-printed, not custom artwork; never promise a custom-artwork sample.",
    ),
    "quote_time": CanonFact(
        key="quote_time",
        label="Quote turnaround",
        answer="Quotes for printed roll stock or custom-sized bags are prepared within 2-3 business days.",
        source="kb/facts/quote-flow.md",
        status=CONFIRMED,
        triggers=(
            r"\bhow long\b.*\bquote\b",
            r"\bquote\b.*\b(?:take|time|ready|when)\b",
            r"\bwhen\b.*\bquote\b",
        ),
        answer_tokens=(r"2\s*[-to]+\s*3\s*business days",),
    ),
    "design": CanonFact(
        key="design",
        label="Design support",
        answer="Design support is free; the team prepares the design after the initial payment.",
        source="kb/facts/design-support.md",
        status=CONFIRMED,
        triggers=(
            r"\bdesign (?:help|support|service|assistance)\b",
            r"\bdo you (?:do|provide) design",
            r"\bcan you (?:design|create)",
            r"\bdesigner\b",
        ),
        answer_tokens=(r"design", r"free"),
    ),
    "styles": CanonFact(
        key="styles",
        label="Style options",
        answer=(
            "Bag styles include stand-up, flat, flat-bottom, side gusset and pinch bottom. "
            "Box styles include display, mailer, gift and kraft boxes."
        ),
        source="kb/products/pouches-mylar-styles.md + kb/products/boxes-campaign-styles.md",
        status=CONFIRMED,
        triggers=(
            r"\b(?:what|which|any)\s+(?:styles?|kinds?|types?)\b[^.?!]{0,40}\b(?:bags?|pouches?|boxes?|box)\b",
            r"\b(?:bag|pouch|box)\s+styles?\b",
            r"\bstyles?\s+(?:of|for)\s+(?:bags?|pouches?|boxes?)\b",
            r"\b(?:what|which)\s+(?:styles?|kinds?|types?)\s+(?:do you|can you|are)\b",
        ),
        answer_tokens=(r"stand-up", r"mailer"),
        note="Options come from the mylar pouch styles page and the boxes campaign style cards; offer only listed styles.",
    ),
    "products": CanonFact(
        key="products",
        label="What we make",
        answer=(
            "We make custom boxes, mylar bags and pouches, labels and stickers, signs and "
            "banners, business cards, and print products."
        ),
        source="kb/products/overview.md",
        status=CONFIRMED,
        triggers=(
            r"\bwhat (?:do you|products?)\b",
            r"\bwhat (?:boxes|bags|labels|products?)\b",
            r"\bwhat (?:kind|type|sort) of\b.*\b(?:make|offer|do)\b",
            r"\bwhat (?:types?|kinds?) of packaging\b",
            r"\bcatalog(?:ue)?\b",
            r"\b(?:what|which|packaging|printing)\s+options\b",
            r"\boptions\s+(?:do you|are)\b",
        ),
        answer_tokens=(r"boxes", r"bags", r"labels", r"banners", r"business cards", r"print"),
    ),
    "price": CanonFact(
        key="price",
        label="Pricing",
        answer="Pricing depends on the specs. The team sends it with your quote.",
        source="kb/facts/pricing-approach.md",
        status=CONFIRMED,
        triggers=(
            r"\bprice\b",
            r"\bpricing\b",
            r"\bcost\b",
            r"\bhow much\b",
            r"\bdiscount\b",
            r"\bper unit\b",
            r"\bcheap(?:er|est)?\b",
            r"\bbudget\b",
            r"\bafford(?:able)?\b",
            r"\blowest\b.*\bprice\b",
        ),
        answer_tokens=(r"specs", r"quote"),
    ),
    "materials": CanonFact(
        key="materials",
        label="Materials",
        answer=(
            "Bags and pouches come in PET, PE, kraft and foil films; labels are PP white "
            "vinyl; boxes are board, never film."
        ),
        source="kb/materials/materials-by-family.md",
        status=CONFIRMED,
        triggers=(
            r"\bmaterials?\b",
            r"\bsubstrates?\b",
            r"\bdo you (?:have|offer|carry|use)\b.*\b(?:pet|mpet|rpet|kraft|bopp|vinyl|corrugated|cardstock|foil|paper|board)\b",
            r"\b(?:have|offer|carry|use|stock)\b[^.?!]{0,40}\b(?:pet|mpet|rpet|kraft|bopp|vinyl|corrugated|cardstock|foil|paper|board)\b",
        ),
        answer_tokens=(r"\bpet\b", r"\bkraft\b", r"\bfoil\b", r"\bboard\b", r"\bvinyl\b"),
    ),
    "extras_info": CanonFact(
        key="extras_info",
        label="Bag extras explained",
        answer=(
            "A zipper makes the pouch resealable; options include press-to-close, "
            "easy-open and child-resistant. A tear notch is a small cut that lets you "
            "open the bag by hand."
        ),
        source="kb/materials/extras.md",
        status=CONFIRMED,
        triggers=(
            r"\bwhat(?:'s| is| are) (?:a |an |the )?(?:zipper|tear notch|hang hole|degassing valve)\b",
            r"\bwhat is (?:zipper and tear|a zipper and tear notch)\b",
            r"\bzipper and tear\b.*\?",
            r"\b(?:which|what|any) (?:zipper|tear notch) options\b",
            r"\bexplain\b.*\b(?:zipper|tear notch)\b",
        ),
        answer_tokens=(r"zipper", r"tear notch", r"resealable"),
    ),
    "custom": CanonFact(
        key="custom",
        label="Custom work",
        answer="Yes — everything we make is custom, including custom shapes and sizes.",
        source="kb/products/overview.md",
        status=CONFIRMED,
        triggers=(
            r"\bdo you (?:guys |all )?(?:make|do|offer|produce|print)\b[^.?!]{0,40}\b(?:pouches?|bags?|boxes?|labels?|stickers?|banners?|cards?)\b",
        ),
        answer_tokens=(r"\byes\b", r"custom"),
    ),
    "food_boxes": CanonFact(
        key="food_boxes",
        label="Food packaging recommendation",
        answer=(
            "For dry meat, a food-grade mylar pouch or a food-grade SBS folding carton both "
            "work. The team confirms the exact material and thickness with your quote."
        ),
        source="kb/products/beef-jerky-bags.md + kb/products/boxes-campaign-materials.md + kb/products/boxes-campaign-styles.md",
        status=CONFIRMED,
        triggers=(
            r"\b(?:dry|dried)\s+(?:meat|food|snacks?|fruit|goods)\b",
            r"\b(?:meat|jerky|snacks?)\b[^.?!]{0,40}\bbox(?:es)?\b",
            r"\bbox(?:es)?\b[^.?!]{0,40}\b(?:meat|jerky|snacks?)\b",
            r"\bfood[- ]grade\b[^.?!]{0,40}\bbox(?:es)?\b",
        ),
        answer_tokens=(r"\bsbs\b", r"food[- ]grade", r"folding carton", r"\bmylar\b", r"\bpouch(?:es)?\b"),
        note="Mylar pouch wording comes from the beef jerky bags page (food-grade mylar); box wording from the boxes campaign pages. The team confirms the final spec with the quote.",
    ),
}

TOPIC_PRIORITY = (
    "price", "moq", "rush", "turnaround", "location", "hours", "payments",
    "shipping", "intl_shipping", "contact", "artwork", "samples", "quote_time", "design",
    "materials", "extras_info", "custom", "styles", "food_boxes", "products",
)

CLAIM_WORDS = (
    "waterproof", "weatherproof", "dishwasher safe", "freezer safe", "food safe",
    "food-safe", "durable", "eco-friendly", "biodegradable", "compostable",
    "scratch resistant", "fade resistant", "guarantee", "warranty", "certified",
    "fda approved", "fda-approved", "bpa-free", "recyclable",
)


def detect_topic(text: str) -> str | None:
    topics = detect_topics(text)
    return topics[0] if topics else None


def dedupe_topics(topics: list[str]) -> list[str]:
    # The international answer already includes the nationwide UPS line, so a
    # separate domestic shipping answer would just repeat it.
    if "intl_shipping" in topics:
        return [key for key in topics if key != "shipping"]
    return topics


def detect_topics(text: str) -> list[str]:
    value = str(text or "")
    topics = [key for key in TOPIC_PRIORITY if CANON[key].matches(value)]
    # "I don't have an email" names the word email. It is a refusal to give
    # theirs, not a question about how to reach Print247.
    if "contact" in topics:
        from .state import refuses_contact

        if refuses_contact(value):
            topics = [key for key in topics if key != "contact"]
    return dedupe_topics(topics)


_MINIMUM_TOPIC = re.compile(
    r"\b(?:moqs?|minimum(?:\s+order(?:\s+quantity)?)?|min\.?\s*(?:order|quantity)|"
    r"smallest\s+(?:order|run|quantity)|lowest\s+(?:order|quantity)|"
    r"least\s+(?:amount|order|quantity))\b",
    re.I,
)
# A request to be told the figure. A complaint, or a bare quantity, is not one.
_EXPLICIT_MINIMUM_ASK = re.compile(
    r"\b(?:what(?:'s|s| is| are)?|whats)\b[^?.!]{0,60}\b(?:moq|minimum|smallest|lowest|least)\b"
    r"|\b(?:do|does|can|could)\s+(?:you|we|i)\b[^?.!]{0,48}\b(?:moq|minimum)\b"
    r"|\bis\s+there\b[^?.!]{0,40}\b(?:moq|minimum)\b"
    r"|\b(?:any|got)\s+(?:a\s+)?minimum\b"
    r"|\b(?:please\s+)?(?:share|tell(?:\s+me)?|give(?:\s+me)?|confirm|send|list)\b[^?.!]{0,48}\b(?:moq|minimum)\b"
    r"|\b(?:your|the|a|our)\s+(?:standard\s+)?(?:moq|minimum(?:\s+order(?:\s+quantity)?)?)\s*\?",
    re.I,
)
_MINIMUM_COMPLAINT = re.compile(
    r"\b(?:too high|too much|too low|too big|ridiculous|crazy)\b",
    re.I,
)


def asks_for_minimum(text: str) -> bool:
    """True only when they are asking what the minimum is.

    "300", "I need 300", and "your minimum is too high" are not that question.
    "What is your minimum?" and "do you have an MOQ?" are.
    """
    value = str(text or "").strip()
    if not value or not _MINIMUM_TOPIC.search(value):
        return False
    complaint = bool(_MINIMUM_COMPLAINT.search(value))
    if "?" in value and not complaint:
        return True
    return bool(_EXPLICIT_MINIMUM_ASK.search(value))


def topics_to_answer(text: str) -> list[str]:
    """Facts this message actually asked for.

    The word "minimum" inside a quantity or a complaint must not pull the
    canon MOQ sentence into the reply.
    """
    topics = detect_topics(text)
    if "moq" in topics and not asks_for_minimum(text):
        return [key for key in topics if key != "moq"]
    return topics


def fact(key: str) -> CanonFact | None:
    return CANON.get(key)


# Section 4.10. True means the bot may volunteer it. False means only when the visitor asked.
# The operator email, and Houston or Sylmar as a facility, are never-rows: not in this map.
OFFERABLE_FACTS = {
    "contact": True,
    "location": False,
    "hours": False,
    # The MOQ sentence is not a volunteer line. A quantity is not a request for it.
    "moq": False,
}
OPERATOR_EMAIL = "johnhenry.it@print247.us"


def facts_for_prompt() -> str:
    lines = ["WRITTEN ANSWERS — use these words, do not invent alternatives:"]
    for key in TOPIC_PRIORITY:
        item = CANON[key]
        flag = "" if item.status == CONFIRMED else " [needs sign-off: answer exactly as written]"
        offerable = OFFERABLE_FACTS.get(key)
        offer = ""
        if offerable is True:
            offer = " [offerable: true]"
        elif offerable is False:
            offer = " [offerable: false]"
        lines.append(f"- {item.label} ({key}){flag}{offer}: {item.answer}")
    lines.append(
        "NEVER state, even if asked: the operator email "
        f"{OPERATOR_EMAIL}; a Houston facility; a Sylmar facility."
    )
    return "\n".join(lines)


def answer_covers(key: str, reply: str) -> bool:
    item = CANON.get(key)
    if not item:
        return False
    return any(re.search(pattern, reply, re.IGNORECASE) for pattern in item.answer_tokens)


def time_phrases_allowed() -> list[str]:
    phrases: list[str] = []
    for item in CANON.values():
        for match in re.finditer(r"\d[\d\s\-to]*(?:business days|days|hours)", item.answer, re.IGNORECASE):
            phrases.append(match.group(0).lower())
    return phrases


def load_overrides(data_dir: Path) -> dict[str, str]:
    path = data_dir / "canon_overrides.json"
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return {str(key): str(value) for key, value in raw.items()}


def effective_answer(key: str, overrides: dict[str, str] | None = None) -> str:
    overrides = overrides or {}
    return overrides.get(key) or CANON[key].answer


def signoff_report() -> list[dict]:
    return [
        {
            "key": item.key,
            "label": item.label,
            "status": item.status,
            "answer": item.answer,
            "note": item.note,
        }
        for item in CANON.values()
        if item.status != CONFIRMED
    ]
