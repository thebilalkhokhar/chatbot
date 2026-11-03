"""Dynamic spelling help: catalogue fuzzy (rapidfuzz) + English words (pyspellchecker)."""

from __future__ import annotations

import re
from functools import lru_cache

from .state import (
    CATALOGUE_OPTION_FIELDS,
    FINISH_WORDS,
    MATERIAL_HINTS,
    STYLE_VALUES,
)

# Minimum rapidfuzz score to accept a catalogue near-match (0–100).
CATALOGUE_FUZZY_SCORE = 80
# Winner must beat the runner-up by this much, or be the only hit above threshold.
CATALOGUE_FUZZY_MARGIN = 8

# Short legacy tokens for fuzzy fallback when the registry is absent. Bare fillers
# like "paper" are omitted: they outrank real labels ("SBS paperboard") under WRatio.
_MATERIAL_CANDIDATES = tuple(
    sorted(
        {
            "pet",
            "mpet",
            "rpet",
            "kraft",
            "foil",
            "metalized",
            "metallized",
            "cardstock",
            "corrugated",
            "vinyl",
            "bopp",
            "pp",
            "pe",
            "plastic",
            "clear",
            "holographic",
            "silver",
            "gold",
            "white",
            "pp white vinyl",
            "rigid cardboard",
        }
    )
)


@lru_cache(maxsize=1)
def _spellchecker():
    from spellchecker import SpellChecker

    return SpellChecker()


def _unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        key = re.sub(r"\s+", " ", str(value or "").strip().lower())
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(str(value).strip())
    return out


def catalogue_candidates(field: str, family: str = "", registry=None) -> list[str]:
    """Closed option list for the open catalogue field (dynamic from registry + local vocab)."""
    key = str(field or "").strip()
    fam = str(family or "").strip()
    found: list[str] = []
    if key == "finishes":
        found.extend(label for label in FINISH_WORDS if label != "none")
        if fam in {"boxes", "unknown", ""}:
            found.extend(
                (
                    "matte lamination",
                    "gloss lamination",
                    "soft touch lamination",
                    "spot UV",
                    "foil printing",
                )
            )
        if registry is not None and fam and fam != "unknown":
            found.extend(registry.values(fam, "finish"))
    elif key == "style":
        found.extend(label for label, _words in STYLE_VALUES)
        if registry is not None and fam and fam != "unknown":
            found.extend(registry.values(fam, "style"))
    elif key == "material":
        found.extend(_MATERIAL_CANDIDATES)
        if registry is not None and fam and fam != "unknown":
            found.extend(registry.values(fam, "material"))
    return _unique(found)


def _option_family(field: str, value: str) -> str:
    """Collapse near-duplicate catalogue labels so gloss ≈ gloss lamination."""
    text = re.sub(r"\s+", " ", str(value or "").strip().lower())
    if field == "finishes":
        from .state import normalize_finish

        normalized = normalize_finish(text) or text
        for suffix in (" lamination", " printing", " stamping"):
            if normalized.endswith(suffix):
                return normalized[: -len(suffix)].strip()
        return normalized
    if field == "style":
        from .state import normalize_style

        return (normalize_style(text) or text).lower()
    if field == "material":
        # Keep the registry label. Only fold the metallized spelling variant.
        if text in {"metallized", "metalized"}:
            return "metalized"
        return text
    return text


def fuzzy_catalogue_match(
    text: str,
    field: str,
    *,
    family: str = "",
    registry=None,
    score_cutoff: int = CATALOGUE_FUZZY_SCORE,
) -> str:
    """Best catalogue option for a typo'd answer, or '' if not confident."""
    if field not in CATALOGUE_OPTION_FIELDS:
        return ""
    query = re.sub(r"\s+", " ", str(text or "").strip().lower())
    if not query or len(query) > 48:
        return ""
    candidates = catalogue_candidates(field, family, registry)
    if not candidates:
        return ""
    # Don't map a clear material/finish token onto the wrong open field
    # (e.g. "metalized" must not become style "Metalized Boxes").
    if field == "style":
        from .state import STYLE_HINTS

        if MATERIAL_HINTS.search(query) and not STYLE_HINTS.search(query):
            return ""
        from .state import normalize_finish

        if normalize_finish(query) and not STYLE_HINTS.search(query):
            return ""
    # Exact catalogue label (case-insensitive) wins before fuzzy — stops bare
    # tokens like "paperboard" outranking the full "SBS paperboard" phrase.
    for candidate in candidates:
        if re.sub(r"\s+", " ", candidate.strip().lower()) == query:
            if field == "material" and query in {"metallized", "metalized"}:
                return "metalized"
            return str(candidate).strip()
    try:
        from rapidfuzz import fuzz, process
    except ImportError:
        return ""

    # Style: also try without trailing "box/bag" ("mail box" → "mail" → mailer).
    queries = [query]
    if field == "style":
        stripped = re.sub(
            r"\b(?:box(?:es)?|bag(?:s)?|pouches?|packaging)\b",
            " ",
            query,
        )
        stripped = re.sub(r"\s+", " ", stripped).strip(" -/")
        if stripped and stripped != query:
            queries.append(stripped)

    by_family: dict[str, tuple[str, float]] = {}
    for variant in queries:
        # Prefer ratio: WRatio inflates short tokens ("pe", "paperboard") against
        # longer registry labels. Single-token typos still score well on ratio.
        scorer = fuzz.ratio
        hits = process.extract(
            variant,
            candidates,
            scorer=scorer,
            processor=lambda value: re.sub(r"\s+", " ", str(value or "").strip().lower()),
            limit=5,
            score_cutoff=max(60, score_cutoff - 15),
        )
        for value, score, _ in hits:
            fam = _option_family(field, value)
            if not fam or fam == "none":
                continue
            prev = by_family.get(fam)
            if prev is None or score > prev[1]:
                by_family[fam] = (value, float(score))
    if not by_family:
        return ""
    ranked = sorted(by_family.items(), key=lambda item: item[1][1], reverse=True)
    best_fam, (best_value, best_score) = ranked[0]
    if best_score < score_cutoff:
        return ""
    if len(ranked) > 1:
        second_score = ranked[1][1][1]
        if best_score - second_score < CATALOGUE_FUZZY_MARGIN and second_score >= score_cutoff - 5:
            # Two close distinct catalogue families — do not guess.
            return ""
    # Short visitor typo → short catalogue label (mate→matte, not matte lamination).
    if field == "finishes":
        from .state import normalize_finish

        if len(query.split()) == 1 and best_fam in FINISH_WORDS and best_fam != "none":
            return best_fam
        normalized = normalize_finish(best_value)
        if normalized and normalized != "none":
            return normalized
    if field == "style":
        from .state import normalize_style

        normalized = normalize_style(best_value)
        if normalized:
            return normalized
        if best_fam:
            return best_fam
    if field == "material":
        label = str(best_value).strip()
        if label.lower() in {"metallized", "metalized"}:
            return "metalized"
        return label
    return str(best_value).strip()


def protect_terms(family: str = "", registry=None) -> frozenset[str]:
    """Words English spell-correction must not rewrite (catalogue / brand tokens)."""
    protected: set[str] = set()
    for label, words in FINISH_WORDS.items():
        protected.add(label.lower())
        protected.update(word.lower() for word in words)
    for label, words in STYLE_VALUES:
        protected.add(label.lower())
        protected.update(word.lower() for word in words)
    protected.update(_MATERIAL_CANDIDATES)
    if registry is not None:
        fam = str(family or "").strip()
        if fam and fam != "unknown":
            for slot in ("style", "material", "finish", "extras"):
                for value in registry.values(fam, slot):
                    protected.update(re.findall(r"[a-z0-9]+", str(value).lower()))
        else:
            for fam_name in getattr(registry, "families", ()) or ():
                for slot in ("style", "material", "finish", "extras"):
                    for value in registry.values(fam_name, slot):
                        protected.update(re.findall(r"[a-z0-9]+", str(value).lower()))
    # Packaging / chat tokens that English dict may not know.
    protected.update(
        {
            "mylar",
            "doypack",
            "mailer",
            "sku",
            "skus",
            "moq",
            "print247",
            "lamination",
            "cardstock",
            "corrugated",
            "bopp",
            "rpet",
            "mpet",
        }
    )
    return frozenset(protected)


# Chat / waiver tokens pyspellchecker happily "fixes" into nonsense (dont→donut).
_CHAT_PROTECTED = frozenset(
    {
        "dont",
        "wont",
        "cant",
        "isnt",
        "arent",
        "didnt",
        "doesnt",
        "havent",
        "hasnt",
        "wasnt",
        "werent",
        "im",
        "ive",
        "idk",
        "dunno",
        "gonna",
        "wanna",
        "gotta",
        "lemme",
        "yall",
    }
)


def correct_english_spelling(text: str, *, protect: frozenset[str] | None = None) -> str:
    """Correct free-English typos (adress → address). Leaves catalogue/protected tokens alone."""
    value = str(text or "")
    if not value or "@" in value or re.search(r"\d", value):
        # Sizes, qty, emails — do not spell-rewrite.
        return value
    try:
        spell = _spellchecker()
    except Exception:
        return value
    blocked = {term.lower() for term in (protect or frozenset())} | set(_CHAT_PROTECTED)

    def fix_token(match: re.Match[str]) -> str:
        raw = match.group(0)
        low = raw.lower()
        if len(low) < 4 or low in blocked:
            return raw
        if low in spell:
            return raw
        candidates = spell.candidates(low) or set()
        if not candidates:
            return raw
        # pyspellchecker.correction() often picks "dress" for "adress";
        # rank candidates with rapidfuzz and prefer longer ties (address).
        try:
            from rapidfuzz import fuzz

            ranked = sorted(
                ((fuzz.WRatio(low, cand), len(cand), cand) for cand in candidates),
                key=lambda row: (row[0], row[1]),
                reverse=True,
            )
            best_score, _, suggestion = ranked[0]
            if best_score < 85:
                return raw
        except ImportError:
            suggestion = spell.correction(low)
        if not suggestion or suggestion == low:
            return raw
        # Protect means "do not rewrite catalogue tokens that are already correct"
        # (matt, kraft). Still allow typos TO land on a protected word
        # (adress → address from "Address Labels" vocab).
        if raw.isupper():
            return suggestion.upper()
        if raw[0].isupper():
            return suggestion.capitalize()
        return suggestion

    return re.sub(r"\b[A-Za-z]{4,}\b", fix_token, value)


def prepare_visitor_text(
    text: str,
    last_question: str,
    *,
    family: str = "",
    registry=None,
) -> tuple[str, str]:
    """Return (text_for_extract, catalogue_fuzzy_value_or_empty).

    Catalogue open-field typos use rapidfuzz against options. Other free text
    uses pyspellchecker for English spelling.
    """
    original = str(text or "")
    field = str(last_question or "").strip()
    from .state import UNSPECIFIED_RE

    # Leave "i dont know" / "not sure" alone so waiver regexes still match.
    if UNSPECIFIED_RE.match(original):
        return original, ""
    if field in CATALOGUE_OPTION_FIELDS:
        hit = fuzzy_catalogue_match(original, field, family=family, registry=registry)
        if hit:
            return original, hit
        # No catalogue hit — still try English cleanup for longer answers.
        protected = protect_terms(family, registry)
        return correct_english_spelling(original, protect=protected), ""
    if field in {"email", "phone"}:
        return original, ""
    # sizes/quantity/skus: keep numeric answers intact, but still fix English so
    # "can you give me your adress" becomes a location question, not dead air.
    if field in {"sizes", "quantity", "skus"} and (
        "@" in original or re.search(r"\d", original)
    ):
        return original, ""
    protected = protect_terms(family, registry)
    return correct_english_spelling(original, protect=protected), ""
