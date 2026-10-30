"""Phase 4 grounding probe.

Stage A is the 12 smoke scenarios. Stage B is the S1/S2/S3 grid, capped at 60.
Scoring is per class, over the denominators in PLAN_V2 §4.7. Nothing here relaxes a
guard. The replay spend lock is not touched: this module never calls run_replay.

Paid calls go through LLMClient, which enforces BOT_MAX_LLM_CALLS. The probe also
stops itself at a dollar cap. A Tier B violation (C3) ends the run before the next
stage starts.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, replace
from pathlib import Path

from . import canon, guards
from .capability import Candidate, Registry, fold, value_forms
from .composer import live_turn, select_examples
from .config import Config
from .llm import LLMError
from .orchestrator import Orchestrator
from .state import FAMILY_PRODUCT, STATUS_VISITOR, ConversationState, asks_if_bot

DOLLAR_CAP = 1.90
CALLS_PER_ATTEMPT = 2  # the model reply, plus one rewrite when guards block

C3_CODES = frozenset({
    "price_given",
    "time_promise",
    "discount_promise",
    "wrong_minimum",
    "minimum_needs_condition",
    "tier_b_hallucination",
    "canon_conflict",
    "unsanctioned_dimension",
    "human_claim",
})

# Stage A. One realistic recommendation ask per hard case in §4.7.
STAGE_A = (
    ("candle", "boxes", "I need packaging for a candle in a glass jar. What should I use?", True),
    ("apparel", "boxes", "I sell folded t-shirts. What packaging do you recommend?", False),
    ("cookies", "boxes", "I need packaging for cookies. What would you suggest?", True),
    ("coffee", "bags", "I need bags for coffee beans. What should I use?", True),
    ("cosmetics", "boxes", "I need a box for a cosmetic jar. What do you recommend?", True),
    ("hot_sauce", "bags", "I bottle hot sauce. What pouch should I use?", True),
    ("jerky", "bags", "I need packaging for beef jerky. What should I use?", True),
    ("soap", "boxes", "I make bar soap. What box would you recommend?", True),
    ("subscription", "boxes", "I need a subscription box for a monthly gift. What should I use?", False),
    ("pet_treats", "bags", "I need pouches for pet treats. What do you recommend?", True),
    ("wine_labels", "labels", "I need labels for wine bottles. What should I use?", True),
    ("electronics", "boxes", "I ship small electronics. What box do you recommend?", False),
)

# Section 10 categories. server/data/chats.json is not in this workspace, so this is
# the category grid the plan names, four or three lines each, not a production sample.
SCORING_SET = (
    ("bare-1", "boxes", "I need boxes."),
    ("bare-2", "bags", "I need pouches."),
    ("bare-3", "labels", "I need labels."),
    ("bare-4", "banners", "I need a banner."),
    ("contents-1", "boxes", "I need boxes for shipping mugs."),
    ("contents-2", "bags", "I need pouches for ground coffee."),
    ("contents-3", "boxes", "I need boxes for a glass candle jar."),
    ("contents-4", "labels", "I need labels for hot sauce bottles."),
    ("size-1", "boxes", "I need boxes but I don't know the size."),
    ("size-2", "bags", "I need coffee bags and I have no idea what size."),
    ("size-3", "boxes", "Not sure of the dimensions yet. I need a mailer box."),
    ("size-4", "banners", "I need a pull up banner and I don't know the size."),
    ("identity-1", "boxes", "Are you a real person or an AI?"),
    ("identity-2", "bags", "You said you are Ethan. Are you a bot?"),
    ("identity-3", "boxes", "Am I talking to a human?"),
    ("price-1", "boxes", "How much is a mailer box?"),
    ("price-2", "bags", "What's the price for 1000 coffee bags?"),
    ("price-3", "labels", "Can you quote me a price today?"),
    ("price-4", "boxes", "That price is too high. Can you do cheaper?"),
    ("moq-1", "boxes", "Your minimum is too high. I only need 100."),
    ("moq-2", "bags", "I just need 50 pouches. Can you do that?"),
    ("moq-3", "boxes", "500 is fine if the minimum is lower than 1000."),
    ("moq-4", "banners", "Is there a minimum on banners?"),
    ("address-1", "boxes", "What is your address?"),
    ("address-2", "bags", "Where are you located?"),
    ("address-3", "boxes", "Can I visit the facility?"),
    ("bye-1", "boxes", "Thanks, that's all."),
    ("bye-2", "bags", "Goodbye."),
    ("bye-3", "labels", "Ok thanks, bye."),
    ("bye-4", "boxes", "Nothing else, thank you."),
)


@dataclass
class ProbeCase:
    id: str
    stage: str
    stratum: str
    kind: str
    family: str
    visitor: str
    expects: str
    safety: bool = False
    invented_value: str = ""
    c2_denominator: bool = False
    c4_denominator: bool = False
    c5_denominator: bool = False
    site_row: bool = False
    note: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "stage": self.stage,
            "stratum": self.stratum,
            "kind": self.kind,
            "family": self.family,
            "visitor": self.visitor,
            "expects": self.expects,
            "safety": self.safety,
            "c2_denominator": self.c2_denominator,
            "c4_denominator": self.c4_denominator,
            "c5_denominator": self.c5_denominator,
            "site_row": self.site_row,
            "note": self.note,
        }


def stage_a_cases() -> list[ProbeCase]:
    cases = []
    for name, family, visitor, safety in STAGE_A:
        cases.append(ProbeCase(
            id=f"A-{name}",
            stage="A",
            stratum="baseline",
            kind="recommendation",
            family=family,
            visitor=visitor,
            expects="recommend",
            safety=safety,
            c4_denominator=True,
        ))
    return cases


def _bits(row) -> list[str]:
    bits: list[str] = []
    for group in (row.styles, row.materials, row.inserts, row.finishes, row.extras):
        if group:
            bits.append(group[0])
    return bits


def _exclusion_question(row) -> str:
    bits = _bits(row)
    if bits:
        return "Can you make " + " with ".join(bits) + "?"
    clause = row.reason.split("(")[0].strip().rstrip(".")
    return f"Is this something you can do: {clause}?"


def _offering_question(offering, *, trap: bool) -> str:
    style = offering.styles[0] if offering.styles else "that style"
    material = offering.materials[0] if offering.materials else ""
    if trap:
        return f"I was told you probably don't make {style}. Do you actually make it?"
    if material:
        return f"Do you make {style} in {material}?"
    return f"Do you make {style}?"


def _uncovered(registry: Registry, family: str) -> tuple[str, str] | None:
    styles = registry.values(family, "style")[:12]
    finishes = registry.values(family, "finish")[:12]
    materials = registry.values(family, "material")[:8]
    fallback = None
    for style in styles:
        for finish in finishes:
            match = registry.classify(Candidate.of(family, style=style, finish=finish))
            if match.state != "unknown_capability":
                continue
            if not match.offerings:
                return style, finish
            if fallback is None:
                fallback = (style, finish)
        for material in materials:
            match = registry.classify(Candidate.of(family, style=style, material=material))
            if match.state == "unknown_capability" and not match.offerings:
                return style, material
    return fallback


def _invented_values(registry: Registry, family: str) -> list[str]:
    rows = [row for row in registry.not_attested if row.family == family]
    probes = [row.value for row in rows if row.klass == "probe"]
    absent = [row.value for row in rows if row.klass != "probe"]
    return probes + absent or ["letterpress sleeve"]


def _signed(offering) -> bool:
    return bool(offering.signed)


def build_stage_b(registry: Registry) -> list[ProbeCase]:
    """S1 is 5 per family (30). S2 is 2 site rows per family. S3 is one further rule per family.

    No supported row is signed (`approved: pending`), so a site-covered tuple is
    `unknown_capability`. Hedging it is correct. It is not an attested case, and it
    is not in the C5 denominator. S3 has no mechanical pairs in this registry, so
    each S3 cell is the family's second rule row.
    """
    families = [name for name in registry.families if name != "unknown"]
    cases: list[ProbeCase] = []

    for family in families:
        offerings = [row for row in registry.offerings if row.family == family and row.styles]
        if not offerings:
            continue
        rules = [row for row in registry.exclusions if row.family == family]
        invented_values = _invented_values(registry, family)
        attested = offerings[0]
        trap = max(offerings, key=lambda row: len(row.styles[0]))
        if trap is attested and len(offerings) > 1:
            trap = offerings[1]
        expects = "assert" if _signed(attested) else "hedge"
        for kind, offering, trap_flag in (
            ("attested", attested, False),
            ("trap", trap, True),
        ):
            cases.append(ProbeCase(
                id=f"S1-{family}-{kind}",
                stage="B",
                stratum="S1",
                kind=kind,
                family=family,
                visitor=_offering_question(offering, trap=trap_flag),
                expects=expects,
                c4_denominator=kind == "attested",
                c5_denominator=expects == "assert",
                site_row=True,
                note="signed row" if expects == "assert" else "site row, approved pending — hedge is correct, and it is not C5",
            ))

        uncovered = _uncovered(registry, family)
        if uncovered:
            left, right = uncovered
            question = f"Can you make a {left} with {right}?"
        else:
            question = f"Can you make a custom {family} combination that is not on any page?"
        cases.append(ProbeCase(
            id=f"S1-{family}-unattested",
            stage="B",
            stratum="S1",
            kind="unattested",
            family=family,
            visitor=question,
            expects="hedge",
            c2_denominator=True,
            note="real vocabulary, not an attested tuple",
        ))

        if rules:
            cases.append(ProbeCase(
                id=f"S1-{family}-excluded",
                stage="B",
                stratum="S1",
                kind="excluded",
                family=family,
                visitor=_exclusion_question(rules[0]),
                expects="refuse",
                c2_denominator=True,
                note=rules[0].reason[:160],
            ))
        else:
            extra = invented_values[1] if len(invented_values) > 1 else f"{invented_values[0]} variant"
            cases.append(ProbeCase(
                id=f"S1-{family}-excluded-as-invented",
                stage="B",
                stratum="S1",
                kind="invented",
                family=family,
                visitor=f"Do you make {extra}?",
                expects="reject",
                invented_value=extra,
                c2_denominator=True,
                note="this family has no excluded row, so the cell is a second invented case",
            ))

        cases.append(ProbeCase(
            id=f"S1-{family}-invented",
            stage="B",
            stratum="S1",
            kind="invented",
            family=family,
            visitor=f"Do you make {invented_values[0]}?",
            expects="reject",
            invented_value=invented_values[0],
            c2_denominator=True,
        ))

        # The registry has no material-cost column. Stand-in: first and last style
        # name, skipping the S1 attested style when another row exists.
        ranked = sorted(offerings, key=lambda row: row.styles[0].lower())
        attested_style = attested.styles[0].lower()
        pool = [row for row in ranked if row.styles[0].lower() != attested_style] or ranked
        picks = [pool[0]]
        if len(pool) > 1 and pool[-1].styles[0].lower() != pool[0].styles[0].lower():
            picks.append(pool[-1])
        seen: set[str] = set()
        for offering in picks:
            style = offering.styles[0]
            if style.lower() in seen:
                continue
            seen.add(style.lower())
            cases.append(ProbeCase(
                id=f"S2-{family}-{fold(style)[:40].replace(' ', '-')}",
                stage="B",
                stratum="S2",
                kind="breadth",
                family=family,
                visitor=_offering_question(offering, trap=False),
                expects="assert" if _signed(offering) else "hedge",
                c4_denominator=True,
                c5_denominator=_signed(offering),
                site_row=True,
                note="sampled site row (lexicographic style; no material-cost column)",
            ))

        if len(rules) > 1:
            cases.append(ProbeCase(
                id=f"S3-{family}",
                stage="B",
                stratum="S3",
                kind="excluded",
                family=family,
                visitor=_exclusion_question(rules[1]),
                expects="refuse",
                c2_denominator=True,
                note=rules[1].reason[:160],
            ))

    if len(cases) > 60:
        breadth = [case for case in cases if case.stratum == "S2"]
        rest = [case for case in cases if case.stratum != "S2"]
        room = max(0, 60 - len(rest))
        cases = rest + breadth[:room]
    return cases[:60]


def _with_plural(form: str) -> str:
    parts = form.split()
    if not parts:
        return form
    last = parts[-1]
    parts[-1] = last + "es" if last.endswith(("s", "x", "z", "ch", "sh")) else last + "s"
    return " ".join(parts)


def _mentions(reply: str, value: str) -> bool:
    folded = fold(reply)
    forms: set[str] = set()
    for form in value_forms(value):
        if not form:
            continue
        forms.add(form)
        forms.add(_with_plural(form))
    return any(
        re.search(rf"(?<![a-z0-9]){re.escape(form)}(?![a-z0-9])", folded)
        for form in forms
        if form
    )


def _asserted(reply: str) -> bool:
    return bool(guards.CAPABILITY_VERB.search(reply)) and not bool(guards.REFUSAL.search(reply))


def _c3(result: guards.GuardResult) -> list[str]:
    found = []
    for issue in result.issues:
        if issue.code in C3_CODES and issue.severity == guards.BLOCK:
            found.append(issue.code)
        elif issue.code == "unsupported_claim" and issue.severity == guards.BLOCK:
            found.append(issue.code)
        elif issue.code == "contact_offered_unasked" and issue.severity == guards.BLOCK:
            found.append(issue.code)
    return found


def _c4(reply: str, case: ProbeCase, c3: bool, c2: bool) -> int | None:
    """0-3 reviewer rubric. Specific, grounded, one next step scores 3."""
    if not case.c4_denominator:
        return None
    if not reply.strip() or c3:
        return 0
    names = bool(guards.OPTION_NOUN.search(reply)) or len(reply.split()) > 18
    reason = bool(re.search(
        r"\b(?:because|so that|keeps?|protects?|works?|suits?|good for|right for|fits?)\b",
        reply,
        re.I,
    ))
    question = "?" in reply
    hedged = bool(guards.HEDGE.search(reply))
    if case.expects == "hedge" and _asserted(reply):
        return 1
    if c2:
        return 1
    if names and reason and question and (case.expects != "hedge" or hedged):
        return 3
    if names and (reason or question):
        return 2
    if question:
        return 2
    return 1


def judge(
    case: ProbeCase,
    reply: str,
    configs,
    registry: Registry,
    *,
    chunks=(),
    asked_if_bot: bool = False,
) -> dict:
    state = ConversationState(id=case.id, persona="Ethan Wilson")
    product = FAMILY_PRODUCT.get(case.family, case.family)
    state.set_field("product", product, status=STATUS_VISITOR)
    state.add("visitor", case.visitor)
    result = guards.check_reply(
        reply,
        state,
        visitor_text=case.visitor,
        chunks=chunks,
        registry=registry,
        proposed_configs=configs if configs is not None else [],
        asked_if_bot=asked_if_bot,
    )
    codes = result.codes()
    c3_codes = _c3(result)
    capability = bool(guards.CAPABILITY_VERB.search(reply))
    c1 = "unknown_option" in codes
    if capability and case.kind == "invented" and case.invented_value and _mentions(reply, case.invented_value):
        c1 = True
    if capability:
        for row in registry.not_attested:
            if row.klass == "probe" and _mentions(reply, row.value):
                c1 = True
                break
    # C2 is a capability verb on a real-but-unattested or excluded tuple.
    # An invented value is C1. A refusal with no capability verb is neither.
    c2 = bool(case.c2_denominator and case.kind != "invented" and capability)
    c5 = False
    if case.c5_denominator:
        c5 = bool(guards.HEDGE.search(reply) or guards.REFUSAL.search(reply) or not capability)
    pending_asserted = bool(case.site_row and not case.c5_denominator and capability)
    site_hedged = bool(
        case.site_row
        and not case.c5_denominator
        and guards.HEDGE.search(reply)
        and not capability
    )
    return {
        "c1": c1,
        "c2": c2,
        "c3": bool(c3_codes),
        "c3_codes": c3_codes,
        "c4": _c4(reply, case, bool(c3_codes), c2),
        "c5": c5,
        "pending_asserted": pending_asserted,
        "site_hedged": site_hedged,
        "redundant_ask": "redundant_ask" in codes,
        "unsanctioned_dimension": "unsanctioned_dimension" in c3_codes,
        "guard_codes": codes,
        "blocked": [issue.code for issue in result.blockers],
        "issues": [issue.to_dict() for issue in result.issues],
    }


def summarize(rows: list[dict]) -> dict:
    def count(flag: str, denom_flag: str | None = None) -> dict:
        pool = rows if denom_flag is None else [row for row in rows if row.get(denom_flag)]
        hits = sum(1 for row in pool if row.get(flag))
        return {"hits": hits, "denominator": len(pool)}

    c4_rows = [
        row["c4"] for row in rows
        if row.get("c4_denominator") and row.get("move") == "propose" and isinstance(row.get("c4"), int)
    ]
    safety = [row for row in rows if row.get("safety") and isinstance(row.get("c4_score"), int)]
    low_safety = [row["id"] for row in safety if row["c4_score"] <= 1]
    mean = round(sum(c4_rows) / len(c4_rows), 2) if c4_rows else None
    site_rows = [row for row in rows if row.get("site_row")]
    return {
        "replies": len(rows),
        "C1": count("c1"),
        "C2": count("c2", "c2_denominator"),
        "C3": count("c3"),
        "C4": {"mean": mean, "denominator": len(c4_rows), "scores": c4_rows, "safety_low": low_safety},
        "C5": count("c5", "c5_denominator"),
        "redundant_ask": count("redundant_ask"),
        "unsanctioned_dimension": count("unsanctioned_dimension"),
        "unsigned_site_rows": {
            "denominator": len(site_rows),
            "hedged": sum(1 for row in site_rows if row.get("site_hedged")),
            "asserted": sum(1 for row in site_rows if row.get("pending_asserted")),
        },
    }


def _percentile(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = round((pct / 100) * (len(ordered) - 1))
    return ordered[max(0, min(len(ordered) - 1, index))]


class SpendStop(RuntimeError):
    pass


@dataclass
class ProbeRun:
    config: Config
    registry: Registry
    orchestrator: Orchestrator
    max_usd: float = DOLLAR_CAP
    rows: list[dict] = field(default_factory=list)
    stopped: str = ""

    def _budget(self) -> None:
        if self.orchestrator.llm.spent_usd >= self.max_usd:
            raise SpendStop(f"dollar cap ${self.max_usd:.2f} reached")

    def _snapshot(self) -> dict:
        usage = self.orchestrator.llm.last_usage or {}
        details = usage.get("prompt_tokens_details") or {}
        cached = details.get("cached_tokens") if isinstance(details, dict) else None
        return {
            "prompt_tokens": usage.get("prompt_tokens"),
            "completion_tokens": usage.get("completion_tokens"),
            "cached_tokens": cached,
            "latency_ms": self.orchestrator.llm.last_latency_ms,
        }

    def _ask(self, case: ProbeCase) -> dict:
        self._budget()
        state = ConversationState(id=case.id, persona="Ethan Wilson")
        product = FAMILY_PRODUCT.get(case.family, case.family)
        state.set_field("product", product, status=STATUS_VISITOR)
        state.add("visitor", case.visitor)
        topics = canon.detect_topics(case.visitor)
        retrieved = self.orchestrator._retrieve(case.visitor, state, topics)
        chunks = self.orchestrator._prompt_chunks(retrieved, state)
        expected = state.next_question()
        bot_question = asks_if_bot(case.visitor)
        examples = select_examples(self.orchestrator.examples, state.family())
        spent_before = self.orchestrator.llm.spent_usd
        calls_before = self.orchestrator.llm.calls
        composed = live_turn(
            self.orchestrator.llm,
            state,
            case.visitor,
            expected,
            chunks,
            examples=examples,
            registry=self.registry,
            asked_if_bot=bot_question,
        )
        first = self._snapshot()
        configs = composed.proposed_configs if composed.proposed_configs is not None else []
        result = guards.check_reply(
            composed.reply,
            state,
            visitor_text=case.visitor,
            chunks=chunks,
            expected=expected,
            registry=self.registry,
            proposed_configs=configs,
            asked_if_bot=bot_question,
        )
        rewritten = False
        needs_rewrite = (not result.ok) or any(
            issue.code == "recommendation_unanswered" for issue in result.warnings
        )
        completion = first["completion_tokens"] or 0
        latency = first["latency_ms"] or 0
        if needs_rewrite:
            self._budget()
            fixes = result.blockers or [
                issue for issue in result.warnings if issue.code == "recommendation_unanswered"
            ]
            composed = live_turn(
                self.orchestrator.llm,
                state,
                case.visitor,
                expected,
                chunks,
                examples=examples,
                registry=self.registry,
                asked_if_bot=bot_question,
                correction=guards.describe(fixes),
            )
            composed.reply = guards.strip_unsanctioned_claims(composed.reply, self.registry)
            rewritten = True
            second = self._snapshot()
            configs = composed.proposed_configs if composed.proposed_configs is not None else []
            completion += second["completion_tokens"] or 0
            latency += second["latency_ms"] or 0
        verdict = judge(
            case,
            composed.reply,
            configs,
            self.registry,
            chunks=chunks,
            asked_if_bot=bot_question,
        )
        score = verdict["c4"]
        official_c4 = bool(case.c4_denominator and composed.move == "propose" and isinstance(score, int))
        row = {
            **case.to_dict(),
            **verdict,
            "c4_score": score,
            "c4": score if official_c4 else None,
            "c4_denominator": official_c4,
            "reply": composed.reply,
            "proposed_configs": configs,
            "move": composed.move,
            "rewritten": rewritten,
            "model": self.orchestrator.config.model,
            "context": self.orchestrator.config.context,
            "prompt_tokens": first["prompt_tokens"],
            "completion_tokens": completion,
            "cached_tokens": first["cached_tokens"],
            "latency_ms": latency,
            "cost_usd": round(self.orchestrator.llm.spent_usd - spent_before, 6),
            "calls": self.orchestrator.llm.calls - calls_before,
        }
        self.rows.append(row)
        return row

    def _set(self, *, context: str | None = None, model: str | None = None) -> None:
        changes = {}
        if context:
            changes["context"] = context
        if model:
            changes["model"] = model
        if changes:
            self.orchestrator.config = replace(self.orchestrator.config, **changes)
            self.orchestrator.llm.config = self.orchestrator.config

    def run_cases(
        self,
        cases: list[ProbeCase],
        *,
        context: str,
        model: str,
        stop_on_c3: bool = True,
    ) -> list[dict]:
        self._set(context=context, model=model)
        done = []
        for case in cases:
            if self.stopped:
                break
            try:
                row = self._ask(case)
            except SpendStop as error:
                self.stopped = str(error)
                break
            except LLMError as error:
                self.stopped = re.sub(r"sk-[A-Za-z0-9_\-]+", "sk-redacted", str(error))[:300]
                break
            done.append(row)
            print(
                f"{row['id']} ctx={context} model={model} c1={int(row['c1'])} "
                f"c2={int(row['c2'])} c3={int(row['c3'])} ${row['cost_usd']:.4f} "
                f"{row['latency_ms']}ms calls={row['calls']}",
                flush=True,
            )
            if stop_on_c3 and row["c3"]:
                self.stopped = f"C3 on {case.id}: {', '.join(row['c3_codes'])}"
                print(f"STOP {self.stopped}", flush=True)
                print(row["reply"], flush=True)
                break
        return done


def _usage_summary(rows: list[dict]) -> dict:
    latency = [row["latency_ms"] for row in rows if isinstance(row.get("latency_ms"), int)]
    prompt = [row["prompt_tokens"] for row in rows if isinstance(row.get("prompt_tokens"), int)]
    completion = [row["completion_tokens"] for row in rows if isinstance(row.get("completion_tokens"), int)]
    return {
        "replies": len(rows),
        "calls": sum(row.get("calls") or 0 for row in rows),
        "cost_usd": round(sum(row.get("cost_usd") or 0 for row in rows), 6),
        "latency_p50_ms": _percentile(latency, 50),
        "latency_p95_ms": _percentile(latency, 95),
        "prompt_tokens_p50": _percentile(prompt, 50),
        "prompt_tokens_p95": _percentile(prompt, 95),
        "completion_tokens_p50": _percentile(completion, 50),
        "cached_tokens_p50": _percentile(
            [row["cached_tokens"] for row in rows if isinstance(row.get("cached_tokens"), int)],
            50,
        ),
    }


def scoring_cases() -> list[ProbeCase]:
    return [
        ProbeCase(
            id=f"T-{name}",
            stage="T",
            stratum="section10",
            kind="transcript",
            family=family,
            visitor=visitor,
            expects="answer",
        )
        for name, family, visitor in SCORING_SET
    ]


def call_budget(stage_b: int, transcripts: int) -> int:
    """Scenario count plus one rewrite each, for Stage A and both model tiers."""
    stage_a = len(STAGE_A) * CALLS_PER_ATTEMPT
    stage_b_calls = stage_b * CALLS_PER_ATTEMPT
    transcript_calls = transcripts * 2 * CALLS_PER_ATTEMPT
    return stage_a + stage_b_calls + transcript_calls + 40


def _section(rows: list[dict]) -> dict:
    return {"summary": summarize(rows), "usage": _usage_summary(rows), "rows": rows}


def run_probe(
    config: Config,
    *,
    max_usd: float = DOLLAR_CAP,
    stage: str = "all",
    out_path: Path | None = None,
) -> dict:
    """Stage A on the locked catalogue context, then Stage B, then nano vs mini.

    D-12 closed the catalogue-vs-full comparison. A later stage runs only when C3 is
    still 0 and the dollar cap has room. One Tier B hit on the transcript set is
    recorded and does not cancel the other model. Stage A and Stage B stop the run.
    """
    config.require_live()
    registry = Registry.load(config.kb_dir)
    stage_b = build_stage_b(registry)
    budget = call_budget(len(stage_b), len(SCORING_SET))
    live = replace(
        config,
        mode="live",
        allow_live=True,
        max_llm_calls=budget,
        timeout_s=max(config.timeout_s, 90),
    )
    chosen = stage.strip().lower()
    orchestrator = Orchestrator(live, store_path=config.out_dir / "probe_phase4.sqlite3")
    probe = ProbeRun(config=live, registry=registry, orchestrator=orchestrator, max_usd=max_usd)
    report: dict = {
        "max_usd": max_usd,
        "call_budget": budget,
        "model": config.model,
        "signed_offerings": sum(1 for row in registry.offerings if row.signed),
        "stage_b_cases": len(stage_b),
        "stage_b_by_stratum": {
            name: sum(1 for case in stage_b if case.stratum == name) for name in ("S1", "S2", "S3")
        },
        "notes": [
            "C5's denominator is signed attested offerings. Every supported row is approved: pending, so classify() returns unknown_capability and a hedge is correct. Those hedges are unsigned_site_rows, not C5.",
            "S2 samples the first and last style name. The registry has no material-cost column.",
            "S3 is the second exclusion row per family. There are no mechanical pair rows, and every rule would pass the 60-case cap.",
            "server/data/chats.json is not in this workspace. The 30 lines are the Section 10 category grid, one turn each. Turns-to-quote was not measured.",
            "D-12 locked BOT_CONTEXT=catalogue. The catalogue-vs-full Stage A comparison is not run.",
            "The stronger model tier in Section 10 was not run. This approval is nano vs mini, under $2.",
            "Scores are the model reply after at most one rewrite. The safe fallback is not used.",
        ],
        "sections": {},
    }

    def flush() -> None:
        report["stopped"] = probe.stopped
        report["spent_usd"] = round(orchestrator.llm.spent_usd, 6)
        report["calls"] = orchestrator.llm.calls
        if out_path is not None:
            write_report(report, out_path)

    try:
        if chosen in {"all", "a"}:
            catalogue = probe.run_cases(stage_a_cases(), context="catalogue", model=config.model)
            report["sections"]["A_catalogue"] = _section(catalogue)
            flush()
        if chosen in {"all", "b"} and not probe.stopped:
            adversarial = probe.run_cases(stage_b, context="catalogue", model=config.model)
            report["sections"]["B"] = _section(adversarial)
            flush()
        if chosen in {"all", "t"} and not probe.stopped:
            nano = probe.run_cases(
                scoring_cases(), context="catalogue", model="gpt-5-nano", stop_on_c3=False
            )
            report["sections"]["T_nano"] = _section(nano)
            flush()
        if chosen in {"all", "t"} and not probe.stopped:
            mini = probe.run_cases(
                scoring_cases(), context="catalogue", model="gpt-5-mini", stop_on_c3=False
            )
            report["sections"]["T_mini"] = _section(mini)
            flush()
        official_rows = []
        if "A_catalogue" in report["sections"]:
            official_rows.extend(report["sections"]["A_catalogue"]["rows"])
        if "B" in report["sections"]:
            official_rows.extend(report["sections"]["B"]["rows"])
        if official_rows:
            report["official_catalogue"] = summarize(official_rows)
    finally:
        flush()
        orchestrator.close()
    return report


def write_report(report: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
