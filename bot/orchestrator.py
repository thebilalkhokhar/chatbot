from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import canon, guards
from .capability import Registry, estimate_tokens
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
    PRODUCT_QUESTION,
    ConversationState,
    apply_field_updates,
    asks_if_bot,
    extract_fields,
    family_of,
    is_context_question,
    is_meta_question,
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

    def _handoff_reason(self, state: ConversationState, visitor: str) -> str:
        if explicit_human_request(visitor):
            return "human"
        if state.complete():
            return "quote"
        # Four or more distinct facts in one message cannot be answered in a
        # chat-sized reply. Answer the first two and let a person take the rest.
        if len(canon.detect_topics(visitor)) >= 4:
            return "complex"
        if (
            state.turn_count >= self.config.max_turns
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
            if state.fields[key].attempts >= 1 and key in REPHRASES:
                return REPHRASES[key]
            return state.question_for(key)
        return ""

    def _safe_fallback(
        self,
        state: ConversationState,
        expected: tuple[str, str] | None,
        handoff_reason: str,
    ) -> str:
        if handoff_reason:
            return HANDOFF_LINES.get(handoff_reason, HANDOFF_LINES["stalled"])
        visitor = state.last_visitor()
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
        topics = canon.detect_topics(visitor)
        if topics:
            parts.append(canon.effective_answer(topics[0], self.overrides))
        if urgent:
            parts.append(urgent)
        elif expected:
            parts.append(REPHRASES.get(expected[0]) or expected[1])
        return " ".join(parts).strip() or "What are you looking to have made — boxes, bags, labels, or something else?"

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
        confirmed = state.confirm_suggested(visitor)
        extracted = extract_fields(visitor, state.last_question, state)
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
            not state.reachable()
            and state.last_question in {"email", "phone", "name"}
            and refuses_contact(visitor)
        )
        if refused_contact:
            state.fields["email"].attempts = max(state.fields["email"].attempts, 2)
            state.fields["phone"].attempts = max(state.fields["phone"].attempts, 2)

        expected = state.next_question()
        handoff_reason = self._handoff_reason(state, visitor)
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
        elif self.config.real_llm_enabled and handoff_reason != "declined":
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
        if not result.ok:
            blocked = [issue.to_dict() for issue in result.blockers]

        recommendation_gap = any(
            issue.code == "recommendation_unanswered" for issue in result.warnings
        )
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
            except LLMError as error:
                log.warning("Live rewrite failed (%s); continuing with fallback", error)

        if not result.ok:
            fallback = self._safe_fallback(state, expected, handoff_reason)
            fallback_result = self._guard(
                fallback, state, visitor, prompt_chunks, expected, bool(handoff_reason)
            )
            if fallback_result.blockers:
                fallback = expected[1] if expected else (HANDOFF_LINES.get(handoff_reason) or "")
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
                "accepted": accepted,
                "rejected": rejected,
            },
        )

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
        )
