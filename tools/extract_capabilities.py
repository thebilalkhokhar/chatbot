"""Derive capability-registry rows from the kb_v2 corpus, seeded by curated vocabulary.

Read-only over kb_v2/. Prints a report to stderr and ```capability blocks to stdout. No LLM call.

How a catalogue value reaches the registry:

  1. every product page's Materials / Finishes / Add-ons bullet is split on its own delimiters
     (commas, semicolons, "and", "+", "aka") into candidate values;
  2. each candidate is matched against the curated lexicon on **whole words only** — the two
     sources of the first attempt's garbage were substring matching ("rboard" out of
     "chipboard") and sentence fragments, both of which need partial words to be admitted;
  3. unmatched word groups are reported as **proposals** with their frequency and citations.

Accepted proposals are re-fed to this tool through `tools/accepted_vocabulary.txt` (one value per
line, optionally `slot: value`), so the lexicon grows by review and never by guess. Everything
matching nothing stays out of the rows.
"""

from __future__ import annotations

import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "chatbot"))

from bot.capability import parse_tables  # noqa: E402

CORPUS = ROOT / "kb_v2"
REGISTRY_MD = ROOT / "kb" / "capabilities" / "capability-registry.md"
ACCEPTED_MD = ROOT / "chatbot" / "tools" / "accepted_vocabulary.txt"

FAMILY_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("business_cards", re.compile(r"\bbusiness cards?\b", re.I)),
    ("labels", re.compile(r"\b(labels?|stickers?|decals?|clings?)\b", re.I)),
    ("bags", re.compile(r"\b(bags?|pouch(?:es)?|mylar|sachets?|sacks?|wraps?|poly[- ]?mailers?)\b", re.I)),
    ("boxes", re.compile(
        r"\b(box(?:es)?|cartons?|mailers?|packaging|cases?|trays?|sleeves?|tins?|rigid)\b", re.I)),
    ("banners", re.compile(
        r"\b(banners?|flags?|signs?|signage|backdrops?|table covers?|table cloths?|runners?|"
        r"pull[- ]?ups?|roll[- ]?ups?|retractable|a-frames?|canop(?:y|ies)|tents?|stands?|"
        r"displays?|pop[- ]?ups?)\b", re.I)),
    ("print", re.compile(
        r"\b(flyers?|brochures?|postcards?|booklets?|bookmarks?|posters?|envelopes?|calendars?|"
        r"folders?|magnets?|invitations?|greeting cards?|notepads?|letterheads?|menus?|"
        r"tear cards?|tickets?|door hangers?|tags?|printing|print)\b", re.I)),
)

SLOT_SECTIONS = {"Materials": "material", "Finishes": "finish", "Add-ons": "extras"}
FACT_SECTIONS = ("Sizes", "Quote form fields", "MOQ", "Turnaround", "Printing", "Shipping", "Artwork")

# print247's own top-level navigation prefixes, straight from the category URLs in kb_v2.
CATEGORY_FAMILY = {
    "boxes-packaging": "boxes",
    "mylar-bags": "bags",
    "labels-stickers": "labels",
    "signs-banners": "banners",
    "business-cards": "business_cards",
    "print-products": "print",
    "supplements-packaging": "",
}

# Words that join values together instead of belonging to one.
STOP = {
    "aka", "and", "or", "the", "a", "an", "of", "with", "in", "for", "to", "on", "by",
    "as", "is", "are", "be", "we", "our", "it", "this", "that", "any", "all", "no", "not",
    "can", "will", "you", "your", "from", "at", "if", "when", "also", "more", "most",
    "such", "than", "then", "so", "but", "some", "other", "options", "based", "requirements",
    "customizable", "etc", "including", "plus", "using", "made", "type", "style",
}
# A candidate with these words is prose, not a catalogue value.
SENTENCEY = re.compile(
    r"\b(depending|offered|stated|page|product|order|please|note|choose|select|recommend|"
    r"ensure|provide|contact|upload|delivered|production|manufacturing|available)\b", re.I)

SPLIT = re.compile(r"\s*(?:,|;|\band\b|\baka\b|\+|&)\s*", re.I)
PAREN = re.compile(r"\(([^()]*)\)")


def canon(text: str) -> str:
    """Lower-case word form used for matching: hyphens and punctuation collapse to spaces."""
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", text.lower())).strip()


def words(text: str) -> tuple[str, ...]:
    return tuple(canon(text).split())


def page_kind(url: str, sections: dict) -> str:
    """product | deal | category | other, from the site's own URL shape and page structure."""
    if "/category/" in url:
        return "category"
    if "/deals/" in url:
        return "deal"
    if "Quote form fields" in sections:
        return "product"
    return "other"


def style_key(text: str) -> str:
    """A product name in a form that can be compared with a category page's sub-product list."""
    text = canon(re.sub(r"\b(custom|bespoke|printed)\b", " ", text.lower()))
    return re.sub(r"\s+", " ", text).strip()


def site_families(pages: list[dict]) -> dict[str, str]:
    """style name -> family, taken from the `Sub-products linked from the page` lists on the
    site's own category pages. This is print247's navigation, not a keyword guess."""
    found: dict[str, str] = {}
    for page in pages:
        url = page["meta"].get("source", "")
        if "/category/" not in url:
            continue
        slug = url.split("/category/", 1)[1].strip("/")
        family = CATEGORY_FAMILY.get("-".join(slug.split("-")[:2]), "")
        if not family:
            continue
        for bullet in page["sections"].get("Sub-products linked from the page", []):
            name = style_key(clean(bullet))
            if 3 <= len(name) <= 60:
                found.setdefault(name, family)
    return found


def classify(title: str, url: str, styles: dict[str, str]) -> tuple[str, str]:
    """Family plus how it was decided: the site's category list beats a keyword match."""
    family = styles.get(style_key(title))
    if family:
        return family, "site-category"
    haystack = f"{title} {url.rsplit('/', 1)[-1].replace('-', ' ').replace('.php', '')}"
    for candidate, pattern in FAMILY_RULES:
        if pattern.search(haystack):
            return candidate, "keyword"
    return "", "none"


def clean(fragment: str) -> str:
    return re.sub(r"\s+", " ", fragment).strip(" .,;:-/+")


def read_page(path: Path) -> dict:
    raw = path.read_text(encoding="utf-8")
    meta: dict[str, str] = {}
    body = raw
    match = re.match(r"^---\n(.*?)\n---\n?(.*)$", raw, re.S)
    if match:
        for line in match.group(1).splitlines():
            if ":" in line:
                key, value = line.split(":", 1)
                meta[key.strip()] = value.strip()
        body = match.group(2)
    sections: dict[str, list[str]] = defaultdict(list)
    current = None
    for line in body.splitlines():
        if line.startswith("## "):
            current = line[3:].strip().rstrip(":")
            continue
        if current and line.startswith("- "):
            sections[current].append(line[2:].strip())
    return {"path": path, "stem": path.stem, "meta": meta, "sections": dict(sections)}


def seed_lexicon() -> tuple[dict[tuple[str, ...], tuple[str, str]], int]:
    """canonical tokens -> (display, slot), plus how many came from the registry itself."""
    lexicon: dict[tuple[str, ...], tuple[str, str]] = {}

    def add(value: str, slot: str, *aliases: str) -> None:
        key = words(value)
        if key:
            lexicon.setdefault(key, (clean(value), slot))
        for alias in aliases:
            alias_key = words(alias)
            if alias_key:
                lexicon.setdefault(alias_key, (clean(value), slot))

    tables = parse_tables(REGISTRY_MD.read_text(encoding="utf-8"), REGISTRY_MD)
    for row in tables.get("vocabulary", []):
        slot = (row.get("slot") or "").strip()
        if slot in {"", "free_params", "form_selectable", "style_card", "style", "gauge"}:
            continue
        for value in (v.strip() for v in (row.get("values") or "").split(";")):
            if value and value != "-":
                add(value, slot)
    registry_keys = set(lexicon)
    if ACCEPTED_MD.exists():
        for line in ACCEPTED_MD.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            slot, _, rest = line.partition(":")
            forms = [form.strip() for form in rest.split("|") if form.strip()]
            if not forms:
                forms = [slot.strip()]
                slot = "material"
            add(forms[0], slot.strip(), *forms[1:])
    return lexicon, len(registry_keys)


def candidates(bullet: str) -> list[str]:
    """One bullet -> its separate value strings, with parentheticals peeled off."""
    inner = PAREN.findall(bullet)
    text = PAREN.sub(" ", bullet)
    parts = [clean(part) for part in SPLIT.split(text)]
    out = [part for part in parts if part]
    out += [clean(found) for found in inner if clean(found)]
    return out


def match_part(part: str, lexicon: dict) -> tuple[list[str], list[str]]:
    """Whole-word longest match: the curated values found, and the word groups that matched nothing."""
    tokens = list(words(part))
    known: list[str] = []
    unknown: list[str] = []
    buffer: list[str] = []

    def flush() -> None:
        text = clean(" ".join(buffer))
        if text:
            unknown.append(text)
        buffer.clear()

    i = 0
    while i < len(tokens):
        best: tuple[tuple[str, ...], str] | None = None
        plural: tuple[tuple[str, ...], str] | None = None
        for key, (display, _slot) in lexicon.items():
            span = tokens[i:i + len(key)]
            if len(span) != len(key):
                continue
            if span == list(key):
                if best is None or len(key) > len(best[0]):
                    best = (key, display)
            elif (span[:-1] == list(key[:-1]) and span[-1] == key[-1] + "s"
                  and len(key[-1]) > 3):
                # "Euro Holes" / "Child-Resistant Zippers" are the same values as their singulars.
                if plural is None or len(key) > len(plural[0]):
                    plural = (key, display)
        hit = best or plural
        if hit is None:
            buffer.append(tokens[i])
            i += 1
            continue
        flush()
        if hit[1] not in known:
            known.append(hit[1])
        i += len(hit[0])
    flush()
    return known, unknown


def main() -> int:
    lexicon, curated_count = seed_lexicon()
    pages = [read_page(p) for part in ("catalog", "site") for p in sorted((CORPUS / part).rglob("*.md"))]

    err = sys.stderr
    print(f"lexicon: {len(lexicon)} values "
          f"({curated_count} curated from the registry, {len(lexicon) - curated_count} accepted proposals)",
          file=err)

    rows: list[dict] = []
    unmapped: list[tuple[str, str]] = []
    proposals: dict[str, dict] = {}
    per_family = Counter()
    per_basis = Counter()
    facts: dict[str, list[tuple[str, str]]] = defaultdict(list)
    styles = site_families(pages)
    print(f"site category lists: {len(styles)} product names used as family evidence", file=err)

    def propose(slot: str, text: str, path: Path, kind: str) -> None:
        entry = proposals.setdefault(text, {"slot": slot, "kind": kind, "cited": set(), "hits": 0})
        entry["hits"] += 1
        entry["cited"].add(path.relative_to(ROOT).as_posix())

    for page in pages:
        title = page["meta"].get("title", page["stem"])
        url = page["meta"].get("source", "")
        family, basis = classify(title, url, styles)
        kind = page_kind(url, page["sections"])
        if not family:
            unmapped.append((page["stem"], title))
            continue
        per_family[family] += 1
        per_basis[(family, basis, kind)] += 1

        slots: dict[str, list[str]] = defaultdict(list)
        for section, default_slot in SLOT_SECTIONS.items():
            for bullet in page["sections"].get(section, []):
                for part in candidates(bullet):
                    known, unknown = match_part(part, lexicon)
                    for value in known:
                        slot = lexicon[words(value)][1]
                        if value not in slots[slot]:
                            slots[slot].append(value)
                    if not known:
                        if SENTENCEY.search(part) or len(words(part)) > 5:
                            propose(default_slot, part, page["path"], "NOTE")
                        else:
                            propose(default_slot, part, page["path"], "NEW")
                        continue
                    for text in unknown:
                        if len(text.split()) > 5 or SENTENCEY.search(text):
                            propose(default_slot, text, page["path"], "NOTE")
                        else:
                            propose(default_slot, text, page["path"], "PART")

        for section in FACT_SECTIONS:
            for bullet in page["sections"].get(section, []):
                facts[section].append((page["stem"], bullet))

        style = clean(re.sub(r"^(custom|bespoke)\s+", "", title, flags=re.I))
        rows.append({
            "family": family, "style": style, "title": title, "url": url,
            "kind": kind, "basis": basis, "page": page, "slots": dict(slots),
        })

    queues = {kind: {k: v for k, v in proposals.items() if v["kind"] == kind}
              for kind in ("NEW", "PART", "NOTE")}
    print(f"rows: {len(rows)}  per family: {dict(per_family.most_common())}", file=err)
    print("per family page kind / evidence:", file=err)
    for (family, basis, kind), count in sorted(per_basis.items()):
        print(f"    {family:<15} {kind:<9} {basis:<14} {count}", file=err)
    products = [stem for stem, _ in unmapped if stem.startswith("catalog-")]
    print(f"unmapped catalogue pages ({len(products)}): " + ", ".join(products), file=err)
    print(f"non-catalogue pages skipped: {len(unmapped) - len(products)}", file=err)
    used = {value for row in rows for values in row["slots"].values() for value in values}
    print(f"distinct curated values used in rows: {len(used)}", file=err)
    for kind, label in (("NEW", "wholly unknown"), ("PART", "known value plus unknown words"),
                        ("NOTE", "prose, not a value")):
        group = queues[kind]
        print(f"{kind} ({label}): {len(group)} distinct, {sum(v['hits'] for v in group.values())} hits", file=err)
    for slot in ("material", "finish", "extras", "insert"):
        for kind in ("NEW", "PART"):
            group = sorted(((k, v) for k, v in queues[kind].items() if v["slot"] == slot),
                           key=lambda kv: (-kv[1]["hits"], kv[0]))
            if not group:
                continue
            print(f"\n  --- {kind} `{slot}` ({len(group)}) ---", file=err)
            for text, data in group[:60]:
                print(f"    {data['hits']:3}  {text:<34} {sorted(data['cited'])[0]}", file=err)
    for section in FACT_SECTIONS:
        print(f"section '{section}': {len(facts[section])} bullets", file=err)

    print("\n```capability")
    print("# table: rows_v2")
    print("# family|kind|basis|style|material|insert|finish|extras|source|url")
    for row in rows:
        slots = row["slots"]
        cells = [row["family"], row["kind"], row["basis"], row["style"]]
        for slot in ("material", "insert", "finish", "extras"):
            cells.append("; ".join(slots.get(slot, [])) or "-")
        cells += [row["page"]["path"].relative_to(ROOT).as_posix(), row["url"]]
        print("|".join(cells))
    print("```")
    print("\n```capability")
    print("# table: proposals")
    print("# slot|kind|value|hits|sources")
    for text, data in sorted(proposals.items(),
                             key=lambda kv: (kv[1]["kind"], kv[1]["slot"], -kv[1]["hits"], kv[0])):
        srcs = "; ".join(sorted(data["cited"])[:3])
        print(f"{data['slot']}|{data['kind']}|{clean(text)}|{data['hits']}|{srcs}")
    print("```")
    print("\n```capability")
    print("# table: facts_v2")
    print("# section|doc|bullet")
    for section in FACT_SECTIONS:
        for doc, bullet in facts[section]:
            print(f"{section}|{doc}|{clean(bullet)}")
    print("```")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
