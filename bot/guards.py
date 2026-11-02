from __future__ import annotations

import re
from dataclasses import dataclass, field

from . import canon
from .pii import restore_public_contact
from .capability import Candidate, Registry, fold, value_forms
from .personas import PERSONAS
from .state import (
    ASK_PRIORITY,
    BARE_QTY_RE,
    EMAIL_RE,
    MATERIAL_HINTS,
    PHONE_RE,
    QTY_UNIT_RE,
    SINGLE_SIZE_RE,
    SIZE_DIM_RE,
    STYLE_HINTS,
    ConversationState,
    STATUS_WAIVED,
    asks_if_bot,
    family_of,
    is_meta_question,
    is_option_request,
    is_question,
    is_visitor_greeting,
    normalize_finish,
    normalize_style,
    use_case_from,
    wants_recommendation,
)

BLOCK = "block"
WARN = "warn"
INFO = "info"

BANNED_PROMISES = re.compile(
    r"\b(?:i|we)(?:'ll| will| can| would)\s+(?:check|confirm|verify|look into|find out|get back|let you know|ask the team)"
    r"|\blet me (?:check|confirm|verify|look into|find out|ask)\b"
    r"|\bi(?:'ll| will) (?:get|have) (?:someone|a rep|the team) (?:to )?(?:check|confirm|look)\b",
    re.I,
)
HOLDING_PHRASE = re.compile(
    r"\bone of our team will be with you shortly\b|\bsomeone will be with you shortly\b",
    re.I,
)
# Apostrophes are folded to ASCII before matching, so I’m and I'm are the same claim.
_APOSTROPHE = str.maketrans({"\u2019": "'", "\u2018": "'", "\u02bc": "'", "`": "'"})
SELF_CLAIM = re.compile(
    r"\b(?:i am|i'm|this is)\s+(?:an?\s+)?(?:ai|a\.i\.|bot|chatbot|robot|virtual assistant|automated assistant|automated system|machine)\b"
    r"|\bas an ai\b",
    re.I,
)
AI_DENIAL = re.compile(
    r"\b(?:i am|i'm|this is)\s+not\s+(?:an?\s+)?(?:ai|a\.i\.|bot|chatbot|robot|virtual assistant)\b",
    re.I,
)
HUMAN_CLAIM = re.compile(
    r"\b(?:i am|i'm)\s+(?:a\s+)?(?:real\s+)?(?:human|person|real person)\b", re.I
)
DISCLOSURE = re.compile(r"\b(?:ai|a\.i\.|automated|virtual assistant|chatbot)\b", re.I)
DISCOUNT_PROMISE = re.compile(
    r"\b(?:i|we)(?:'ll| will|can|could)\s+(?:offer|give|do|arrange)\s+(?:you\s+)?(?:a\s+)?"
    r"(?:discount|better price|better deal|lower price)\b",
    re.I,
)
PRICE = re.compile(
    r"[$€£]\s*\d"
    r"|\b\d[\d,]*(?:\.\d+)?\s*(?:usd|dollars?|cents?|per unit|/unit|a unit)\b"
    r"|\b(?:price|pricing|cost)(?: is| would be| will be| comes to| at)\b[^.]{0,20}\d",
    re.I,
)
TIME_NUMERIC = re.compile(
    r"\b\d+\s*(?:-|to|–)?\s*\d*\s*(?:business\s+)?(?:days?|weeks?|hours?)\b", re.I
)
TIME_DATE = re.compile(
    r"\b(?:by|before|on)\s+(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday|"
    r"tomorrow|next week|end of (?:the )?(?:day|week|month)|\d{1,2}/\d{1,2}(?:/\d{2,4})?)\b",
    re.I,
)
DELIVERY_VERB = re.compile(
    r"\b(?:ship|deliver|ready|arrive|finish|complete|produce|have it|get it|receive)\b", re.I
)
MARKDOWN = re.compile(r"\*\*|__|`|^\s*#{1,6}\s|^\s*[-*•]\s|^\s*\d+[.)]\s", re.M)
EMOJI = re.compile("[\U0001f300-\U0001faff\u2600-\u27bf]")
GREETING = re.compile(
    r"^\s*(?:hi|hello|hey|morning|afternoon|evening|good (?:morning|afternoon|evening|day))\b",
    re.I,
)
_GREETING_PREFIX = re.compile(
    r"^(?:good\s+(?:morning|afternoon|evening|day)|morning|afternoon|evening|"
    r"(?:hi|hello|hey)(?:\s+there)?)\b(?!-)[!.,:]*\s*",
    re.I,
)
QUESTION_CLAUSE = re.compile(
    r"(?:^|[.!?]\s+|\band\s+|\balso\s+|\bplus\s+)(?:what|which|when|where|who|how|"
    r"can|could|would|will|do|does|did|is|are|should|any)\b"
    r"(?!\s+(?:much\s+)?it\s+costs?\b)",
    re.I,
)
NUMBER = re.compile(r"\b\d[\d,]*(?:\.\d+)?%?")
WEEKDAY = r"(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)"
RECOMMENDATION_MARKER = re.compile(
    r"\b(?:i(?:'d| would)? (?:suggest|recommend)|my recommendation|best (?:option|choice|fit)|"
    r"good (?:fit|choice)|works? well|would work|both work|is a good|are a good)\b",
    re.I,
)
OPTION_NOUN = re.compile(
    r"\b(?:stand[- ]?up|flat[- ]?bottom|side gusset|pinch bottom|mailer|rigid|"
    r"folding carton|sbs|kraft|mylar|pouches?|boxes?|labels?|stickers?|banners?|"
    r"business cards?|corrugated|display box)\b",
    re.I,
)

FIELD_PROBES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("email", re.compile(r"\b(?:email|e-mail|address to send|where (?:should|can|shall) (?:i|we) send|send (?:the|your) quote to)\b", re.I)),
    ("phone", re.compile(r"\b(?:phone|telephone|number to reach|call you|cell|mobile)\b", re.I)),
    ("name", re.compile(r"\b(?:your name|who am i (?:speaking|chatting)|may i have your name|first name)\b", re.I)),
    ("sizes", re.compile(r"\b(?:size|sizes|dimensions?|measurements?)\b", re.I)),
    ("quantity", re.compile(r"\b(?:quantity|quantities|how many (?:units|pieces|bags|boxes|labels|stickers|pouches|banners|cards))\b", re.I)),
    ("finishes", re.compile(
        r"\b(?:finishes|matte|gloss|soft touch)\b"
        r"|\b(?:what|which)\s+finish\b"
        r"|\bfinish\s+(?:would|do|should|you|preference|options)\b",
        re.I,
    )),
    ("skus", re.compile(r"\b(?:designs?|skus?)\b", re.I)),
    ("style", re.compile(
        r"\b(?:what|which)\s+style\b"
        r"|\bstyle\s+(?:of|do|would|should|are)\b"
        r"|\b(?:flat|stand[- ]?up|flat[- ]?bottom|reference image)\b",
        re.I,
    )),
    ("material", re.compile(r"\b(?:material|special features|paper stock)\b", re.I)),
    ("extras", re.compile(r"\b(?:zipper|tear notch|extras?)\b", re.I)),
    ("use_case", re.compile(
        r"\b(?:what (?:will|goes|is going)\s+(?:be\s+)?inside|what are you (?:packing|putting|selling|shipping|sending)|"
        r"use case|what is it for|what are they for|who is it going to|retail or (?:shipping|wholesale|online)|"
        r"what (?:kind|type) of (?:product|item))\b",
        re.I,
    )),
    ("product", re.compile(r"\b(?:what are you looking|boxes, bags|have made|looking to (?:make|order|have))\b", re.I)),
)

IGNORED_NUMBERS = {"247"}


@dataclass(frozen=True)
class Issue:
    code: str
    severity: str
    detail: str
    excerpt: str = ""

    def to_dict(self) -> dict:
        return {
            "code": self.code,
            "severity": self.severity,
            "detail": self.detail,
            "excerpt": self.excerpt,
        }


@dataclass
class GuardResult:
    issues: list[Issue] = field(default_factory=list)

    @property
    def blockers(self) -> list[Issue]:
        return [issue for issue in self.issues if issue.severity == BLOCK]

    @property
    def warnings(self) -> list[Issue]:
        return [issue for issue in self.issues if issue.severity == WARN]

    @property
    def ok(self) -> bool:
        return not self.blockers

    def add(self, code: str, severity: str, detail: str, excerpt: str = "") -> None:
        self.issues.append(Issue(code=code, severity=severity, detail=detail, excerpt=excerpt))

    def codes(self) -> list[str]:
        return [issue.code for issue in self.issues]

    def to_dict(self) -> dict:
        return {"ok": self.ok, "issues": [issue.to_dict() for issue in self.issues]}


def _straighten(text: str) -> str:
    return str(text or "").translate(_APOSTROPHE)


def _has_value_token(key: str, text: str) -> bool:
    """Whether `text` actually carries a value for `key`, not just a question about it."""
    value = str(text or "")
    if key == "email":
        return bool(EMAIL_RE.search(value))
    if key == "phone":
        return bool(PHONE_RE.search(value))
    if key == "name":
        return bool(re.search(r"\bmy name is\s+[A-Za-z]", value, re.I))
    if key == "sizes":
        return bool(SIZE_DIM_RE.search(value) or SINGLE_SIZE_RE.search(value))
    if key == "quantity":
        return bool(QTY_UNIT_RE.search(value) or BARE_QTY_RE.match(value.strip()))
    if key == "finishes":
        finish = normalize_finish(value)
        return bool(finish)
    if key == "style":
        return bool(normalize_style(value) or STYLE_HINTS.search(value))
    if key == "material":
        return bool(MATERIAL_HINTS.search(value))
    if key == "product":
        return family_of(value) != "unknown"
    if key == "use_case":
        return bool(use_case_from(value))
    if key == "skus":
        return bool(re.search(r"\d+\s*(?:designs?|skus?)", value, re.I))
    if key == "extras":
        return bool(re.search(r"\b(?:zipper|tear notch|window|hang hole)\b", value, re.I))
    return False


def question_as_answer(visitor_text: str, key: str) -> bool:
    """True when this message must not be stored as `key`.

    Section 3.4: a question cannot satisfy a field unless it also carries a value
    token for that field. "your address" has no question mark and no style token;
    it is the logged failure that used to fill style and skip the question.
    """
    text = str(visitor_text or "").strip()
    if not text or _has_value_token(key, text):
        return False
    if is_question(text) or asks_if_bot(text):
        return True
    # A short fact request ("your address") is a question even with the mark left off.
    # Longer messages that merely mention a topic are still answers ("dry meat" is a use).
    topics = canon.detect_topics(text)
    return bool(topics) and len(text.split()) <= 4


def settled_for_asking(state: ConversationState, key: str) -> bool:
    """Whether asking about this field again is the failure v1 called `question_already_answered`.

    A size still missing its unit, and one the customer refused to give, are both
    still open — Section 4.4 keeps the unit question and then hands the size to the team.
    """
    field_value = state.fields.get(key)
    if field_value is None:
        return False
    if key == "sizes" and (state.size_needs_unit() or field_value.status == STATUS_WAIVED):
        return False
    return field_value.done


def _sentences(text: str) -> list[str]:
    return [part.strip() for part in re.split(r"(?<=[.!?])\s+", text) if part.strip()]


def count_questions(text: str) -> int:
    value = str(text or "").strip()
    if not value:
        return 0
    marks = value.count("?")
    inferred = max(0, len(QUESTION_CLAUSE.findall(value)) - marks)
    if marks == 0:
        inferred = max(inferred, 1 if QUESTION_CLAUSE.search(value) else 0)
    return marks + inferred


def asked_field(text: str) -> str | None:
    value = str(text or "")
    question_sentences = [sentence for sentence in _sentences(value) if "?" in sentence]
    if question_sentences:
        scope = " ".join(question_sentences)
    elif re.search(r"\b(?:let me know|tell me|share|send over)\b", value, re.I):
        scope = value
    else:
        return None
    # "Is 15x19 in inches, cm, or mm?" is the size question and never says "size".
    if re.search(r"\binches\b", scope, re.I) and re.search(r"\b(?:cm|mm)\b", scope, re.I):
        return "sizes"
    # Prefer the field the question is actually about when earlier probes only
    # match restated specs ("…besides soft touch and the oval size… material?").
    focused = (
        ("material", re.compile(
            r"\b(?:what|which)\s+(?:\w+\s+){0,4}material\b"
            r"|\bmaterial\s+(?:would|do|should|are|you want)\b",
            re.I,
        )),
        ("finishes", re.compile(
            r"\b(?:what|which)\s+finish\b|\bfinish\s+(?:would|do|should)\b",
            re.I,
        )),
        ("skus", re.compile(
            r"\b(?:how many).{0,40}\b(?:designs?|skus?)\b"
            r"|\b(?:what|which)\s+(?:design|sku)\b",
            re.I,
        )),
        ("quantity", re.compile(
            r"\b(?:what|which)\s+quantity\b"
            r"|\bhow many\s+(?:units|pieces|bags?|boxes?|labels?|stickers?|pouches?|banners?|cards?)\b"
            r"|\bquantity\s+(?:are|do|would|should|you)\b",
            re.I,
        )),
        ("style", re.compile(r"\b(?:what|which)\s+style\b", re.I)),
        ("sizes", re.compile(
            r"\b(?:what|which)\s+size\b|\bsize\s+(?:are|do|would|should)\b",
            re.I,
        )),
    )
    for key, pattern in focused:
        if pattern.search(scope):
            return key
    for key, pattern in FIELD_PROBES:
        if pattern.search(scope):
            return key
    # Vision / propose-and-confirm: "Are you looking for print products…?"
    if re.search(
        r"\bare you looking for\b|\bdoes (?:that|this|[a-z][\w-]*) look(?: like)?(?: the)? right\b"
        r"|\bdoes .+ sound right\b|\bis that right\b",
        scope,
        re.I,
    ):
        if re.search(
            r"\b(?:boxes?|bags?|labels?|banners?|print products?|business cards?|pouches?)\b",
            scope,
            re.I,
        ):
            return "product"
        if re.search(r"\bstyle\b|\bmailer\b|\brigid\b|\bpouch\b|\btuck\b", scope, re.I):
            return "style"
        if re.search(r"\bfinish\b|\bmatte\b|\bgloss\b|\bsoft touch\b", scope, re.I):
            return "finishes"
        if re.search(r"\bmaterial\b", scope, re.I):
            return "material"
        return "product"
    return None


def normalize_reply(text: str) -> str:
    value = re.sub(r"\s+", " ", str(text or "")).strip().lower()
    return value.strip(" .!?")


def sentence_similarity(left: str, right: str) -> float:
    def words(value: str) -> set[str]:
        return set(re.findall(r"[a-z0-9]+", value.lower()))

    a, b = words(left), words(right)
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _allowed_blob(state: ConversationState, chunks, overrides: dict[str, str] | None) -> str:
    parts = [canon.effective_answer(key, overrides) for key in canon.CANON]
    parts.extend(str(value.value) for value in state.fields.values())
    parts.extend(state.visitor_texts())
    for item in chunks or ():
        chunk = getattr(item, "chunk", item)
        parts.append(getattr(chunk, "text", ""))
        parts.append(getattr(chunk, "title", ""))
    return "\n".join(parts)


def _normalize_time(text: str) -> str:
    value = re.sub(r"\s+", " ", str(text or "").lower())
    value = re.sub(r"\s*(?:-|–|to)\s*", "-", value)
    return value.strip()


def _allowed_time_phrases(overrides: dict[str, str] | None) -> list[str]:
    phrases = canon.time_phrases_allowed()
    for key in canon.CANON:
        answer = canon.effective_answer(key, overrides)
        phrases.extend(match.group(0) for match in TIME_NUMERIC.finditer(answer))
    return list(dict.fromkeys(_normalize_time(item) for item in phrases))


def _numbers(text: str) -> set[str]:
    return {
        match.group(0).replace(",", "").rstrip("%")
        for match in NUMBER.finditer(str(text or ""))
    }


def _repeat_against_history(reply: str, state: ConversationState) -> tuple[str, float]:
    target = normalize_reply(reply)
    best, score = "", 0.0
    for previous in state.bot_texts():
        candidate = normalize_reply(previous)
        if not candidate:
            continue
        same = target == candidate
        similarity = 1.0 if same else sentence_similarity(target, candidate)
        if similarity > score:
            best, score = candidate, similarity
    return best, score


def _check_length(reply: str, result: GuardResult) -> None:
    words = len(reply.split())
    if words == 0:
        result.add("empty_reply", BLOCK, "The reply is empty.")
    elif words > 110:
        result.add("too_long", BLOCK, f"The reply is {words} words; keep it under about 60.", reply[:80])
    elif words > 60:
        result.add("long_reply", WARN, f"The reply is {words} words; it should read like a chat message.")


def _check_format(reply: str, result: GuardResult) -> None:
    if MARKDOWN.search(reply):
        result.add("markdown", BLOCK, "Markdown, bullets or headings cannot be sent in chat.")
    if EMOJI.search(reply):
        result.add("emoji", BLOCK, "Emoji are not used in these chats.")


def _check_questions(reply: str, result: GuardResult) -> None:
    count = count_questions(reply)
    if count > 1:
        result.add(
            "multiple_questions",
            WARN,
            f"{count} questions in one message; the rule is one question per message.",
            reply[:120],
        )


def _check_banned(reply: str, result: GuardResult) -> None:
    promise = BANNED_PROMISES.search(reply)
    if promise:
        result.add(
            "promise_to_check",
            BLOCK,
            "Promising to check or confirm and come back is one of the QA failures.",
            promise.group(0),
        )
    holding = HOLDING_PHRASE.search(reply)
    if holding:
        result.add(
            "holding_phrase",
            BLOCK,
            "'One of our team will be with you shortly' is on the banned list.",
            holding.group(0),
        )
    discount = DISCOUNT_PROMISE.search(reply)
    if discount:
        result.add(
            "discount_promise",
            BLOCK,
            "Discounts are never offered in chat; the quote carries pricing.",
            discount.group(0),
        )


def _check_price(reply: str, result: GuardResult) -> None:
    price = PRICE.search(reply)
    if price:
        result.add(
            "price_given",
            BLOCK,
            "A price or per-unit figure was given; pricing only goes out with the quote.",
            price.group(0),
        )


def _check_time(reply: str, overrides: dict[str, str] | None, result: GuardResult) -> None:
    allowed = _allowed_time_phrases(overrides)
    for match in TIME_NUMERIC.finditer(reply):
        phrase = _normalize_time(match.group(0))
        if any(phrase == item or phrase in item for item in allowed):
            continue
        result.add(
            "time_promise",
            BLOCK,
            "A production or delivery time was promised that is not an approved fact.",
            match.group(0),
        )
    if not TIME_NUMERIC.search(reply):
        for sentence in _sentences(reply):
            if TIME_DATE.search(sentence) and DELIVERY_VERB.search(sentence):
                result.add(
                    "time_promise",
                    BLOCK,
                    "A date was promised; dates only come with the quote.",
                    sentence[:120],
                )
                break


def _check_bot_claim(reply: str, asked_if_bot: bool, result: GuardResult) -> None:
    text = _straighten(reply)
    # D-1: volunteering an AI claim blocks. Being asked and answering honestly does not.
    # A denial blocks either way — "I'm not an AI" is not the approved sentence.
    if AI_DENIAL.search(text) or (SELF_CLAIM.search(text) and not asked_if_bot):
        result.add(
            "bot_self_claim",
            BLOCK,
            "The agent volunteered that it is an AI, or denied it. "
            "Disclose only when asked, in one honest sentence.",
        )
    if HUMAN_CLAIM.search(text):
        result.add(
            "human_claim",
            BLOCK,
            "The agent claimed to be a human; do not assert that.",
        )
    if asked_if_bot and not DISCLOSURE.search(text):
        result.add(
            "bot_question_unanswered",
            BLOCK,
            "The visitor asked whether this is a bot; the reply should say it is an AI assistant.",
        )


# Safety and eco words stay BLOCK. Descriptive packaging words are WARN. Presence in a
# KB chunk is not a licence; only an allow-list sentence quoted in full covers a word.
SAFETY_CLAIMS = (
    "waterproof", "weatherproof", "dishwasher safe", "freezer safe", "food safe",
    "food-safe", "eco-friendly", "biodegradable", "compostable", "fda approved",
    "fda-approved", "bpa-free", "bpa free", "recyclable", "certified",
)
DESCRIPTIVE_CLAIMS = (
    "durable", "scratch resistant", "fade resistant", "guarantee", "warranty",
)


def _allowlist_covers(registry: Registry | None, reply: str, claim: str) -> bool:
    if registry is None:
        return False
    lowered = reply.lower()
    for row in registry.claims:
        sentence = row.say.lower()
        if claim in sentence and sentence in lowered:
            return True
    return False


def _claim_stands_alone(registry: Registry | None, reply: str, claim: str) -> bool:
    """True when the word is still there after catalogue style names are removed.

    "Biodegradable Stand-Up Pouches" is a style we list. Saying that name is not a
    certification. "These pouches are biodegradable" still is.
    """
    if registry is None:
        return True
    needle = fold(claim).replace(" ", "")
    if not needle:
        return True
    compact = fold(reply).replace(" ", "")
    names: set[str] = set()
    for slots in registry.vocabulary.values():
        for values in slots.values():
            for value in values:
                token = fold(value).replace(" ", "")
                if needle in token and len(token) > len(needle) + 2:
                    names.add(token)
    for token in sorted(names, key=len, reverse=True):
        for variant in (token + "es", token + "s", token):
            compact = compact.replace(variant, " ")
    return needle in compact.replace(" ", "")


def _check_claims(reply: str, _allowed_blob: str, result: GuardResult, registry: Registry | None = None) -> None:
    lowered_reply = reply.lower()
    for claim in SAFETY_CLAIMS:
        if (
            claim in lowered_reply
            and not _allowlist_covers(registry, reply, claim)
            and _claim_stands_alone(registry, reply, claim)
        ):
            result.add(
                "unsupported_claim",
                BLOCK,
                f"'{claim}' is a safety or compliance claim and it is not an allow-list sentence.",
                claim,
            )
    for claim in DESCRIPTIVE_CLAIMS:
        if claim in lowered_reply and not _allowlist_covers(registry, reply, claim):
            result.add(
                "unsupported_claim",
                WARN,
                f"'{claim}' is a descriptive claim, not an allow-list sentence.",
                claim,
            )


TIER_B_NUMBER_HINT = re.compile(
    r"\$|%|\b(?:days?|weeks?|hours?|business days|minimum|moq|units?|pieces?|percent|per size)\b",
    re.I,
)


def _number_is_tier_b(reply: str, number: str) -> bool:
    for match in NUMBER.finditer(reply):
        token = match.group(0).replace(",", "").rstrip("%")
        if token != number:
            continue
        window = reply[max(0, match.start() - 48): match.end() + 48]
        if TIER_B_NUMBER_HINT.search(window):
            return True
    return False


def _check_numbers(reply: str, allowed_blob: str, result: GuardResult) -> None:
    allowed = _numbers(allowed_blob) | IGNORED_NUMBERS
    if "24/7" in reply:
        allowed |= {"24", "7"}
    if "24/7" in allowed_blob:
        allowed |= {"24", "7"}
    for number in _numbers(reply):
        if number in allowed:
            continue
        tier_b = _number_is_tier_b(reply, number)
        result.add(
            "untraceable_number",
            BLOCK if tier_b else WARN,
            f"The number {number} appears nowhere in the chat, the facts or the KB.",
            number,
        )


def _check_minimum(reply: str, state: ConversationState, result: GuardResult) -> None:
    family = state.family()
    lowered = reply.lower()
    mentions = [sentence for sentence in _sentences(reply) if re.search(r"\b(?:moq|minimum)\b", sentence, re.I)]
    if not mentions:
        return
    if family == "banners":
        asserts = re.search(
            r"\b(?:moq|minimum)\b[^.]{0,30}\b(?:1,?000|500|\d{3,})\b"
            r"|\b(?:1,?000|500|\d{3,})\s*(?:units?|pieces?)?\s*(?:minimum|moq)\b",
            lowered,
        )
        if asserts:
            result.add(
                "wrong_minimum",
                BLOCK,
                "Banners have no minimum; no minimum figure applies to a banner order.",
                asserts.group(0),
            )
        return
    numbers: set[str] = set()
    for sentence in mentions:
        numbers |= _numbers(sentence)
    wrong = {number for number in numbers if number not in {"1000", "500"}}
    if wrong:
        result.add(
            "wrong_minimum",
            BLOCK,
            "The minimum was stated with a figure the company does not use (1,000 per size, 500 each with multiple designs).",
            ", ".join(sorted(wrong)),
        )
    skus = state.fields.get("skus")
    if "500" in numbers and not re.search(r"\b(?:multiple|more than one|several|each design|per design)\b", lowered):
        if not (skus and skus.value and skus.value.isdigit() and int(skus.value) >= 2):
            result.add(
                "minimum_needs_condition",
                BLOCK,
                "500 is only correct with multiple designs; say 1,000 per size for a single design.",
            )


_ASK_JOIN = re.compile(
    r"\s*,?\s+\b(?:and|also|plus)\b\s+(?=(?:what|which|when|where|who|how|"
    r"can|could|would|will|do|does|did|is|are|should|any)\b)",
    re.I,
)
_ASK_START = re.compile(
    r"^(?:what|which|when|where|who|how|do|does|did|is|are|should|any)\b"
    r"|^(?:can|could|would|will)\s+you\b",
    re.I,
)
# The production MOQ sentence and its pieces. A quantity must not drag these in.
_MOQ_LECTURE = re.compile(
    r"\b(?:our\s+)?standard\s+moq\b"
    r"|\bmoq\s+is\b"
    r"|\b1[,.]?000\s+per\s+size\b"
    r"|\bsmaller\s+runs\b"
    r"|\bno\s+minimum\b"
    r"|\bminimum\s+order\s+is\b"
    r"|\b(?:the\s+)?minimum\s+is\s+(?:1[,.]?000|500)\b"
    r"|\bjust tell me the quantity\b"
    r"|\b500\s+each\b"
    r"|\b(?:under|below|less than|lower than|at least)\s+1[,.]?000\b"
    r"|\bminimum\b[^.]{0,40}\b(?:1[,.]?000|500)\b"
    r"|\b(?:1[,.]?000|500)\b[^.]{0,40}\b(?:minimum|moq)\b",
    re.I,
)
_MOQ_START = re.compile(
    r"\b(?:our\s+standard\s+moq|standard\s+moq|no\s+minimum|"
    r"minimum\s+order\s+is|(?:the\s+)?minimum\s+is\s+(?:1[,.]?000|500)|"
    r"smaller\s+runs|just tell me the quantity|500\s+each|"
    r"(?:under|below|less than|lower than|at least)\s+1[,.]?000)\b",
    re.I,
)


def _field_of_clause(clause: str) -> str:
    for key, pattern in FIELD_PROBES:
        if pattern.search(clause):
            return key
    # "inches, cm, or mm" is the size-unit question and does not say "size".
    if re.search(r"\b(?:inches|cm|mm|unit)\b", clause, re.I):
        return "sizes"
    return ""


def _is_ask(clause: str) -> bool:
    text = clause.strip()
    if "?" in text:
        return True
    return bool(_ASK_START.match(text))


def _ask_clauses(text: str) -> list[str]:
    clauses: list[str] = []
    for sentence in _sentences(text):
        for part in _ASK_JOIN.split(sentence):
            cleaned = part.strip(" ,;")
            if cleaned:
                clauses.append(cleaned)
    return clauses


def _as_question(clause: str) -> str:
    text = clause.strip().rstrip(" ,;.")
    if text.endswith("?"):
        return text
    return f"{text}?"


def _is_moq_lecture(sentence: str) -> bool:
    return bool(_MOQ_LECTURE.search(sentence))


def _without_moq_lecture(sentence: str) -> str:
    """Drop a canon MOQ sentence. Keep a short acknowledgement that sat in front of it."""
    if not _is_moq_lecture(sentence):
        return sentence
    match = _MOQ_START.search(sentence)
    if match and match.start() > 0:
        prefix = sentence[: match.start()].rstrip(" ,;—-")
        if prefix and not _is_moq_lecture(prefix):
            if prefix[-1] not in ".!?":
                prefix += "."
            return prefix
    return ""


def strip_repeated_greeting(reply: str) -> str:
    """Drop a hello that follows the opening greeting. 'Morning!' is one of these.

    A sentence that merely starts with the word morning ("Morning production...") stays.
    """
    kept: list[str] = []
    for sentence in _sentences(reply):
        text = sentence.strip()
        match = _GREETING_PREFIX.match(text)
        if not match:
            kept.append(sentence)
            continue
        rest = text[match.end():].strip()
        token = match.group(0).strip(" !.,:").lower()
        if rest and token in {"morning", "afternoon", "evening"}:
            kept.append(sentence)
            continue
        if rest:
            kept.append(rest)
    return re.sub(r"\s+", " ", " ".join(kept)).strip()


def strip_unsolicited_moq(reply: str, visitor: str) -> str:
    """Remove the MOQ sentence unless they asked what the minimum is."""
    text = str(reply or "").strip()
    if not text or canon.asks_for_minimum(visitor):
        return text
    kept = [_without_moq_lecture(sentence) for sentence in _sentences(text)]
    kept = [sentence for sentence in kept if sentence]
    if not kept:
        return ""
    return re.sub(r"\s+", " ", " ".join(kept)).strip()


def enforce_single_question(reply: str, priority_key: str = "", priority_text: str = "") -> str:
    """Keep one question: the highest-priority missing field, then stop."""
    text = str(reply or "").strip()
    if count_questions(text) <= 1:
        return text
    clauses = _ask_clauses(text)
    ask_indexes = [index for index, clause in enumerate(clauses) if _is_ask(clause)]
    if len(ask_indexes) <= 1:
        return text

    def rank(index: int) -> tuple:
        clause = clauses[index]
        field = _field_of_clause(clause)
        overlap = sentence_similarity(clause, priority_text) if priority_text else 0.0
        if priority_key and (field == priority_key or overlap >= 0.34):
            band, order = 0, 0
        elif field in ASK_PRIORITY:
            band, order = 1, ASK_PRIORITY.index(field)
        else:
            band, order = 2, 0
        return (band, order, -overlap, -index)

    keep = min(ask_indexes, key=rank)
    kept: list[str] = []
    for index, clause in enumerate(clauses):
        if index in ask_indexes and index != keep:
            continue
        if index == keep:
            kept.append(_as_question(clause))
            continue
        piece = clause.strip()
        if piece and piece[-1] not in ".!?":
            piece += "."
        kept.append(piece)
    collapsed = re.sub(r"\s+", " ", " ".join(kept)).strip()
    if count_questions(collapsed) <= 1:
        return collapsed
    # A compound ask that would not split still has to leave as one question.
    return _as_question(clauses[keep])


def _asks_for_our_contact(visitor: str) -> bool:
    return canon.asks_for_our_contact(visitor)


def shape_contact_flow(reply: str, visitor: str, priority_key: str = "", priority_text: str = "") -> str:
    """Answer a contact question with the canon line, then the next checklist field.

    An email or phone ask is also removed while designs, material, or finish are still
    the field that should be asked.
    """
    text = str(reply or "").strip()
    exact = canon.effective_answer("contact")
    if _asks_for_our_contact(visitor):
        kept: list[str] = []
        for sentence in _sentences(text):
            if exact in sentence:
                kept.append(sentence)
            elif re.search(r"support@print247|\(832\)\s*807", sentence, re.I):
                continue
            else:
                kept.append(sentence)
        text = " ".join(kept).strip()
        if exact not in text:
            text = f"{exact} {text}".strip()
    redirect = bool(priority_text) and priority_key not in {"", "email", "phone"}
    if not redirect:
        return re.sub(r"\s+", " ", text).strip()
    kept = []
    removed = False
    for sentence in _sentences(text):
        if "?" in sentence and asked_field(sentence) in {"email", "phone"}:
            removed = True
            continue
        kept.append(sentence)
    text = " ".join(kept).strip()
    needs_next = removed or (_asks_for_our_contact(visitor) and count_questions(text) == 0)
    if needs_next and priority_text.lower() not in text.lower():
        text = f"{text} {priority_text}".strip()
    return re.sub(r"\s+", " ", text).strip()


def redirect_settled_ask(
    reply: str,
    locked: tuple[str, ...] | list[str] = (),
    priority_key: str = "",
    priority_text: str = "",
) -> str:
    """A settled style or finish is not asked again. The open checklist field is."""
    locked_fields = set(locked or ())
    if not locked_fields or not priority_text:
        return reply
    asked = asked_field(reply)
    if not asked or asked not in locked_fields or asked == priority_key:
        return reply
    kept: list[str] = []
    for sentence in _sentences(reply):
        if "?" in sentence and asked_field(sentence) in locked_fields:
            continue
        kept.append(sentence)
    text = " ".join(kept).strip()
    if priority_text.lower() not in text.lower():
        text = f"{text} {priority_text}".strip()
    return re.sub(r"\s+", " ", text).strip()


def prepare_reply(
    reply: str,
    visitor: str,
    *,
    priority_key: str = "",
    priority_text: str = "",
    already_greeted: bool = False,
    locked_fields: tuple[str, ...] | list[str] = (),
) -> str:
    """Outgoing reply rules: no unsolicited MOQ, no second greeting, one question."""
    text = restore_public_contact(strip_unsolicited_moq(reply, visitor))
    if already_greeted:
        text = strip_repeated_greeting(text)
    text = shape_contact_flow(text, visitor, priority_key, priority_text)
    text = redirect_settled_ask(text, locked_fields, priority_key, priority_text)
    return enforce_single_question(text, priority_key, priority_text).strip()


def _check_answer_first(
    reply: str,
    visitor_text: str,
    state: ConversationState,
    result: GuardResult,
    handoff: bool = False,
) -> None:
    # A handoff passes the whole conversation, unanswered questions included,
    # to a person. Holding the handoff line to answer-first would leave the
    # visitor with no reply at all.
    if handoff and re.search(r"\b(?:specialist|human|team member|colleague)\b", reply, re.I):
        return
    topics = canon.topics_to_answer(visitor_text)
    for topic in topics:
        if topic == "moq" and state.family() == "banners":
            covered = bool(re.search(r"\bno minimum\b", reply, re.I))
        else:
            covered = canon.answer_covers(topic, reply)
        if covered:
            continue
        item = canon.CANON[topic]
        # Alternative-material asks are answered by reasoning from FACTS/primer,
        # not by pasting the multi-family materials sentence into the rewrite.
        if topic == "materials" and (
            wants_recommendation(visitor_text) or is_option_request(visitor_text)
        ):
            result.add(
                "unanswered_question",
                BLOCK,
                "They asked about alternative or available materials. Explain the "
                "standard material for this product family from FACTS and the "
                "CATALOGUE PRIMER, ask whether to proceed with it, name that material "
                "in the reply, keep proposed_configs empty or limited to it, and do "
                "not ask for email yet.",
                visitor_text[:120],
            )
            continue
        result.add(
            "unanswered_question",
            BLOCK,
            f"They asked about {item.label.lower()} and the reply does not answer it. "
            f"Use the written answer: {item.answer}",
            visitor_text[:120],
        )
    if is_meta_question(visitor_text) and not asks_if_bot(visitor_text):
        if not re.search(r"\b(?:sorry|i hear|understand|fair|of course|happy to explain)\b", reply, re.I):
            result.add(
                "unanswered_question",
                BLOCK,
                "They raised a complaint or asked why, and the reply does not address it.",
                visitor_text[:120],
            )
    if topics:
        return
    if is_question(visitor_text):
        sentences = _sentences(reply)
        first = sentences[0] if sentences else reply
        if count_questions(first) == 1 and first.strip().endswith("?") and not re.search(
            r"\b(?:thanks|got it|understood|sure|yes|no|certainly)\b", first, re.I
        ):
            result.add(
                "possibly_unanswered_question",
                WARN,
                "They asked something and the reply only asks the next script question; answer first.",
                visitor_text[:120],
            )


def _check_recommendation(
    reply: str,
    visitor_text: str,
    state: ConversationState,
    result: GuardResult,
    handoff: bool = False,
) -> None:
    if handoff or not wants_recommendation(visitor_text):
        return
    if RECOMMENDATION_MARKER.search(reply):
        return
    if OPTION_NOUN.search(reply) and re.search(
        r"\b(?:works?|fits?|suits?|good|best|right for|ideal for|include|includes|we have|we offer)\b",
        reply,
        re.I,
    ):
        return
    known = bool(state.fields["use_case"].value)
    result.add(
        "recommendation_unanswered",
        BLOCK if known else WARN,
        "They asked for a recommendation and the reply names no option. Suggest one from the catalogue.",
        visitor_text[:120],
    )


def _check_repeat(
    reply: str,
    state: ConversationState,
    expected: tuple[str, str] | None,
    result: GuardResult,
) -> None:
    previous, score = _repeat_against_history(reply, state)
    if not previous:
        return
    if score >= 0.95:
        field_asked = asked_field(reply) or (expected[0] if expected else None)
        field_value = state.fields.get(field_asked) if field_asked else None
        if (
            field_asked
            and field_value
            and not settled_for_asking(state, field_asked)
            and field_value.attempts < 2
        ):
            # Re-asking the same open question after an unclear answer is
            # allowed once; the QA failure is repeating a question they answered.
            return
        result.add(
            "repeated_message",
            BLOCK,
            "This is word for word what the agent already sent.",
            reply[:120],
        )
    elif score >= 0.82 and "?" in reply and "?" in previous:
        result.add(
            "repeated_question",
            BLOCK,
            "This asks the same question in almost the same words as before.",
            reply[:120],
        )
    elif score >= 0.72:
        result.add(
            "repeated_wording",
            WARN,
            "This reads very close to an earlier message.",
            reply[:120],
        )


def _check_greeting(reply: str, state: ConversationState, result: GuardResult, visitor: str = "") -> None:
    if state.turn_count == 0 or is_visitor_greeting(visitor):
        return
    if GREETING.search(reply):
        result.add("second_greeting", WARN, "Do not greet again after the first message.")
    if re.search(r"\bmy name is\b", reply, re.I):
        result.add(
            "second_intro",
            BLOCK,
            "Introducing the agent again mid-chat is a QA failure.",
            reply[:120],
        )
        return
    firsts = "|".join(re.escape(persona.first) for persona in PERSONAS)
    name_mentioned = re.search(
        rf"\b(?:this is|it's|i'm|i am)\s+({firsts})\b", reply, re.I
    )
    if name_mentioned:
        result.add("second_intro", WARN, "The agent repeats its name after the first turn.", name_mentioned.group(0))


def _check_asked_fields(
    reply: str,
    state: ConversationState,
    _expected: tuple[str, str] | None,
    handoff: bool,
    result: GuardResult,
) -> None:
    # `_expected` is the single highest-impact ask. A reply may ask any other
    # field the ask-set still allows, so this check no longer compares to it.
    field_asked = asked_field(reply)
    if field_asked:
        value = state.fields.get(field_asked)
        # `stated` is visitor or confirmed. A missing unit is still an open ask.
        if (
            value
            and value.stated
            and not (field_asked == "sizes" and state.size_needs_unit())
        ):
            words = " ".join((value.raw_visitor_text or value.value).split()).replace('"', "'")
            if len(words) > 80:
                words = words[:77] + "..."
            result.add(
                "redundant_ask",
                BLOCK,
                f'They already said the {field_asked} ("{words}"); do not ask for it again.',
                reply[:120],
            )
        if value and settled_for_asking(state, field_asked):
            result.add(
                "question_already_answered",
                WARN,
                f"They already gave the {field_asked}; asking for it again is one of the QA failures.",
                reply[:120],
            )
        elif field_asked in {"email", "phone"} and state.reachable():
            result.add(
                "question_already_answered",
                WARN,
                "A contact method is already on file; do not ask for another.",
                reply[:120],
            )
    if handoff:
        return
    # `off_script` is the script. v2 has no script to be off, so the code is gone.
    # `redundant_ask` is what still blocks a re-ask.
    allowed = state.ask_set()
    if allowed and not field_asked:
        result.add(
            "no_question_asked",
            WARN,
            f"The ask-set is {', '.join(allowed)}; the reply does not ask about one of them.",
        )


def _check_sizes(reply: str, state: ConversationState, result: GuardResult) -> None:
    if re.search(r"\b(?:our|the) standard sizes?\b|\bone of these sizes\b", reply, re.I):
        result.add(
            "invented_standard_size",
            BLOCK,
            "There is no standard size; everything is made to fit what goes inside.",
        )


CAPABILITY_VERB = re.compile(
    r"\b(?:we|i)\s+(?:make|offer|produce|print|supply|do)\b"
    r"|\b(?:we|i)\s+can\s+(?:make|do|offer)\b",
    re.I,
)
HEDGE = re.compile(
    r"\b(?:the\s+)?team\s+(?:would\s+|will\s+|can\s+)?confirm\b",
    re.I,
)
REFUSAL = re.compile(
    r"\b(?:do not|don't|cannot|can't|not offered|isn't offered|is not offered|"
    r"we (?:don't|do not|won't|cannot|can't))\b",
    re.I,
)
DIMENSION = re.compile(
    r"\b\d+(?:\.\d+)?(?:\s*(?:\"|in(?:ch(?:es)?)?|cm|mm))?"
    r"\s*[x×]\s*"
    r"\d+(?:\.\d+)?(?:\s*(?:\"|in(?:ch(?:es)?)?|cm|mm))?"
    r"(?:\s*[x×]\s*\d+(?:\.\d+)?(?:\s*(?:\"|in(?:ch(?:es)?)?|cm|mm))?)?"
    r"(?:\s*\+\s*\d+(?:\.\d+)?)?",
    re.I,
)
TYPICAL_SIZE = re.compile(r"\b(?:typical|usually|most people take)\b", re.I)
FIT_CLAIM = re.compile(
    r"\b(?:will fit|fits your|guaranteed fit|that(?:'ll| will) fit|that one will fit|perfect fit)\b",
    re.I,
)
PAYPAL_ONLY = re.compile(r"\bpaypal\b[^.?!]{0,24}\bonly\b|\bonly\b[^.?!]{0,24}\bpaypal\b", re.I)
ALIEN_PAY = re.compile(r"\b(?:bitcoin|venmo|cash\s*app|apple pay|google pay|crypto)\b", re.I)
OPERATOR_EMAIL_RE = re.compile(re.escape(canon.OPERATOR_EMAIL), re.I)
NEVER_PLACE = re.compile(r"\b(?:houston|sylmar)\b", re.I)
STREET = re.compile(r"\b1631\b|\bcottonwood\b|\bsan fernando\b", re.I)
HOURS_STATED = re.compile(r"\b(?:monday to friday|office is open|9\s*am to 5\s*pm)\b", re.I)


def _dim_tuple(fragment: str) -> tuple[str, ...]:
    return tuple(part.lstrip("0") or "0" for part in re.findall(r"\d+(?:\.\d+)?", fragment))


def _visitor_dimensions(state: ConversationState, visitor: str) -> set[tuple[str, ...]]:
    sizes = state.fields["sizes"]
    blob = " ".join([visitor or "", sizes.value or "", sizes.raw_visitor_text or ""])
    blob += " " + " ".join(state.visitor_texts())
    found: set[tuple[str, ...]] = set()
    for match in DIMENSION.finditer(blob):
        numbers = _dim_tuple(match.group(0))
        if len(numbers) >= 2:
            found.add(numbers)
    return found


def _sentence_at(reply: str, start: int) -> str:
    left = reply.rfind(".", 0, start)
    right = reply.find(".", start)
    return reply[(left + 1 if left >= 0 else 0):(right if right >= 0 else len(reply))]


def _check_dimensions(
    reply: str,
    state: ConversationState,
    visitor: str,
    registry: Registry | None,
    result: GuardResult,
) -> None:
    catalogue = registry.catalogue_dimensions() if registry is not None else set()
    visitor_dims = _visitor_dimensions(state, visitor)
    fit = bool(FIT_CLAIM.search(reply))
    for match in DIMENSION.finditer(reply):
        numbers = _dim_tuple(match.group(0))
        if len(numbers) < 2:
            continue
        sentence = _sentence_at(reply, match.start())
        if TYPICAL_SIZE.search(sentence) or fit:
            result.add(
                "unsanctioned_dimension",
                BLOCK,
                "A size was presented as typical or as a guaranteed fit. "
                "A listed size is never a fit, and a typical size is never ours.",
                match.group(0),
            )
            continue
        if numbers in catalogue or numbers in visitor_dims:
            continue
        result.add(
            "unsanctioned_dimension",
            BLOCK,
            "That dimension is not a verified catalogue size and not the visitor's own number.",
            match.group(0),
        )


def _check_tier_b_words(reply: str, result: GuardResult) -> None:
    if PAYPAL_ONLY.search(reply) or ALIEN_PAY.search(reply):
        result.add(
            "canon_conflict",
            BLOCK,
            "A payment claim contradicts the FACTS list, or names a method the facts do not.",
            (PAYPAL_ONLY.search(reply) or ALIEN_PAY.search(reply)).group(0),
        )
        result.add(
            "tier_b_hallucination",
            BLOCK,
            "A Tier B payment claim has no canon wording behind it.",
        )


def _check_contact_offer(reply: str, visitor: str, result: GuardResult) -> None:
    topics = set(canon.detect_topics(visitor))
    if OPERATOR_EMAIL_RE.search(reply):
        result.add(
            "contact_offered_unasked",
            BLOCK,
            "The operator email is never given to a visitor.",
            canon.OPERATOR_EMAIL,
        )
    if NEVER_PLACE.search(reply):
        result.add(
            "contact_offered_unasked",
            BLOCK,
            "Houston and Sylmar are not confirmed facilities.",
            NEVER_PLACE.search(reply).group(0),
        )
    if STREET.search(reply) and "location" not in topics:
        result.add(
            "contact_offered_unasked",
            WARN,
            "The street address is offerable: false. State it only when they ask.",
        )
    if HOURS_STATED.search(reply) and "hours" not in topics:
        result.add(
            "contact_offered_unasked",
            WARN,
            "Office hours are offerable: false. State them only when they ask.",
        )


def _slot_list(item: dict, *keys: str) -> list[str]:
    for key in keys:
        if key not in item or item[key] in (None, ""):
            continue
        raw = item[key]
        if isinstance(raw, str):
            text = raw.strip()
            return [text] if text else []
        return [str(value).strip() for value in raw if str(value).strip()]
    return []


def _canonical_slots(registry: Registry, family: str, slot: str, values: list[str]) -> list[str]:
    canonical: list[str] = []
    for value in values:
        normalised = registry.normalise(family, slot, value)
        if normalised.value:
            canonical.append(normalised.value)
    return canonical


def _value_in_text(value: str, text: str) -> bool:
    folded = fold(text)
    if "rigid cardboard" in value_forms(value) and re.search(r"(?<![a-z0-9])rigid(?![a-z0-9])", folded):
        return True
    for form in value_forms(value):
        if form and re.search(rf"(?<![a-z0-9]){re.escape(form)}(?![a-z0-9])", folded):
            return True
    return False


def _config_has(values: tuple[str, ...], wanted: str) -> bool:
    wanted_forms = value_forms(wanted)
    return any(value_forms(value) & wanted_forms for value in values)


def _check_configs(
    reply: str,
    registry: Registry | None,
    proposed_configs,
    result: GuardResult,
) -> None:
    # None: this reply was not a model emit, so there is no structure to reconcile.
    # An empty list is intentional: a greeting, an off-topic answer, or a correction
    # of a bad spec. Those turns must not be rejected for naming no configuration.
    if proposed_configs is None or registry is None or not proposed_configs:
        return
    configs = [item for item in proposed_configs if isinstance(item, dict)]
    if not configs:
        return
    families = tuple(
        dict.fromkeys(
            str(item.get("family") or "").strip().lower()
            for item in configs
            if str(item.get("family") or "").strip()
        )
    )
    mentions = registry.prose_mentions(reply, families or None)
    parsed: list[tuple[dict, Candidate, tuple[str, ...]]] = []
    for item in configs:
        family = str(item.get("family") or "").strip().lower() or "unknown"
        slots = {
            "style": _canonical_slots(registry, family, "style", _slot_list(item, "style")),
            "material": _canonical_slots(registry, family, "material", _slot_list(item, "material")),
            "insert": _canonical_slots(registry, family, "insert", _slot_list(item, "insert", "inserts")),
            "finish": _canonical_slots(registry, family, "finish", _slot_list(item, "finish", "finishes")),
            "extras": _canonical_slots(registry, family, "extras", _slot_list(item, "extras", "extra")),
        }
        named = tuple(value for group in slots.values() for value in group)
        for slot, values in slots.items():
            allowed: set[str] = set()
            for known in registry.values(family, slot):
                allowed |= value_forms(known)
            for value in values:
                if allowed and value_forms(value) & allowed:
                    continue
                if not allowed and not registry.values(family, slot):
                    result.add(
                        "unknown_option",
                        BLOCK,
                        f"{value} is not in the {family} {slot} vocabulary.",
                        value,
                    )
                    continue
                if not (value_forms(value) & allowed):
                    result.add(
                        "unknown_option",
                        BLOCK,
                        f"{value} is not in the {family} {slot} vocabulary.",
                        value,
                    )
        candidate = Candidate.of(family, **slots)
        parsed.append((item, candidate, named))

    if not parsed:
        if mentions:
            result.add(
                "unstructured_recommendation",
                BLOCK,
                "The reply names a catalogue option but emits no configuration containing it.",
                mentions[0][2],
            )
        return

    for _item, _candidate, named in parsed:
        for value in named:
            if not _value_in_text(value, reply):
                result.add(
                    "reply_config_mismatch",
                    BLOCK,
                    f"The configuration names {value}, and the reply never does.",
                    value,
                )
    for family, _slot, value in mentions:
        if not any(_config_has(named, value) for _item, _candidate, named in parsed if _candidate.family == family or not family):
            result.add(
                "reply_config_mismatch",
                BLOCK,
                f"The reply names {value}, and no emitted configuration contains it.",
                value,
            )

    for _item, candidate, named in parsed:
        if not named:
            continue
        match = registry.classify(candidate)
        naming = reply
        if match.state == "excluded":
            if CAPABILITY_VERB.search(naming) or not REFUSAL.search(naming):
                result.add(
                    "excluded_combination",
                    BLOCK,
                    match.reason or "That combination is excluded.",
                    " ".join(named)[:80],
                )
            else:
                exclusion = match.exclusion
                excluded_forms: set[str] = set()
                if exclusion is not None:
                    for group in (
                        exclusion.styles,
                        exclusion.materials,
                        exclusion.inserts,
                        exclusion.finishes,
                        exclusion.extras,
                    ):
                        for value in group:
                            excluded_forms |= value_forms(value)
                offered = False
                for _fam, _slot, value in mentions:
                    if not (value_forms(value) & excluded_forms):
                        alt = Candidate.of(candidate.family, **{ _slot: (value,) })
                        if registry.classify(alt).state == "attested":
                            offered = True
                if not offered:
                    result.add(
                        "nearest_alternative_missing",
                        WARN,
                        "The refusal names no attested alternative.",
                    )
            continue
        if match.state == "unknown_capability":
            if CAPABILITY_VERB.search(naming):
                result.add(
                    "unsupported_configuration",
                    BLOCK,
                    "That combination is not an attested offering, and the reply says we make it.",
                    " ".join(named)[:80],
                )
            if not HEDGE.search(naming):
                result.add(
                    "unknown_capability_unhedged",
                    BLOCK,
                    "An unattested combination needs the team to confirm the build.",
                    " ".join(named)[:80],
                )


def check_reply(
    reply: str,
    state: ConversationState,
    *,
    visitor_text: str | None = None,
    chunks=(),
    expected: tuple[str, str] | None = None,
    handoff: bool = False,
    asked_if_bot: bool = False,
    overrides: dict[str, str] | None = None,
    registry: Registry | None = None,
    proposed_configs=None,
) -> GuardResult:
    text = str(reply or "").strip()
    result = GuardResult()
    if expected is None and not handoff:
        expected = state.next_question()
    visitor = visitor_text if visitor_text is not None else state.last_visitor()
    allowed_blob = _allowed_blob(state, chunks, overrides)

    _check_length(text, result)
    _check_format(text, result)
    _check_questions(text, result)
    _check_banned(text, result)
    _check_price(text, result)
    _check_time(text, overrides, result)
    _check_bot_claim(text, asked_if_bot, result)
    _check_claims(text, allowed_blob, result, registry)
    _check_numbers(text, allowed_blob, result)
    _check_minimum(text, state, result)
    _check_answer_first(text, visitor, state, result, handoff)
    _check_recommendation(text, visitor, state, result, handoff)
    _check_repeat(text, state, expected, result)
    _check_greeting(text, state, result, visitor)
    _check_asked_fields(text, state, expected, handoff, result)
    _check_sizes(text, state, result)
    _check_dimensions(text, state, visitor, registry, result)
    _check_tier_b_words(text, result)
    _check_contact_offer(text, visitor, result)
    _check_configs(text, registry, proposed_configs, result)

    if text and not text[0].isalnum():
        result.add("formatting", WARN, "The reply starts with punctuation or a symbol.")

    return result


def strip_unsanctioned_claims(reply: str, registry: Registry | None) -> str:
    """Drop a safety or eco word the allow-list does not quote in full.

    A catalogue style name that contains the word is left as the name. The exact
    allow-list sentence is left as the sentence.
    """
    text = str(reply or "")
    for claim in sorted(SAFETY_CLAIMS, key=len, reverse=True):
        if claim.lower() not in text.lower():
            continue
        if _allowlist_covers(registry, text, claim):
            continue
        if not _claim_stands_alone(registry, text, claim):
            continue
        text = re.sub(re.escape(claim), "", text, flags=re.I)
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r" +([,.])", r"\1", text)
    return text.strip()


def describe(issues: list[Issue] | GuardResult) -> str:
    items = issues.issues if isinstance(issues, GuardResult) else issues
    text = "; ".join(f"{item.code}: {item.detail}" for item in items)
    if any(item.code == "unsupported_claim" for item in items):
        text += (
            ". REWRITE RULE: delete eco-friendly, biodegradable, compostable, recyclable, "
            "food safe, waterproof, FDA, BPA, and certified unless the reply contains the "
            "exact allow-list sentence that uses that word. Do not keep a paraphrase."
        )
    if any(item.code in {"reply_config_mismatch", "unknown_capability_unhedged", "unsupported_configuration"} for item in items):
        text += (
            ". REWRITE RULE: If you are asking for contact details, shipping info, or design "
            "counts (SKUs), focus ONLY on that ask. Do NOT re-assert or re-emit proposed_configs "
            "for styles/materials/finishes that were discussed in previous turns unless you are "
            "actively presenting a new recommendation."
        )
    return text
