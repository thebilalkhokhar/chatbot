from __future__ import annotations

import re
from dataclasses import dataclass, field

from . import canon
from .personas import PERSONAS
from .state import (
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
    is_question,
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
GREETING = re.compile(r"^\s*(?:hi|hello|hey|good (?:morning|afternoon|evening))\b", re.I)
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
    ("finishes", re.compile(r"\b(?:finish|finishes|matte|gloss|soft touch)\b", re.I)),
    ("skus", re.compile(r"\b(?:designs?|skus?)\b", re.I)),
    ("style", re.compile(r"\b(?:style|flat|stand[- ]?up|flat[- ]?bottom|reference image)\b", re.I)),
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
    for key, pattern in FIELD_PROBES:
        if pattern.search(scope):
            return key
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
    elif words > 95:
        result.add("too_long", BLOCK, f"The reply is {words} words; keep it under about 60.", reply[:80])
    elif words > 65:
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
            BLOCK,
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
            WARN,
            "The visitor asked whether this is a bot; the reply should say it is an AI assistant.",
        )


def _check_claims(reply: str, allowed_blob: str, result: GuardResult) -> None:
    lowered_reply = reply.lower()
    lowered_allowed = allowed_blob.lower()
    for claim in canon.CLAIM_WORDS:
        if claim in lowered_reply and claim not in lowered_allowed:
            result.add(
                "unsupported_claim",
                BLOCK,
                f"'{claim}' is not in the knowledge base or the written answers.",
                claim,
            )


def _check_numbers(reply: str, allowed_blob: str, result: GuardResult) -> None:
    allowed = _numbers(allowed_blob) | IGNORED_NUMBERS
    if "24/7" in reply:
        allowed |= {"24", "7"}
    if "24/7" in allowed_blob:
        allowed |= {"24", "7"}
    for number in _numbers(reply):
        if number in allowed:
            continue
        result.add(
            "untraceable_number",
            BLOCK,
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
                WARN,
                "500 is only correct with multiple designs; say 1,000 per size for a single design.",
            )


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
    topics = canon.detect_topics(visitor_text)
    for topic in topics:
        if topic == "moq" and state.family() == "banners":
            covered = bool(re.search(r"\bno minimum\b", reply, re.I))
        else:
            covered = canon.answer_covers(topic, reply)
        if covered:
            continue
        item = canon.CANON[topic]
        result.add(
            "unanswered_question",
            BLOCK,
            f"They asked about {item.label.lower()} and the reply does not answer it. "
            f"Use the written answer: {item.answer}",
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
    result: GuardResult,
    handoff: bool = False,
) -> None:
    if handoff or not wants_recommendation(visitor_text):
        return
    if RECOMMENDATION_MARKER.search(reply):
        return
    if OPTION_NOUN.search(reply) and re.search(
        r"\b(?:works?|fits?|suits?|good|best|right for|ideal for)\b", reply, re.I
    ):
        return
    result.add(
        "recommendation_unanswered",
        WARN,
        "They asked for a recommendation and the reply names no option. Suggest one from the KB excerpts.",
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


def _check_greeting(reply: str, state: ConversationState, result: GuardResult) -> None:
    if state.turn_count == 0:
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
                BLOCK,
                f"They already gave the {field_asked}; asking for it again is one of the QA failures.",
                reply[:120],
            )
        elif field_asked in {"email", "phone"} and state.reachable():
            result.add(
                "question_already_answered",
                BLOCK,
                "A contact method is already on file; do not ask for another.",
                reply[:120],
            )
    if handoff:
        return
    # Section 3.4: the model may pick any field in the ask-set. `off_script` stays
    # (Phase 2 keeps every v1 guard) but it no longer enforces script position —
    # it fires only when the reply asks about a field the ask-set does not allow.
    allowed = state.ask_set()
    allowed_set = set(allowed)
    if field_asked and field_asked not in allowed_set:
        listed = ", ".join(allowed) if allowed else "nothing may be asked"
        result.add(
            "off_script",
            WARN,
            f"The reply asks about {field_asked}, which is outside the ask-set ({listed}).",
            reply[:120],
        )
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
            WARN,
            "There is no standard size; everything is made to fit what goes inside.",
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
    _check_claims(text, allowed_blob, result)
    _check_numbers(text, allowed_blob, result)
    _check_minimum(text, state, result)
    _check_answer_first(text, visitor, state, result, handoff)
    _check_recommendation(text, visitor, result, handoff)
    _check_repeat(text, state, expected, result)
    _check_greeting(text, state, result)
    _check_asked_fields(text, state, expected, handoff, result)
    _check_sizes(text, state, result)

    if text and not text[0].isalnum():
        result.add("formatting", WARN, "The reply starts with punctuation or a symbol.")

    return result


def describe(issues: list[Issue] | GuardResult) -> str:
    items = issues.issues if isinstance(issues, GuardResult) else issues
    return "; ".join(f"{item.code}: {item.detail}" for item in items)
