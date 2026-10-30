from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import canon, guards
from .capability import Candidate, Registry, estimate_tokens
from .composer import (
    Composed,
    HANDOFF_LINES,
    REPHRASES,
    clarify_reply,
    disclosure_line,
    heuristic_turn,
    live_turn,
    select_examples,
)
from .config import Config
from .kb import KBIndex, load_or_build
from .llm import LLMClient, LLMError
from .personas import persona_for
from .state import (
    FIELD_LABELS,
    PRODUCT_QUESTION,
    ConversationState,
    apply_field_updates,
    asks_if_bot,
    extract_fields,
    family_of,
    is_context_question,
    is_meta_question,
    is_option_request,
    is_question,
    is_goodbye,
    is_job_pitch,
    refuses_contact,
    wants_human,
)
from .store import StateStore

log = logging.getLogger("chatbot.orchestrator")


@dataclass
class TurnResult:
    conversation_id: str
    reply: str
    persona: str
    handoff: str = ""
    source: str = "heuristic"
    issues: list[dict] = field(default_factory=list)
    blocked: list[dict] = field(default_factory=list)
    retrieved: list[dict] = field(default_factory=list)
    accepted: dict[str, str] = field(default_factory=dict)
    rejected: dict[str, str] = field(default_factory=dict)
    elapsed_ms: int = 0
    flags: dict = field(default_factory=dict)
    known: dict[str, str] = field(default_factory=dict)
    visitor: str = ""
    move: str = ""
    proposed_configs: list = field(default_factory=list)
    registry: list = field(default_factory=list)
    rejected_drafts: list = field(default_factory=list)
    fields_proposed: list = field(default_factory=list)
    context: dict = field(default_factory=dict)
    goal: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "conversation_id": self.conversation_id,
            "reply": self.reply,
            "persona": self.persona,
            "handoff": self.handoff,
            "source": self.source,
            "issues": self.issues,
            "blocked": self.blocked,
            "retrieved": self.retrieved,
            "accepted": self.accepted,
            "rejected": self.rejected,
            "elapsed_ms": self.elapsed_ms,
            "flags": self.flags,
            "known": self.known,
            "visitor": self.visitor,
            "move": self.move,
            "proposed_configs": self.proposed_configs,
            "registry": self.registry,
            "rejected_drafts": self.rejected_drafts,
            "fields_proposed": self.fields_proposed,
            "context": self.context,
            "goal": self.goal,
        }


def load_golden(path: Path) -> list[dict]:
    if not path.exists():
        return []
    items: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if item.get("visitor") and item.get("reply"):
            items.append(item)
    return items


def explicit_human_request(text: str) -> bool:
    if not wants_human(text):
        return False
    if not asks_if_bot(text):
        return True
    return bool(
        re.search(
            r"\b(human|person|agent|representative|rep|operator|manager|customer service|live)\b",
            text,
            re.I,
        )
    )


def is_acknowledgement(text: str) -> bool:
    return bool(
        re.match(
            r"\s*(?:hi|hello|hey|good (?:morning|afternoon|evening)|thanks|thank you|ok(?:ay)?|sure|yes|yeah|no|nope)\b",
            text,
            re.I,
        )
    )


class Orchestrator:
    def __init__(
        self,
        config: Config,
        *,
        store_path: Path | None = None,
        index: KBIndex | None = None,
        examples: list[dict] | None = None,
    ) -> None:
        config.ensure_dirs()
        self.config = config
        self.store = StateStore(store_path or config.data_dir / "chatbot.sqlite3")
        self.index = index or load_or_build(config.kb_dir, config.data_dir)
        self.overrides = canon.load_overrides(config.data_dir)
        self.examples = examples if examples is not None else load_golden(config.data_dir / "golden.jsonl")
        self.llm = LLMClient(config)
        self.registry = Registry.load(config.kb_dir)
        self.primer_tokens = estimate_tokens(self.registry.render_primer())

    def close(self) -> None:
        self.store.close()

    def start(self, conversation_id: str, *, channel: str = "website") -> TurnResult:
        started = time.perf_counter()
        state = self.store.get_or_create(conversation_id)
        if state.messages:
            return TurnResult(
                conversation_id=conversation_id,
                reply="",
                persona=state.persona,
                handoff=state.handoff,
                source="none",
                flags={"already_started": True},
            )
        expected = ("product", PRODUCT_QUESTION)
        composed = heuristic_turn(state, "", expected, overrides=self.overrides)
        result = self._guard(composed.reply, state, "", [], expected, False)
        state.last_question = "product"
        state.fields["product"].attempts += 1
        state.add("ai", composed.reply)
        self.store.save(state)
        self.store.append_event(
            conversation_id,
            "start",
            {"channel": channel, "reply": composed.reply, "persona": state.persona},
        )
        return TurnResult(
            conversation_id=conversation_id,
            reply=composed.reply,
            persona=state.persona,
            source="heuristic",
            issues=[issue.to_dict() for issue in result.issues],
            elapsed_ms=int((time.perf_counter() - started) * 1000),
            context=self._context_view(None, self.llm.spent_usd, include_usage=False),
            goal=self._goal_view(state),
        )

    def _retrieve(self, text: str, state: ConversationState, topics: list[str]) -> list:
        query = " ".join([text, state.family(), " ".join(topics)])
        chunks = self.index.search(query, top_k=self.config.top_k, family=state.family())
        if not chunks:
            chunks = self.index.search(text, top_k=min(3, self.config.top_k))
        return chunks

    def _prompt_chunks(self, retrieved, state: ConversationState):
        if self.config.context == "full":
            return self.index.verified()
        if self.config.context == "catalogue":
            family = state.family()
            if family and family != "unknown":
                return [item for item in retrieved if family in item.chunk.families]
            return retrieved
        return retrieved

    def _handoff_reason(self, state: ConversationState, visitor: str, *, progressed: bool = False) -> str:
        if explicit_human_request(visitor):
            return "human"
        if state.complete():
            return "quote"
        # Four or more distinct facts in one message cannot be answered in a
        # chat-sized reply. Answer the first two and let a person take the rest.
        if len(canon.detect_topics(visitor)) >= 4:
            return "complex"
        # The opening greeting is not one of the capped replies. A turn that
        # just filled an open field is still the order, not a stall.
        after_greeting = state.turn_count
        if state.messages and state.messages[0].author == "ai":
            after_greeting = max(0, state.turn_count - 1)
        if (
            not progressed
            and after_greeting >= self.config.max_turns
            and not state.complete()
            and not state.flags.get("handoff_resumed")
        ):
            return "max_turns"
        return ""

    def _urgent_ask(self, state: ConversationState) -> str:
        """The most urgent missing field: product, what they are packing, size, quantity."""
        allowed = set(state.ask_set())
        for key in ("product", "use_case", "sizes", "quantity"):
            if key not in allowed:
                continue
            if key == "sizes" and state.size_needs_unit():
                return state.question_for(key)
            if state.fields[key].attempts >= 1 and key in REPHRASES:
                return REPHRASES[key]
            return state.question_for(key)
        return ""

    def _unattested_note(
        self,
        state: ConversationState,
        expected: tuple[str, str] | None,
        guard: guards.GuardResult | None,
        configs,
    ) -> str:
        """A blocked draft that named a real but unattested build, said safely."""
        if guard is None:
            return ""
        codes = {issue.code for issue in guard.blockers}
        if not codes & {"unsupported_configuration", "unknown_capability_unhedged"}:
            return ""
        tier_b = {
            "price_given",
            "time_promise",
            "discount_promise",
            "wrong_minimum",
            "minimum_needs_condition",
            "tier_b_hallucination",
            "canon_conflict",
            "unsanctioned_dimension",
            "human_claim",
            "unsupported_claim",
            "contact_offered_unasked",
        }
        if codes & tier_b or "unknown_option" in codes:
            return ""
        words: list[str] = []
        for item in configs or []:
            if not isinstance(item, dict):
                continue
            for key in ("style", "material", "finish", "finishes", "extras", "insert"):
                raw = item.get(key)
                values = raw if isinstance(raw, list) else [raw]
                for value in values:
                    text = str(value or "").strip()
                    # A catalogue dump or a sentence stuffed into a slot is not a build
                    # the visitor asked for. Kraft + gloss is. Nine primer values are not.
                    if not text or len(text) > 40 or len(text.split()) > 3:
                        continue
                    if re.search(r"[.;:]|\b(?:not specified|using|catalogue|goal)\b", text, re.I):
                        continue
                    if text.lower() not in {word.lower() for word in words}:
                        words.append(text)
        if not words or len(words) > 3:
            return ""
        signature = "|".join(sorted(word.lower() for word in words))
        if state.flags.get("unattested_noted") == signature:
            return ""
        state.flags["unattested_noted"] = signature
        labels = [word[:1].upper() + word[1:] for word in words]
        if len(labels) == 1:
            named = f"{labels[0]} is"
        elif len(labels) == 2:
            named = f"{labels[0]} and {labels[1]} are"
        else:
            named = f"{', '.join(labels[:-1])} and {labels[-1]} are"
        sentence = f"{named} noted. That build needs the team to confirm."
        question = ""
        if expected:
            question = state.question_for(expected[0]) if expected[0] == "sizes" and state.size_needs_unit() else expected[1]
        if question:
            sentence = f"{sentence} {question}"
        return sentence

    def _offslot_ack(self, state: ConversationState, accepted: dict[str, str], asked: str) -> str:
        """A material or finish given while style was the open question."""
        if asked != "style" or state.fields["style"].done:
            return ""
        values = [str(accepted[key]) for key in ("material", "finishes", "extras") if accepted.get(key)]
        if not values:
            return ""
        labels = [word[:1].upper() + word[1:] for word in values]
        if len(labels) == 1:
            named = f"{labels[0]} is"
        elif len(labels) == 2:
            named = f"{labels[0]} and {labels[1]} are"
        else:
            named = f"{', '.join(labels[:-1])} and {labels[-1]} are"
        return f"{named} noted. {state.question_for('style')}".strip()

    def _safe_fallback(
        self,
        state: ConversationState,
        expected: tuple[str, str] | None,
        handoff_reason: str,
        guard: guards.GuardResult | None = None,
        configs=None,
    ) -> str:
        if handoff_reason:
            return HANDOFF_LINES.get(handoff_reason, HANDOFF_LINES["stalled"])
        if state.last_question == "style" and state.fields["style"].value == "no preference":
            return heuristic_turn(
                state,
                state.last_visitor(),
                expected,
                overrides=self.overrides,
            ).reply
        note = self._unattested_note(state, expected, guard, configs)
        if note:
            return note
        visitor = state.last_visitor()
        if is_option_request(visitor):
            return heuristic_turn(
                state,
                visitor,
                expected,
                overrides=self.overrides,
            ).reply
        urgent = self._urgent_ask(state)
        # A meta-question gets one honest line and the open ask. No topic lecture.
        if asks_if_bot(visitor):
            parts = [disclosure_line(state.persona)]
            if urgent:
                parts.append(urgent)
            return " ".join(parts)
        if is_meta_question(visitor):
            parts = ["Fair question — I'll stick to what the quote actually needs."]
            if urgent:
                parts.append(urgent)
            return " ".join(parts)
        parts: list[str] = []
        topics = canon.topics_to_answer(visitor)
        if topics:
            parts.append(canon.effective_answer(topics[0], self.overrides))
        if urgent:
            parts.append(urgent)
        elif expected:
            parts.append(REPHRASES.get(expected[0]) or expected[1])
        return " ".join(parts).strip() or "What are you looking to have made — boxes, bags, labels, or something else?"

    def _finish_reply(
        self,
        reply: str,
        visitor: str,
        expected: tuple[str, str] | None,
        *,
        already_greeted: bool = False,
    ) -> str:
        """Drop an unsolicited MOQ lecture, a repeated greeting, and any extra question."""
        priority_key = expected[0] if expected else ""
        priority_text = expected[1] if expected else ""
        polished = guards.prepare_reply(
            reply,
            visitor,
            priority_key=priority_key,
            priority_text=priority_text,
            already_greeted=already_greeted,
        )
        if polished:
            return polished
        if expected:
            return expected[1]
        return str(reply or "").strip()

    def _guard(
        self,
        reply: str,
        state: ConversationState,
        visitor: str,
        chunks,
        expected: tuple[str, str] | None,
        handoff: bool,
        proposed_configs=None,
    ) -> guards.GuardResult:
        return guards.check_reply(
            reply,
            state,
            visitor_text=visitor,
            chunks=chunks,
            expected=expected,
            handoff=handoff,
            asked_if_bot=asks_if_bot(visitor),
            overrides=self.overrides,
            registry=self.registry,
            proposed_configs=proposed_configs,
        )

    def handle(self, conversation_id: str, text: str, *, channel: str = "website") -> TurnResult:
        started = time.perf_counter()
        spent_before = self.llm.spent_usd
        state = self.store.get_or_create(conversation_id)
        visitor = str(text or "").strip()

        if not visitor:
            return TurnResult(conversation_id=conversation_id, reply="", persona=state.persona)

        if state.handoff:
            if channel == "ui" and state.handoff != "quote":
                resumed = state.handoff
                self.store.append_event(
                    conversation_id,
                    "handoff_resumed",
                    {"handoff": resumed, "channel": channel},
                )
                state.handoff = ""
                state.flags["handoff_resumed"] = True
                self.store.save(state)
            else:
                return TurnResult(
                    conversation_id=conversation_id,
                    reply="",
                    persona=state.persona,
                    handoff=state.handoff,
                    source="none",
                    flags={"already_handed_off": True},
                )

        state.repair_fields()
        state.add("visitor", visitor)
        asked_before = state.last_question
        was_reachable = state.reachable()
        confirmed = state.confirm_suggested(visitor)
        extracted = extract_fields(visitor, state.last_question, state, registry=self.registry)
        accepted, rejected = apply_field_updates(state, extracted, visitor)
        for key in confirmed:
            accepted[key] = state.fields[key].value
        # The unit follow-up gets exactly one turn. If it is not answered with a
        # unit, keep the size as unconfirmed and move on instead of asking again.
        state.finalize_stalled()

        topics = canon.detect_topics(visitor)
        family = family_of(visitor)
        unclear = (
            not accepted
            and not topics
            and family == "unknown"
            and not is_acknowledgement(visitor)
            and not is_goodbye(visitor)
            and not is_job_pitch(visitor)
            and not asks_if_bot(visitor)
            and len(visitor.split()) <= 8
        )

        refused_contact = (
            not was_reachable
            and state.last_question in {"email", "phone", "name"}
            and refuses_contact(visitor)
        )
        if refused_contact:
            state.fields["email"].attempts = max(state.fields["email"].attempts, 2)
            state.fields["phone"].attempts = max(state.fields["phone"].attempts, 2)

        expected = state.next_question()
        handoff_reason = self._handoff_reason(state, visitor, progressed=bool(accepted))
        if refused_contact:
            handoff_reason = "declined"
        if not expected and not handoff_reason and not state.complete():
            handoff_reason = "stalled"
        if handoff_reason:
            state.handoff = handoff_reason
            expected = None

        chunks = self._retrieve(visitor, state, topics)
        prompt_chunks = self._prompt_chunks(chunks, state)
        examples = select_examples(self.examples, state.family())

        clarification = clarify_reply(state) if is_context_question(visitor) else ""
        offslot = ""
        if not handoff_reason and not is_question(visitor):
            offslot = self._offslot_ack(state, accepted, asked_before)

        composed = Composed(reply="")
        source = "heuristic"
        if clarification:
            composed = Composed(reply=clarification, source="heuristic")
            base = state.question_for(state.last_question)
            if base:
                expected = (state.last_question, base)
            # A clarification question is not a failed answer, so it should not
            # use up the two attempts that move the script past a field.
            field_value = state.fields.get(state.last_question)
            if field_value and not field_value.done:
                field_value.attempts = min(field_value.attempts, 1)
        elif offslot:
            composed = Composed(reply=offslot, source="heuristic")
        elif self.config.real_llm_enabled and not handoff_reason:
            try:
                composed = live_turn(
                    self.llm,
                    state,
                    visitor,
                    expected,
                    prompt_chunks,
                    overrides=self.overrides,
                    examples=examples,
                    asked_if_bot=asks_if_bot(visitor),
                    registry=self.registry,
                )
                source = "live"
                state.flags.pop("llm_error", None)
            except LLMError as error:
                log.warning("Live compose failed (%s); using heuristic reply", error)
                state.flags["llm_error"] = str(error)[:200]
                composed = Composed(reply="")
                source = "heuristic"

        if not composed.reply:
            composed = heuristic_turn(
                state,
                visitor,
                expected,
                handoff_reason=handoff_reason,
                overrides=self.overrides,
                unclear=unclear,
            )
            source = "heuristic"

        already_greeted = bool(state.bot_texts())
        composed.reply = self._finish_reply(
            composed.reply, visitor, expected, already_greeted=already_greeted
        )
        result = self._guard(
            composed.reply,
            state,
            visitor,
            prompt_chunks,
            expected,
            bool(handoff_reason),
            composed.proposed_configs,
        )
        blocked: list[dict] = []
        rejected_drafts: list[dict] = []
        if not result.ok:
            blocked = [issue.to_dict() for issue in result.blockers]

        recommendation_gap = any(
            issue.code == "recommendation_unanswered" for issue in result.warnings
        )
        if source == "live" and (not result.ok or recommendation_gap):
            rejected_drafts.append(self._draft_record("draft", composed, result))
        if (not result.ok or recommendation_gap) and source == "live":
            fixes = result.blockers or [
                issue for issue in result.warnings if issue.code == "recommendation_unanswered"
            ]
            correction = guards.describe(fixes)
            try:
                rewritten = live_turn(
                    self.llm,
                    state,
                    visitor,
                    expected,
                    prompt_chunks,
                    overrides=self.overrides,
                    examples=examples,
                    asked_if_bot=asks_if_bot(visitor),
                    correction=correction,
                    registry=self.registry,
                )
                rewritten.reply = guards.strip_unsanctioned_claims(rewritten.reply, self.registry)
                rewritten.reply = self._finish_reply(
                    rewritten.reply, visitor, expected, already_greeted=already_greeted
                )
                # A rewrite is reconciled again. Fixing a price and quietly adding
                # an option the new configs do not name still blocks.
                rewritten_result = self._guard(
                    rewritten.reply,
                    state,
                    visitor,
                    prompt_chunks,
                    expected,
                    bool(handoff_reason),
                    rewritten.proposed_configs,
                )
                rewritten_gap = any(
                    issue.code == "recommendation_unanswered"
                    for issue in rewritten_result.warnings
                )
                if rewritten.reply and rewritten_result.ok and not rewritten_gap:
                    composed = rewritten
                    result = rewritten_result
                    source = "live-rewrite"
                    blocked = []
                elif rewritten.reply:
                    rejected_drafts.append(self._draft_record("rewrite", rewritten, rewritten_result))
            except LLMError as error:
                log.warning("Live rewrite failed (%s); continuing with fallback", error)

        if not result.ok:
            fallback = self._finish_reply(
                self._safe_fallback(
                    state,
                    expected,
                    handoff_reason,
                    guard=result,
                    configs=composed.proposed_configs,
                ),
                visitor,
                expected,
                already_greeted=already_greeted,
            )
            fallback_result = self._guard(
                fallback, state, visitor, prompt_chunks, expected, bool(handoff_reason)
            )
            if fallback_result.blockers:
                fallback = self._finish_reply(
                    expected[1] if expected else (HANDOFF_LINES.get(handoff_reason) or ""),
                    visitor,
                    expected,
                    already_greeted=already_greeted,
                )
                fallback_result = self._guard(
                    fallback, state, visitor, prompt_chunks, expected, bool(handoff_reason)
                )
            composed = Composed(reply=fallback, source="fallback")
            result = fallback_result
            source = "fallback"

        reply = composed.reply.strip()
        if composed.fields:
            # The live model repeats every detail it knows in `fields`. Only let
            # it fill an open field, or the field it was just asked about, so an
            # echo cannot overwrite an answer already on file.
            llm_fields = {
                key: value
                for key, value in composed.fields.items()
                if key not in accepted
                and (
                    key not in state.fields
                    or not state.fields[key].done
                    or key == state.last_question
                )
            }
            llm_accepted, llm_rejected = apply_field_updates(
                state, llm_fields, visitor, source="model", bases=composed.bases
            )
            accepted.update(llm_accepted)
            rejected.update(llm_rejected)

        asked = guards.asked_field(reply)
        asking = guards.count_questions(reply) > 0
        if not asked and asking and expected:
            asked = expected[0]
        if asked:
            state.last_question = asked
            field_value = state.fields.get(asked)
            unit_question = (
                asked == "sizes"
                and re.search(r"\binches\b", reply, re.I)
                and re.search(r"\bcm\b", reply, re.I)
            )
            if unit_question:
                # The unit follow-up is not a repeated size ask, so it must not
                # count toward the attempt limit that marks a size unconfirmed.
                state.flags["unit_asked"] = True
            elif field_value and not field_value.done:
                field_value.attempts += 1
        else:
            state.last_question = ""

        if re.search(r"\b(?:moq|minimum)\b", reply, re.I):
            state.flags["minimum_stated"] = True
        if re.search(r"\bno standard size\b|\bmade to fit\b", reply, re.I):
            state.flags["size_no_standard_explained"] = True

        state.add("ai", reply)
        self.store.save(state)
        self.store.append_event(
            conversation_id,
            "turn",
            {
                "channel": channel,
                "visitor": visitor,
                "reply": reply,
                "persona": state.persona,
                "source": source,
                "handoff": state.handoff,
                "issues": [issue.to_dict() for issue in result.issues],
                "retrieved": [item.chunk.id for item in chunks],
                "context": self.config.context,
                "arch": self.config.arch,
                "move": composed.move,
                "proposed_configs": composed.proposed_configs or [],
                "primer_tokens": self.primer_tokens,
                "prompt_chunks": len(prompt_chunks),
                "cost_usd": round(self.llm.spent_usd - spent_before, 6),
                "prompt_tokens": (self.llm.last_usage or {}).get("prompt_tokens"),
                "completion_tokens": (self.llm.last_usage or {}).get("completion_tokens"),
                "latency_ms": self.llm.last_latency_ms,
                "accepted": accepted,
                "rejected": rejected,
                "rejected_drafts": rejected_drafts,
            },
        )
        sent_configs = composed.proposed_configs or []
        return TurnResult(
            conversation_id=conversation_id,
            reply=reply,
            persona=state.persona,
            handoff=state.handoff,
            source=source,
            issues=[issue.to_dict() for issue in result.issues],
            blocked=blocked,
            retrieved=[
                {"id": item.chunk.id, "title": item.chunk.title, "score": round(item.score, 3)}
                for item in chunks
            ],
            accepted=accepted,
            rejected=rejected,
            elapsed_ms=int((time.perf_counter() - started) * 1000),
            flags={key: value for key, value in state.flags.items() if isinstance(value, (str, int, bool))},
            known={key: value.value for key, value in state.fields.items() if value.value},
            visitor=visitor,
            move=composed.move,
            proposed_configs=sent_configs,
            registry=self._registry_view(sent_configs),
            rejected_drafts=rejected_drafts,
            fields_proposed=list(composed.fields_proposed or []),
            context=self._context_view(
                prompt_chunks,
                spent_before,
                include_usage=source in {"live", "live-rewrite"},
            ),
            goal=self._goal_view(state),
        )

    def _draft_record(self, stage: str, composed: Composed, guard: guards.GuardResult) -> dict:
        configs = composed.proposed_configs or []
        return {
            "stage": stage,
            "move": composed.move,
            "configs": configs,
            "registry": self._registry_view(configs),
            "fields_proposed": list(composed.fields_proposed or []),
            "issues": [issue.to_dict() for issue in guard.issues],
        }

    def _registry_view(self, configs) -> list[dict]:
        rows: list[dict] = []
        for item in configs or []:
            if not isinstance(item, dict):
                continue
            family = str(item.get("family") or "").strip().lower() or "unknown"
            candidate = Candidate.of(
                family,
                style=item.get("style"),
                material=item.get("material"),
                insert=item.get("insert") or item.get("inserts"),
                finish=item.get("finish") or item.get("finishes"),
                extras=item.get("extras") or item.get("extra"),
            )
            match = self.registry.classify(candidate)
            rows.append(
                {
                    "family": candidate.family,
                    "style": list(candidate.style),
                    "material": list(candidate.material),
                    "insert": list(candidate.insert),
                    "finish": list(candidate.finish),
                    "extras": list(candidate.extras),
                    "state": match.state,
                    "reason": match.reason,
                }
            )
        return rows

    def _goal_view(self, state: ConversationState) -> dict:
        fields = []
        for key, label in FIELD_LABELS.items():
            value = state.fields[key]
            fields.append(
                {
                    "key": key,
                    "label": label,
                    "value": value.value,
                    "status": value.status,
                    "basis": value.basis,
                    "attempts": value.attempts,
                }
            )
        return {
            "family": state.family(),
            "ask": state.ask_set(),
            "missing": state.missing_for_prompt(),
            "do_not_ask": [{"key": key, "words": words} for key, words in state.do_not_ask()],
            "fields": fields,
        }

    def _context_view(self, prompt_chunks, spent_before: float, *, include_usage: bool) -> dict:
        usage = (self.llm.last_usage or {}) if include_usage else {}
        chunks = prompt_chunks or []
        return {
            "tier": self.config.context,
            "arch": self.config.arch,
            "primer_tokens": self.primer_tokens,
            "prompt_chunks": len(chunks),
            "prompt_tokens": usage.get("prompt_tokens"),
            "completion_tokens": usage.get("completion_tokens"),
            "cost_usd": round(self.llm.spent_usd - spent_before, 6) if include_usage else 0,
            "latency_ms": self.llm.last_latency_ms if include_usage else None,
        }
