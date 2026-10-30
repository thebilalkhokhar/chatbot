"""Capability registry and compliance allow-list: loader, normaliser, primer.

Phase 1 of PLAN_V2. This module is the only reader of ``kb/capabilities/``. It parses the
machine-readable ``capability`` blocks in those markdown files, answers tuple-membership
questions for the Phase 3 guards, and renders the CATALOGUE PRIMER that v2 puts in front of
the model on every turn. Nothing here calls a model and nothing here changes v1 behaviour.

The registry at ``kb/capabilities/capability-registry.md`` is generated from the ``kb_v2/``
corpus by ``chatbot/tools/build_registry_v2.py``; every citation in it is a ``kb_v2/`` path
resolved against the project root, so the source audit reads that corpus, not ``kb/``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from .kb import tokenize
from .state import FAMILIES

REGISTRY_PATH = Path("capabilities") / "capability-registry.md"
ALLOWLIST_PATH = Path("capabilities") / "compliance-allowlist.md"
PRIMER_NAME = "catalogue_primer.txt"
PROJECT_ROOT = Path(__file__).resolve().parents[2]
CORPUS_DIR_NAME = "kb_v2"

FENCE = "```capability"
EMPTY = "-"
# PLAN_V2 §4.9 estimated 900-1500 before the registry existed. The kb_v2 registry carries 147 page rows
# and the site's whole option vocabulary, so the primer measures 2856 tokens by this estimator: ~1880 in
# the six family vocabulary blocks (styles alone are 146 names), 825 in the 26 exclusion sentences, and
# the rest in the header, the gauge warning and the size/colour rules. The bound is the measurement plus
# headroom for sign-off edits, not a target: cutting attested values to fit a smaller number would
# remove exactly the nouns the primer exists to carry. See PLAN_V2 §4.9.
PRIMER_TOKEN_BUDGET = 2900
CHARS_PER_TOKEN = 4

STATES = ("attested", "unknown_capability", "excluded")
# The capability tuple. `colour` and `fold` are vocabulary the bot may discuss but they are not
# tuple slots: a colour is an appearance the site prints under Materials, and a fold is a print
# build detail, so neither may change an attested/unknown classification.
SLOTS = ("style", "material", "insert", "finish", "extras")
VOCABULARY_SLOTS = ("style", "material", "colour", "finish", "extras", "insert", "fold")
GAUGE_BASES = ("page", "faq", "knowledge")
NOT_ATTESTED_CLASSES = ("probe", "v1-absent")

# A slot the site files under "Finishes" but the quote form treats as an extra.
FINISH_VALUES_THAT_ARE_EXTRAS = frozenset(
    {
        "window",
        "clear window",
        "zipper",
        "resealable zipper",
        "easy-open zipper",
        "child-resistant zipper",
        "tear notch",
        "hang hole",
        "euro hole",
        "degassing valve",
    }
)

# "rigid" is a box material on the site's pages, never a product name.
MATERIAL_WORDS = {"rigid": "rigid cardboard", "rigid box": "rigid cardboard"}

# A pack count answers neither size nor quantity.
PACK_COUNT = re.compile(
    r"^\d+\s*(?:-|\s)?\s*(?:count|ct|pack|pcs|pieces|capsules per bag|bags per case)\.?$",
    re.IGNORECASE,
)
SIZE_WITHOUT_UNIT = re.compile(
    r"^\d+(?:\.\d+)?\s*[x×]\s*\d+(?:\.\d+)?(?:\s*[x×]\s*\d+(?:\.\d+)?)?(?:\s*\+\s*\d+(?:\.\d+)?)?$"
)


def fold(text: str) -> str:
    """The registry's comparison form for a value: case, hyphens and separators folded away.

    ``build_registry_v2.py`` folds site wording with the same shape when it writes the `aliases`
    table, so a query and the table meet in the middle instead of two normalisers drifting apart.
    """
    return re.sub(r"\s+", " ", re.sub(r"[-/_&,.:;+]", " ", (text or "").lower())).strip()


class CapabilityError(ValueError):
    """A capability file is malformed. Fail loudly instead of guessing."""


def estimate_tokens(text: str) -> int:
    """Conservative token estimate: this project ships no tokenizer dependency."""
    return max(len(text.split()), -(-len(text) // CHARS_PER_TOKEN))


def _variants(token: str) -> set[str]:
    """The forms of a word that count as the same word: plural, and a 4-char prefix.

    The registry normalises site wording ("QR codes" becomes "QR code", "generally" becomes
    "general"), so an exact token match would flag every normalisation as an invention.
    """
    text = token.lower()
    forms = {text, text[:4], f"{text}s", f"{text}es"}
    if text.endswith("s"):
        forms.add(text[:-1])
    if text.endswith("es"):
        forms.add(text[:-2])
    return forms


def _shares_a_form(row_values: tuple[str, ...], candidate_values: tuple[str, ...]) -> bool:
    """Whether any candidate value is the same registry value as any row value, forms included."""
    known: set[str] = set()
    for value in row_values:
        known |= value_forms(value)
    return any(value_forms(value) & known for value in candidate_values)


def value_forms(text: str) -> set[str]:
    """The comparison forms of one registry value: folded, and folded with each token de-pluralised.

    The kb_v2 registry takes its style names from page titles, which are plural ("Mailer Boxes",
    "Pull up Banners"), while a visitor says the singular. Without this, every singular ask the site
    plainly serves would read as an invented noun.
    """
    base = fold(text)
    forms = {base}
    singular: list[str] = []
    for token in base.split():
        if len(token) > 4 and token.endswith("es") and token[:-2] != "":
            singular.append(token[:-2])
        elif len(token) > 3 and token.endswith("s"):
            singular.append(token[:-1])
        else:
            singular.append(token)
    forms.add(" ".join(singular))
    return forms


def _as_tuple(value) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        text = value.strip()
        return () if not text or text == EMPTY else (text,)
    return tuple(str(item).strip() for item in value if str(item).strip())


def _cell(row: dict[str, str], key: str) -> str:
    value = (row.get(key) or "").strip()
    return "" if value == EMPTY else value


def _list_cell(row: dict[str, str], key: str) -> tuple[str, ...]:
    cell = _cell(row, key)
    if not cell:
        return ()
    parts = [part.strip() for part in cell.split(";")]
    return tuple(part for part in parts if part and part != EMPTY)


CITATION = re.compile(r"\((?:kb|chatbot)/[^)]*\)")


def _brief(note: str) -> str:
    """Drop source paths from a note before it goes into the prompt; the file keeps them."""
    return CITATION.sub("", note).replace("  ", " ").strip(" ;,")


def parse_tables(text: str, path: Path) -> dict[str, list[dict[str, str]]]:
    """Read every ```capability block into {table name: [row dicts]}.

    A block is ``# table: name``, a ``# col|col`` header, then one record per line. A record
    with the wrong cell count raises: a silently mis-parsed registry is worse than a crash.
    """
    tables: dict[str, list[dict[str, str]]] = {}
    lines = text.splitlines()
    index = 0
    while index < len(lines):
        if not lines[index].strip().startswith(FENCE):
            index += 1
            continue
        index += 1
        name: str | None = None
        columns: list[str] | None = None
        rows: list[dict[str, str]] = []
        closed = False
        while index < len(lines):
            stripped = lines[index].strip()
            index += 1
            if stripped.startswith("```"):
                closed = True
                break
            if not stripped:
                continue
            if stripped.startswith("#"):
                header = stripped.lstrip("#").strip()
                if header.startswith("table:"):
                    name = header.split(":", 1)[1].strip()
                    columns = None
                elif name and columns is None:
                    columns = [cell.strip() for cell in header.split("|") if cell.strip()]
                continue
            if name is None or columns is None:
                raise CapabilityError(
                    f"{path}: record before a '# table:' line and column header: {stripped[:70]!r}"
                )
            cells = [cell.strip() for cell in stripped.split("|")]
            if len(cells) != len(columns):
                raise CapabilityError(
                    f"{path}: table {name!r} declares {len(columns)} columns "
                    f"({', '.join(columns)}) but this record has {len(cells)}: {stripped[:70]!r}"
                )
            rows.append(dict(zip(columns, cells)))
        if not closed:
            raise CapabilityError(f"{path}: unterminated ```capability block")
        if name is None:
            raise CapabilityError(f"{path}: a ```capability block has no '# table:' line")
        tables.setdefault(name, []).extend(rows)
    return tables


@dataclass(frozen=True)
class Offering:
    """One ``supported`` row: a site-attested combination we may discuss."""

    family: str
    styles: tuple[str, ...] = ()
    materials: tuple[str, ...] = ()
    inserts: tuple[str, ...] = ()
    finishes: tuple[str, ...] = ()
    extras: tuple[str, ...] = ()
    gauges: tuple[str, ...] = ()
    scope: str = ""
    source: str = ""
    approved: str = ""
    note: str = ""

    @property
    def signed(self) -> bool:
        return bool(self.approved) and self.approved.strip().lower() != "pending"

    def covers(self, candidate: "Candidate") -> bool:
        """True when every slot the candidate names is inside this row's values.

        An empty cell in the row means the row does not constrain that slot. Matching goes through
        `value_forms`, because the row cells are page titles and the candidate is customer wording.
        """
        pairs = (
            (self.styles, candidate.style),
            (self.materials, candidate.material),
            (self.inserts, candidate.insert),
            (self.finishes, candidate.finish),
            (self.extras, candidate.extras),
        )
        for row_values, candidate_values in pairs:
            if not row_values or not candidate_values:
                continue
            known: set[str] = set()
            for value in row_values:
                known |= value_forms(value)
            if any(not value_forms(value) & known for value in candidate_values):
                return False
        return True


@dataclass(frozen=True)
class Exclusion:
    """One ``excluded`` row. ``pair`` rows are mechanical; ``rule`` rows are prose for the primer."""

    family: str
    kind: str
    styles: tuple[str, ...] = ()
    materials: tuple[str, ...] = ()
    inserts: tuple[str, ...] = ()
    finishes: tuple[str, ...] = ()
    extras: tuple[str, ...] = ()
    reason: str = ""
    source: str = ""
    approved: str = ""

    @property
    def mechanical(self) -> bool:
        return self.kind == "pair"

    def matches(self, candidate: "Candidate") -> bool:
        if not self.mechanical or candidate.family != self.family:
            return False
        constrained = [
            (self.styles, candidate.style),
            (self.materials, candidate.material),
            (self.inserts, candidate.insert),
            (self.finishes, candidate.finish),
            (self.extras, candidate.extras),
        ]
        constrained = [(row, cand) for row, cand in constrained if row]
        if not constrained:
            return False
        return all(_shares_a_form(row, cand) for row, cand in constrained)


@dataclass(frozen=True)
class ProductionQuestion:
    family: str
    question: str
    asked: str
    source: str = ""


@dataclass(frozen=True)
class NotAttested:
    family: str
    value: str
    note: str
    klass: str = "probe"


@dataclass(frozen=True)
class Gauge:
    """One ``gauges`` row: a thickness or weight figure and how strongly it is sourced."""

    family: str
    material: str
    gauge: str
    basis: str
    source: str
    note: str


@dataclass(frozen=True)
class UnmappedPage:
    """A catalogue page the extractor could not place in a family - an audit item, not a product."""

    page: str
    title: str
    kind: str


@dataclass(frozen=True)
class SizeRow:
    family: str
    values: tuple[str, ...]
    note: str
    source: str


@dataclass(frozen=True)
class Claim:
    """One ``allowed`` row of the compliance allow-list."""

    topic: str
    family: str
    say: str
    source: str
    never_say: str


@dataclass(frozen=True)
class Ban:
    """One ``never`` row: a phrase that is banned even though our own material uses it."""

    claim: str
    family: str
    why: str


@dataclass(frozen=True)
class Candidate:
    """A configuration the model proposes, in registry vocabulary."""

    family: str
    style: tuple[str, ...] = ()
    material: tuple[str, ...] = ()
    insert: tuple[str, ...] = ()
    finish: tuple[str, ...] = ()
    extras: tuple[str, ...] = ()

    @classmethod
    def of(cls, family, style=None, material=None, insert=None, finish=None, extras=None) -> "Candidate":
        return cls(
            family=str(family or "unknown"),
            style=_as_tuple(style),
            material=_as_tuple(material),
            insert=_as_tuple(insert),
            finish=_as_tuple(finish),
            extras=_as_tuple(extras),
        )

    def named_values(self) -> tuple[str, ...]:
        return self.style + self.material + self.insert + self.finish + self.extras


@dataclass(frozen=True)
class Match:
    """The classification of one candidate: the state, and why."""

    state: str
    reason: str = ""
    offerings: tuple[Offering, ...] = ()
    exclusion: Exclusion | None = None

    @property
    def may_assert(self) -> bool:
        return self.state == "attested"


@dataclass(frozen=True)
class Normalised:
    """Result of mapping one customer word onto a registry slot."""

    family: str
    slot: str
    value: str
    note: str = ""
    answers_nothing: bool = False


@dataclass
class Registry:
    vocabulary: dict[str, dict[str, tuple[str, ...]]] = field(default_factory=dict)
    offerings: tuple[Offering, ...] = ()
    exclusions: tuple[Exclusion, ...] = ()
    production_questions: tuple[ProductionQuestion, ...] = ()
    not_attested: tuple[NotAttested, ...] = ()
    sizes: tuple[SizeRow, ...] = ()
    gauges: tuple[Gauge, ...] = ()
    unmapped: tuple[UnmappedPage, ...] = ()
    aliases: dict[str, str] = field(default_factory=dict)
    claims: tuple[Claim, ...] = ()
    bans: tuple[Ban, ...] = ()
    registry_path: Path | None = None
    allowlist_path: Path | None = None

    # ---- loading ----

    @classmethod
    def load(cls, kb_dir: Path) -> "Registry":
        registry_path = kb_dir / REGISTRY_PATH
        allowlist_path = kb_dir / ALLOWLIST_PATH
        for path in (registry_path, allowlist_path):
            if not path.exists():
                raise CapabilityError(f"missing capability file: {path}")

        tables = parse_tables(registry_path.read_text(encoding="utf-8"), registry_path)
        allow_tables = parse_tables(allowlist_path.read_text(encoding="utf-8"), allowlist_path)

        vocabulary: dict[str, dict[str, tuple[str, ...]]] = {}
        for row in tables.get("vocabulary", []):
            family = _cell(row, "family")
            slot = _cell(row, "slot")
            if not family or not slot:
                raise CapabilityError(f"{registry_path}: vocabulary row needs family and slot: {row}")
            if slot not in VOCABULARY_SLOTS:
                raise CapabilityError(
                    f"{registry_path}: vocabulary slot {slot!r} is not one the loader reads "
                    f"({', '.join(VOCABULARY_SLOTS)}) - an unread slot means a value silently disappears"
                )
            vocabulary.setdefault(family, {})[slot] = _list_cell(row, "values")

        offerings = tuple(
            Offering(
                family=_cell(row, "family"),
                styles=_list_cell(row, "style"),
                materials=_list_cell(row, "material"),
                inserts=_list_cell(row, "insert"),
                finishes=_list_cell(row, "finish"),
                extras=_list_cell(row, "extras"),
                gauges=_list_cell(row, "gauge"),
                scope=_cell(row, "scope"),
                source=_cell(row, "source"),
                approved=_cell(row, "approved"),
                note=_cell(row, "note"),
            )
            for row in tables.get("supported", [])
        )
        exclusions = tuple(
            Exclusion(
                family=_cell(row, "family"),
                kind=_cell(row, "kind"),
                styles=_list_cell(row, "style"),
                materials=_list_cell(row, "material"),
                inserts=_list_cell(row, "insert"),
                finishes=_list_cell(row, "finish"),
                extras=_list_cell(row, "extras"),
                reason=_cell(row, "reason"),
                source=_cell(row, "source"),
                approved=_cell(row, "approved"),
            )
            for row in tables.get("excluded", [])
        )
        questions = tuple(
            ProductionQuestion(
                family=_cell(row, "family"),
                question=_cell(row, "question"),
                asked=_cell(row, "asked"),
                source=_cell(row, "source"),
            )
            for row in tables.get("needs_production", [])
        )
        absent = tuple(
            NotAttested(
                family=_cell(row, "family"),
                value=_cell(row, "value"),
                note=_cell(row, "note"),
                klass=_cell(row, "class") or "probe",
            )
            for row in tables.get("not_attested", [])
        )
        sizes = tuple(
            SizeRow(
                family=_cell(row, "family"),
                values=_list_cell(row, "values"),
                note=_cell(row, "note"),
                source=_cell(row, "source"),
            )
            for row in tables.get("sizes", [])
        )
        gauges = tuple(
            Gauge(
                family=_cell(row, "family"),
                material=_cell(row, "material"),
                gauge=_cell(row, "gauge"),
                basis=_cell(row, "basis"),
                source=_cell(row, "source"),
                note=_cell(row, "note"),
            )
            for row in tables.get("gauges", [])
        )
        unmapped = tuple(
            UnmappedPage(page=_cell(row, "page"), title=_cell(row, "title"), kind=_cell(row, "kind"))
            for row in tables.get("unmapped", [])
        )
        aliases = {
            fold(_cell(row, "variant")): _cell(row, "canonical")
            for row in tables.get("aliases", [])
            if _cell(row, "variant") and _cell(row, "canonical")
        }
        claims = tuple(
            Claim(
                topic=_cell(row, "topic"),
                family=_cell(row, "family"),
                say=_cell(row, "say"),
                source=_cell(row, "source"),
                never_say=_cell(row, "never_say"),
            )
            for row in allow_tables.get("allowed", [])
        )
        bans = tuple(
            Ban(claim=_cell(row, "claim"), family=_cell(row, "family"), why=_cell(row, "why"))
            for row in allow_tables.get("never", [])
        )

        return cls(
            vocabulary=vocabulary,
            offerings=offerings,
            exclusions=exclusions,
            production_questions=questions,
            not_attested=absent,
            sizes=sizes,
            gauges=gauges,
            unmapped=unmapped,
            aliases=aliases,
            claims=claims,
            bans=bans,
            registry_path=registry_path,
            allowlist_path=allowlist_path,
        )

    # ---- queries ----

    @property
    def families(self) -> tuple[str, ...]:
        """The registry's family key list, in the runtime's own order."""
        return tuple(name for name in FAMILIES if name in self.vocabulary)

    def slots(self, family: str) -> tuple[str, ...]:
        return tuple(self.vocabulary.get(family, {}))

    def values(self, family: str, slot: str) -> tuple[str, ...]:
        return self.vocabulary.get(family, {}).get(slot, ())

    def known_values(self, family: str) -> frozenset[str]:
        found: set[str] = set()
        for values in self.vocabulary.get(family, {}).values():
            for value in values:
                found |= value_forms(value)
        return frozenset(found)

    def unknown_values(self, candidate: Candidate) -> dict[str, tuple[str, ...]]:
        """Values the candidate names that this family's vocabulary does not contain (probe C1)."""
        known = self.known_values(candidate.family)
        out: dict[str, tuple[str, ...]] = {}
        for slot in SLOTS:
            values = getattr(candidate, slot)
            unknown = tuple(value for value in values if not value_forms(value) & known)
            if unknown:
                out[slot] = unknown
        return out

    def is_not_attested(self, value: str) -> NotAttested | None:
        needle = value_forms(value)
        for row in self.not_attested:
            if value_forms(row.value) & needle:
                return row
        return None

    def classify(self, candidate: Candidate) -> Match:
        """Default-deny tuple membership: excluded, else attested-if-signed, else unknown."""
        for exclusion in self.exclusions:
            if exclusion.matches(candidate):
                return Match(
                    state="excluded",
                    reason=exclusion.reason,
                    exclusion=exclusion,
                )
        covering = tuple(row for row in self.offerings if row.family == candidate.family and row.covers(candidate))
        if not covering:
            return Match(
                state="unknown_capability",
                reason="no attested row covers this combination",
            )
        signed = tuple(row for row in covering if row.signed)
        if signed:
            return Match(state="attested", reason="signed row", offerings=signed)
        return Match(
            state="unknown_capability",
            reason="site-attested but unsigned (approved: pending) — discuss, do not assert",
            offerings=covering,
        )

    # ---- normalisation ----

    def canonical_value(self, value: str) -> str:
        """The registry's canonical form of a written value ('Softouch Lamination' -> 'soft touch lamination')."""
        return self.aliases.get(fold(value), value.strip())

    def normalise(self, family: str, slot: str, value: str) -> Normalised:
        """Map one customer word onto a registry slot before the tuple key is built."""
        text = (value or "").strip()
        if not text:
            return Normalised(family, slot, "")
        lowered = text.lower()
        canonical = self.canonical_value(text)

        if PACK_COUNT.match(lowered):
            return Normalised(family, slot, "", note="pack count is neither size nor quantity", answers_nothing=True)
        if slot == "size" and SIZE_WITHOUT_UNIT.match(lowered):
            return Normalised(family, slot, "", note="no unit — ask for it, never assume inches or mm", answers_nothing=True)

        if lowered in MATERIAL_WORDS:
            return Normalised(
                family or "boxes",
                "material",
                self.canonical_value(MATERIAL_WORDS[lowered]),
                note="'rigid' names a box stock on these pages, never a product",
            )
        # A sticker is a label and a decal is signage: the site sells each under its own category, so
        # the family is settled here and the style stays whatever the visitor or page named.
        if slot == "style" and lowered in {"sticker", "stickers"}:
            return Normalised("labels", "style", canonical, note="a sticker is a labels value, not a banners one")
        if slot == "style" and lowered in {"decal", "decals"}:
            return Normalised("banners", "style", canonical, note="a decal is a banners value, not a labels one")
        if slot == "material" and canonical.lower() in {"matte", "gloss", "soft touch"}:
            return Normalised(
                family, "finish", canonical, note=f"'{canonical}' is a finish here; it never answers material"
            )
        if slot == "finish" and fold(canonical) in {fold(v) for v in FINISH_VALUES_THAT_ARE_EXTRAS}:
            return Normalised(family, "extras", canonical, note="the page files this under finishes; the quote slot is extras")
        return Normalised(family, slot, canonical)

    def gauge_for(self, figure: str) -> Gauge | None:
        """The registry row for a gauge figure, so the answer carries its basis and material."""
        needle = fold(figure)
        for row in self.gauges:
            if needle and needle in fold(row.gauge):
                return row
        return None

    # ---- primer ----

    def render_primer(self) -> str:
        """The CATALOGUE PRIMER: deterministic text, rendered from the registry, never hand-authored."""
        lines: list[str] = [
            "CATALOGUE PRIMER - what Print247 offers",
            "Rendered from kb/capabilities by chatbot/bot/capability.py; do not edit by hand.",
            "This is the whole option set. A style, material, finish, extra, gauge or size not listed",
            "here is not ours: describe the need, offer the nearest listed option, let the team confirm.",
            "Never invent a value. Everything below is site-attested; a specific build is still confirmed",
            "by the team with the quote.",
            "Product names below are the site's own page titles.",
        ]
        for family in self.families:
            lines.append("")
            lines.append(family.upper().replace("_", " "))
            slots = self.vocabulary[family]
            for slot in VOCABULARY_SLOTS:
                values = slots.get(slot)
                if values:
                    lines.append(f"  {slot}: {', '.join(values)}")
            for row in (item for item in self.sizes if item.family == family):
                if row.values:
                    lines.append(f"  sizes we list: {', '.join(row.values)}")
                else:
                    lines.append(f"  sizes: {_brief(row.note)}")
            stated = [g for g in self.gauges if g.family == family and g.basis == "page"]
            if stated:
                lines.append("  gauge stated on a product page: " + "; ".join(f"{g.material}: {g.gauge}" for g in stated))

        weaker = [g for g in self.gauges if g.basis in {"faq", "knowledge"}]
        lines.append("")
        lines.append("GAUGES NOT FOR THE REPLY")
        lines.append(
            f"  {len(weaker)} figures come from a FAQ answer or a hub article, not a product spec "
            "(micron, mil, gsm, oz, lb, pt and mm measure different things per family). "
            "Say the team confirms the gauge with the quote; never quote one of these numbers."
        )

        lines.append("")
        lines.append("DO NOT OFFER")
        for exclusion in self.exclusions:
            if exclusion.mechanical:
                parts = [
                    value
                    for group in (
                        exclusion.styles,
                        exclusion.materials,
                        exclusion.inserts,
                        exclusion.finishes,
                        exclusion.extras,
                    )
                    for value in group
                ]
                lines.append(f"  {exclusion.family}: {' + '.join(parts)} - {_brief(exclusion.reason)}")
            else:
                lines.append(f"  {exclusion.family}: {_brief(exclusion.reason)}")
        probes = [row for row in self.not_attested if row.klass == "probe"]
        lines.append(f"  never ours, anywhere: {', '.join(row.value for row in probes)}")

        lines.append("")
        lines.append("COLOUR is not a capability: white, silver, clear, frosted and iridescent name the")
        lines.append("look of a stock, so a colour never decides whether we can make something.")
        lines.append("SIZES: only a size listed above, or one the customer typed, may appear in a reply.")
        lines.append("Never calculate or imply a dimension, and never present a listed size as a")
        lines.append("guaranteed fit - the packaging team confirms the final size.")
        lines.append("COMPLIANCE: only the signed sentences in the compliance allow-list may be")
        lines.append("asserted; otherwise say specs are confirmed by the team with the quote and keep")
        lines.append("helping. Explain why an option suits the product; never name a property we have")
        lines.append("not signed.")
        return "\n".join(lines) + "\n"

    def write_primer(self, data_dir: Path) -> Path:
        data_dir.mkdir(parents=True, exist_ok=True)
        path = data_dir / PRIMER_NAME
        path.write_text(self.render_primer(), encoding="utf-8")
        return path

    # ---- validation ----

    def validate(self, corpus_dir: Path | None = None) -> tuple[list[str], list[str]]:
        """Structural errors and source-audit warnings for `cli capability`.

        `corpus_dir` is the read-only `kb_v2/` the registry cites; the audit walks it to prove no
        vocabulary value in this file was invented. It defaults to the project's own corpus.
        """
        errors: list[str] = []
        warnings: list[str] = []
        if corpus_dir is None:
            corpus_dir = PROJECT_ROOT / CORPUS_DIR_NAME

        expected = tuple(name for name in FAMILIES if name != "unknown")
        if self.families != expected:
            errors.append(
                f"registry families {list(self.families)} != runtime families {list(expected)}"
            )

        for family in self.families:
            slots = self.vocabulary[family]
            if not slots.get("style"):
                errors.append(f"{family}: vocabulary has no style values")

        for index, row in enumerate(self.offerings, start=1):
            label = f"supported row {index} ({row.family}/{', '.join(row.styles) or '-'})"
            if not row.source:
                errors.append(f"{label}: no source - a row without a source is not a row")
            if not row.approved:
                errors.append(f"{label}: no approved value (use 'pending' until it is signed)")
            if row.scope not in {"page", "family"}:
                errors.append(f"{label}: scope must be page or family, got {row.scope!r}")
            for slot, values in (
                ("style", row.styles),
                ("material", row.materials),
                ("insert", row.inserts),
                ("finish", row.finishes),
                ("extras", row.extras),
            ):
                orphans = self._orphans(row.family, slot, values)
                if orphans:
                    errors.append(f"{label}: orphan {slot} values not in vocabulary: {', '.join(orphans)}")
            errors.extend(self._citation_misses(label, row.source))

        for index, row in enumerate(self.exclusions, start=1):
            label = f"excluded row {index} ({row.family})"
            if not row.reason:
                errors.append(f"{label}: no reason - a refusal must be explainable")
            if row.kind not in {"pair", "rule"}:
                errors.append(f"{label}: kind must be pair or rule, got {row.kind!r}")
            if not row.source:
                errors.append(f"{label}: no source")
            errors.extend(self._citation_misses(label, row.source))
            if row.kind == "pair":
                constrained = [
                    group
                    for group in (row.styles, row.materials, row.inserts, row.finishes, row.extras)
                    if group
                ]
                if len(constrained) < 2:
                    errors.append(f"{label}: a pair row must constrain at least two slots")
                for slot, values in (
                    ("style", row.styles),
                    ("material", row.materials),
                    ("insert", row.inserts),
                    ("finish", row.finishes),
                    ("extras", row.extras),
                ):
                    orphans = self._orphans(row.family, slot, values)
                    if orphans:
                        errors.append(f"{label}: orphan {slot} values not in vocabulary: {', '.join(orphans)}")

        for index, row in enumerate(self.production_questions, start=1):
            if not row.question or not row.asked:
                errors.append(f"needs_production row {index}: needs a question and who it is asked of")
            if not row.source:
                errors.append(f"needs_production row {index}: a question needs the page that raised it")
            errors.extend(self._citation_misses(f"needs_production row {index}", row.source))

        for index, row in enumerate(self.gauges, start=1):
            label = f"gauges row {index} ({row.family})"
            if row.gauge and row.gauge != EMPTY:
                if row.basis not in GAUGE_BASES:
                    errors.append(f"{label}: basis must be one of {', '.join(GAUGE_BASES)}, got {row.basis!r}")
                if not row.source:
                    errors.append(f"{label}: a figure without a source is not a figure")
                errors.extend(self._citation_misses(label, row.source))
            elif not row.note:
                errors.append(f"{label}: a row with no figure must say why in the note")

        for index, row in enumerate(self.not_attested, start=1):
            if row.klass not in NOT_ATTESTED_CLASSES:
                errors.append(f"not_attested row {index}: class must be probe or v1-absent, got {row.klass!r}")
            if row.klass == "probe" and value_forms(row.value) & self.known_values(row.family):
                errors.append(
                    f"not_attested row {index} ({row.value}): a probe the vocabulary also attests is not a probe"
                )

        for index, row in enumerate(self.claims, start=1):
            label = f"allowed claim {index} ({row.topic})"
            if not row.say or not row.source or not row.never_say:
                errors.append(f"{label}: needs say, source and never_say")
        for index, row in enumerate(self.bans, start=1):
            if not row.claim or not row.why:
                errors.append(f"never row {index}: needs a claim and a why")

        for row in self.sizes:
            if row.values and not row.source:
                errors.append(f"sizes row ({row.family}): listed sizes need a source")
            if row.values:
                errors.extend(self._citation_misses(f"sizes row ({row.family})", row.source))

        warnings.extend(self._audit_vocabulary_sources(corpus_dir))

        return errors, warnings

    @staticmethod
    def _citation_misses(label: str, citation: str) -> list[str]:
        """Every `kb_v2/...` path a cell cites must exist - a dead citation is a invented source."""
        missing: list[str] = []
        for path in re.findall(r"kb_v2/[^\s;|]+\.md", citation or ""):
            if not (PROJECT_ROOT / path).exists():
                missing.append(f"{label}: cited file does not exist: {path}")
        return missing

    def _orphans(self, family: str, slot: str, values: tuple[str, ...]) -> tuple[str, ...]:
        """A value a row uses that the family's vocabulary for that slot does not define."""
        allowed: set[str] = set()
        for known in self.values(family, slot):
            allowed |= value_forms(known)
        return tuple(value for value in values if not value_forms(value) & allowed)

    def _audit_vocabulary_sources(self, corpus_dir: Path) -> list[str]:
        """Warn about a vocabulary value whose words appear in no file in the corpus it cites.

        Token-subset, not exact-phrase: the registry folds site wording ("Foil Pouch" becomes
        "foil pouch", "Greyboard" becomes "grayboard"), so an exact match would flag every fold as an
        invention. A value is unsourced only when one of its words appears nowhere.
        """
        if not corpus_dir.exists():
            return [f"source audit skipped: corpus directory {corpus_dir} is missing"]

        file_tokens: list[tuple[Path, set[str]]] = []
        for path in sorted(corpus_dir.rglob("*.md")):
            if path.name.lower() == "readme.md":
                continue
            text = path.read_text(encoding="utf-8").lower()
            tokens = set(tokenize(text))
            file_tokens.append((path, tokens | {token[:4] for token in tokens}))

        misses: list[str] = []
        for family in self.families:
            for slot, values in self.vocabulary[family].items():
                for value in values:
                    words = tokenize(value)
                    if not words:
                        continue
                    sourced = any(
                        all(_variants(word) & tokens for word in words) for _, tokens in file_tokens
                    )
                    if not sourced:
                        misses.append(
                            f"{family}.{slot}: {value!r} has no file in the cited corpus containing its words"
                        )
        return misses
