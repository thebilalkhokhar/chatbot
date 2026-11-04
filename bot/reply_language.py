"""Dynamic language pass: LLM detects language, anglicises inbound, translates outbound.

The bot reasons, extracts, and guards in English. Non-English visitors are handled
with two LLM steps (no per-language word lists):

1. Inbound — detect the visitor's language and rewrite their latest message into
   English for extract/spelling (numbers as digits, units as in/cm/mm, catalogue
   terms in English when clear).
2. Outbound — translate the English reply into the session language on the way out.

What the visitor typed stays on Message.text; the English gloss is Message.english.
What the visitor saw of a bot line is Message.shown.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Iterable

from .llm import LLMClient, LLMError
from .state import UNIT_ONLY_RE, asks_language_preference
from .visitor_language import ENGLISH

log = logging.getLogger("chatbot.reply_language")

# Wall-clock budget from request start for the whole turn (compose + language).
# Overridden at call sites with config.timeout_s + language headroom when available.
SEND_BY_S = 20.0
# HTTP timeout for one inbound or outbound language call.
LANGUAGE_S = 5.0


def turn_language_budget_s(compose_timeout_s: float) -> float:
    """Enough wall time for compose, reply judge, inbound, and outbound language calls."""
    # +3s headroom matches reply_judge.JUDGE_S without importing that module here.
    return float(compose_timeout_s or 6.0) + (2.0 * LANGUAGE_S) + 3.0 + 1.0

INBOUND_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "language": {
            "type": "string",
            "description": "English name of the language the visitor is writing in, e.g. English, Spanish, German.",
        },
        "english": {
            "type": "string",
            "description": "The same message rewritten in English for the sales extract engine.",
        },
    },
    "required": ["language", "english"],
}

_SENTENCE_SPLIT = re.compile(
    r"(?<=[.!?])(?<!e\.g\.)(?<!i\.e\.)(\s+)(?=[A-Z¿¡(\"“•])"
)
_ONLY_SPACE = re.compile(r"^\s+$")
_ONLY_NEWLINES = re.compile(r"^\n+$")
_EMAIL_ONLY = re.compile(r"^[\w.+-]+@[\w-]+\.[\w.]+$", re.I)
_PHONE_ONLY = re.compile(r"^[\d\s().+\-]{7,}$")
_NUMERIC_SIZE = re.compile(
    r"^[\d\s./x×*\-byBY]+(?:\s*(?:in|inch|inches|cm|mm|ft|foot|feet))?$",
    re.I,
)


@dataclass(frozen=True)
class InboundLanguage:
    language: str
    english: str


def pieces_of(text: str) -> list[tuple[str, bool]]:
    """Split a reply into sentences and the spaces/newlines between them."""
    parts: list[tuple[str, bool]] = []
    for line in re.split(r"(\n+)", str(text or "")):
        if not line:
            continue
        if _ONLY_NEWLINES.fullmatch(line):
            parts.append((line, False))
            continue
        for sentence in _SENTENCE_SPLIT.split(line):
            if not sentence:
                continue
            parts.append((sentence, not bool(_ONLY_SPACE.fullmatch(sentence))))
    return parts


def skip_inbound_llm(text: str) -> bool:
    """True when the message carries no language to detect (email/phone/pure size digits)."""
    value = str(text or "").strip()
    if not value:
        return True
    if _EMAIL_ONLY.fullmatch(value):
        return True
    if _PHONE_ONLY.fullmatch(value) and sum(ch.isdigit() for ch in value) >= 7:
        return True
    if _NUMERIC_SIZE.fullmatch(value):
        return True
    return False


def _inbound_system() -> str:
    return "\n".join(
        [
            "You normalise one live-chat message from a packaging customer for an English-only sales engine.",
            'Return JSON: {"language": "...", "english": "..."}.',
            "language = the common English name of the language they are writing in "
            "(English, Spanish, French, Portuguese, German, Italian, Arabic, Russian, "
            "Chinese, Japanese, Korean, Hindi, …).",
            "If they clearly switch into English with a full English sentence, language is English.",
            "If they ask you to speak or continue in a named language, set language to that "
            "language (not English), even though english is the English gloss of their ask.",
            "If this message alone is too short to tell (yes/no/ok, a number, an email, a size, "
            "a unit, or a catalogue style/material/finish name), keep the prior session language — "
            "do not flip to English.",
            "english = a faithful ENGLISH rendering of ONLY the Latest message (never a summary "
            "of earlier turns, never paste prior quantities/finishes/sizes into this field).",
            "Rules for english:",
            "- MUST be English words only. Never copy non-English wording into english.",
            "- Quantities MUST use digits only (300 not three hundred; 1000 not one thousand).",
            "- Size units alone → exactly one of: in, inches, cm, mm, ft, feet "
            "(translate any non-English unit word; never leave the original unit word).",
            "- Dimension lines keep numbers; append the English unit when they named one.",
            "- Suggestion / recommendation asks → natural English "
            "(e.g. Any suggestions?, What do you recommend?).",
            "- No preference / not sure / no idea → those English phrases.",
            "- Product / finish / style → ordinary English packaging terms "
            "(boxes, bags, labels, mailer, kraft, display, gift, matte lamination, gloss "
            "lamination, soft touch lamination, spot UV, foil printing, white cardboard, "
            "corrugated) when that is the meaning.",
            "- Keep emails, phones, URLs, and numeric sizes intact.",
            "- Add nothing and leave nothing out.",
            "If the message is already English, language=English and english is the same text.",
        ]
    )


# Capture the language they named in "do you speak X?" / "in X please" (English gloss).
_NAMED_LANGUAGE_IN_ASK = re.compile(
    r"(?:do you|can you|are you able to|will you)\s+"
    r"(?:speak|talk|write|reply|answer|chat|continue)\s+"
    r"(?:to me\s+)?(?:in\s+)?([A-Za-z][A-Za-z\-]+)"
    r"|please\s+(?:speak|talk|write|reply|answer|chat)\s+(?:to me\s+)?(?:in\s+)?([A-Za-z][A-Za-z\-]+)"
    r"|(?:speak|talk|write|reply|answer|chat)\s+(?:to me\s+)?(?:in\s+)?([A-Za-z][A-Za-z\-]+)\s+please"
    r"|(?:speak|talk|write|reply|answer|chat)\s+(?:to me\s+)?in\s+([A-Za-z][A-Za-z\-]+)"
    r"|\bin\s+([A-Za-z][A-Za-z\-]+)\s+please\b"
    r"|\b(?:switch|change)\s+(?:to|into)\s+([A-Za-z][A-Za-z\-]+)\b"
    # Raw chips: "¿Hablas español?", "Parlez-vous français?"
    r"|\b(?:hablas|habla|parlez[- ]vous|parles[- ]tu|sprechen\s+sie|sprichst\s+du|"
    r"falas?|parli|parlate|puedes|puede|kannst\s+du)\b.{0,24}\b"
    r"(espa[nñ]ol|spanish|fran[cç]ais|french|deutsch|german|english|ingl[eé]s|"
    r"italiano|italian|portugu[eê]s|portuguese|arabic|chinese|mandarin|hindi|urdu)\b",
    re.I,
)
_NAMED_LANGUAGE_SKIP = frozenset(
    {
        "to",
        "me",
        "in",
        "a",
        "an",
        "the",
        "your",
        "my",
        "this",
        "that",
        "with",
        "us",
        "please",
        "english",  # asking "speak English?" keeps English via prior/default
    }
)
_LANGUAGE_ENDONYM_TO_ENGLISH = {
    "español": "Spanish",
    "espanol": "Spanish",
    "spanish": "Spanish",
    "français": "French",
    "francais": "French",
    "french": "French",
    "deutsch": "German",
    "german": "German",
    "inglés": "English",
    "ingles": "English",
    "english": "English",
    "italiano": "Italian",
    "italian": "Italian",
    "português": "Portuguese",
    "portugues": "Portuguese",
    "portuguese": "Portuguese",
    "arabic": "Arabic",
    "chinese": "Chinese",
    "mandarin": "Mandarin",
    "hindi": "Hindi",
    "urdu": "Urdu",
}


def language_named_in_preference_ask(english: str) -> str:
    """English name of the language they asked to use, if the gloss names one."""
    match = _NAMED_LANGUAGE_IN_ASK.search(str(english or ""))
    if not match:
        return ""
    name = next((group for group in match.groups() if group), "")
    if not name or name.casefold() in _NAMED_LANGUAGE_SKIP:
        return ""
    mapped = _LANGUAGE_ENDONYM_TO_ENGLISH.get(name.casefold())
    if mapped:
        return mapped
    return name[0].upper() + name[1:]


def heuristic_language_preference_gloss(raw: str) -> tuple[str, str] | None:
    """When inbound LLM times out, still route ¿Hablas…? to the language-ack path."""
    value = str(raw or "").strip()
    if not value or not asks_language_preference(value):
        return None
    named = language_named_in_preference_ask(value) or "Spanish"
    return named, f"Do you speak {named}?"


def _looks_like_language_ask_raw(raw: str) -> bool:
    """Raw (possibly non-English) still looks like a language preference ask."""
    value = str(raw or "").strip()
    if not value:
        return False
    if asks_language_preference(value):
        return True
    # Interrogative language chips ("¿Hablas …?", "Parlez-vous …?") before gloss.
    if ("?" in value or "¿" in value) and len(value.split()) <= 8:
        return True
    return False


def _ambiguous_short_for_language(raw: str) -> bool:
    """Yes/no, numbers, email, size, unit, short catalogue picks — not a language switch."""
    value = str(raw or "").strip()
    if not value:
        return True
    if skip_inbound_llm(value):
        return True
    if len(value.split()) <= 6 and not asks_language_preference(value):
        return True
    return False


def sticky_session_language(prior: str, detected: str, raw: str) -> str:
    """Keep non-English session language on short / catalogue replies that look 'English'."""
    prior_lang = str(prior or ENGLISH).strip() or ENGLISH
    detected_lang = str(detected or prior_lang).strip() or prior_lang
    if prior_lang.casefold() == ENGLISH.casefold():
        return detected_lang
    if detected_lang.casefold() != ENGLISH.casefold():
        return detected_lang
    if _ambiguous_short_for_language(raw):
        return prior_lang
    return detected_lang


def _parse_inbound(parsed: dict, *, prior: str, raw: str) -> InboundLanguage:
    language = str(parsed.get("language") or prior).strip() or prior
    english = str(parsed.get("english") or raw).strip() or raw
    if len(language) <= 3 and language.isalpha():
        language = prior if prior != ENGLISH else language.upper()
    # Prior-turn bleed: short field answers must not become "Do you speak …?".
    if asks_language_preference(english) and not _looks_like_language_ask_raw(raw):
        english = raw
    # Prefer the language they asked to speak, even if the model marked English.
    named = language_named_in_preference_ask(english)
    if named:
        language = named
    else:
        language = sticky_session_language(prior, language, raw)
    # Normalise common "Español" / "Deutsch" labels to English names when obvious
    # via a second LLM pass is unnecessary — outbound prompt accepts any label.
    return InboundLanguage(language=language, english=english)


def _needs_anglicise_retry(
    result: InboundLanguage,
    raw: str,
    *,
    open_field: str = "",
) -> bool:
    """True when language is non-English but english was left unusable for extract."""
    if not result:
        return False
    if result.language.strip().casefold() in {"", ENGLISH.casefold()}:
        return False
    english = result.english.strip()
    if english.casefold() == raw.strip().casefold():
        return True
    # Size unit follow-up still not an English unit token (e.g. left as a foreign word).
    if (
        str(open_field or "").strip() == "sizes"
        and not re.search(r"\d", english)
        and len(english.split()) <= 3
        and not UNIT_ONLY_RE.match(english)
    ):
        return True
    return False


def normalize_inbound(
    client: LLMClient,
    text: str,
    *,
    prior_language: str = ENGLISH,
    recent_visitor: Iterable[str] = (),
    open_field: str = "",
    catalogue_terms: Iterable[str] = (),
    ms_left: float,
) -> InboundLanguage | None:
    """Detect language and return an English gloss for extract. None on timeout/error."""
    raw = str(text or "").strip()
    if not raw:
        return InboundLanguage(language=prior_language or ENGLISH, english="")

    prior = str(prior_language or ENGLISH).strip() or ENGLISH
    if skip_inbound_llm(raw):
        return InboundLanguage(language=prior, english=raw)

    timeout_s = min(LANGUAGE_S, max(0.0, ms_left / 1000.0))
    if timeout_s < 0.2:
        log.info("inbound language skipped: only %.0fms left", ms_left)
        return None

    recent = [str(item).strip()[:300] for item in recent_visitor if str(item).strip()]
    recent = recent[-3:]
    terms = [str(item).strip() for item in catalogue_terms if str(item).strip()]
    # Cap so the inbound prompt stays small; prefer first catalogue rows.
    terms = terms[:40]
    field = str(open_field or "").strip()
    user_parts = [
        f"Prior session language: {prior}",
        f"Latest message: {raw}",
    ]
    if recent:
        user_parts.insert(1, "Recent visitor messages:\n" + "\n".join(f"- {item}" for item in recent))
    if field:
        user_parts.append(f"Open quote field being answered: {field}")
    if field == "sizes":
        user_parts.append(
            "If Latest answers the unit follow-up (unit only, no new numbers), english "
            "MUST be exactly one of: in, inches, cm, mm, ft, feet."
        )
    if field == "skus":
        user_parts.append(
            "If they ask for a suggestion or say they have no idea / no preference / "
            "no designs yet, english must use those English phrases so the quote engine "
            "can match them."
        )
    if field and terms:
        user_parts.append(
            "If they are choosing an option for that field, set english to the closest "
            "catalogue term from this list (copy spelling exactly when it fits): "
            + "; ".join(terms)
        )
    user = "\n\n".join(user_parts)

    try:
        parsed = client.complete_json(
            _inbound_system(),
            user,
            INBOUND_SCHEMA,
            name="chat_inbound_language",
            timeout_s=timeout_s,
            # Need the real address/number in the gloss; compose calls still mask PII.
            mask_pii=False,
        )
        result = _parse_inbound(parsed, prior=prior, raw=raw)
        # Model sometimes sets language correctly but leaves english untranslated.
        if _needs_anglicise_retry(result, raw, open_field=field):
            remaining = min(LANGUAGE_S, max(0.0, (ms_left / 1000.0) - timeout_s * 0.5))
            if remaining >= 0.4:
                field_hint = ""
                if field == "sizes":
                    field_hint = (
                        " This is a size-unit answer: english must be in, inches, cm, mm, "
                        "ft, or feet only."
                    )
                elif field == "skus":
                    field_hint = (
                        " If they want ideas, english like 'Any suggestions?'. "
                        "If unsure, english like 'no idea' or 'no preference'."
                    )
                retry_user = (
                    user
                    + "\n\nCORRECTION: language is not English, but your english field is still "
                    "unusable for the English extract engine. Rewrite english into clear "
                    "English packaging chat wording now. Do not repeat the original "
                    "non-English words."
                    + field_hint
                )
                parsed = client.complete_json(
                    _inbound_system(),
                    retry_user,
                    INBOUND_SCHEMA,
                    name="chat_inbound_language_retry",
                    timeout_s=remaining,
                    mask_pii=False,
                )
                result = _parse_inbound(parsed, prior=result.language or prior, raw=raw)
        return result
    except Exception as error:  # noqa: BLE001
        log.warning("inbound language failed: %s", error)
        return None


def translate_outbound(
    texts: list[str],
    *,
    language: str,
    client: LLMClient,
    visitor_samples: Iterable[str] = (),
    ms_left: float,
) -> list[str] | None:
    """Translate English bot lines into `language`. None on timeout/error."""
    target = str(language or ENGLISH).strip() or ENGLISH
    if target == ENGLISH:
        return texts

    pieces = [pieces_of(text) for text in texts]
    pending: list[tuple[str, int, int]] = []
    for index, parts in enumerate(pieces):
        for at, (text, translate) in enumerate(parts):
            if translate and text.strip():
                pending.append((text, index, at))
    if not pending:
        return texts

    timeout_s = min(LANGUAGE_S, max(0.0, ms_left / 1000.0))
    if timeout_s < 0.2:
        log.info("outbound language skipped: only %.0fms left", ms_left)
        return None

    samples = [str(item).strip()[:300] for item in visitor_samples if str(item).strip()]
    samples = samples[-3:]
    system = "\n".join(
        [
            f"Translate chat messages from a Print247 sales rep into {target}, "
            "the language the customer is writing in.",
            "Write the way a friendly sales rep types in a live chat in that language, "
            "matching the customer's own variety of it.",
            "Keep numbers, sizes with units, quantities, prices, email addresses, "
            "phone numbers and links exactly as they are.",
            f"Translate the whole sentence into {target}, including product option names "
            "(styles, materials, finishes). Do not leave English catalogue labels mixed "
            f"into a {target} sentence — translate those labels too.",
            "Keep the meaning, the question and the length. Add nothing and leave nothing out.",
            "Each entry is one sentence of a message. Translate every word of every entry "
            f"into {target}.",
            'Reply with JSON: {"translations": ["...", ...]}, one entry per entry given, '
            "in the same order.",
        ]
    )
    user = (
        (f"The customer has written:\n" + "\n".join(f"- {item}" for item in samples) + "\n\n" if samples else "")
        + "Messages to translate:\n"
        + json.dumps([text for text, _, _ in pending], ensure_ascii=False)
    )
    try:
        parsed = client.complete_object(
            system,
            user,
            name="chat-outbound-language",
            timeout_s=timeout_s,
            temperature=0.0,
        )
        translations = parsed.get("translations")
        if not isinstance(translations, list) or len(translations) != len(pending):
            raise LLMError(
                f"expected {len(pending)} translations, got "
                f"{len(translations) if isinstance(translations, list) else type(translations)}"
            )
        mutable = [[list(part) for part in parts] for parts in pieces]
        for (_src, index, at), translated in zip(pending, translations):
            text = str(translated or "").strip()
            if text:
                mutable[index][at][0] = text
        return ["".join(part[0] for part in parts) for parts in mutable]
    except Exception as error:  # noqa: BLE001
        log.warning("could not translate the reply into %s: %s", target, error)
        return None


# Back-compat aliases used by older call sites / tests.
TRANSLATION_S = LANGUAGE_S


def translate_replies(
    texts: list[str],
    messages: Iterable[dict | object],
    client: LLMClient,
    *,
    ms_left: float,
    language: str = "",
) -> list[str] | None:
    """Outbound translate; language comes from the session (not word-list detection)."""
    target = str(language or "").strip()
    if not target:
        target = ENGLISH
    samples = []
    for message in messages:
        if isinstance(message, dict):
            author = str(message.get("author") or "")
            text = str(message.get("text") or "")
        else:
            author = str(getattr(message, "author", "") or "")
            text = str(getattr(message, "text", "") or "")
        if author == "visitor" and text.strip():
            samples.append(text)
    return translate_outbound(
        texts,
        language=target,
        client=client,
        visitor_samples=samples,
        ms_left=ms_left,
    )
