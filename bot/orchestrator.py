from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import canon, guards
from .capability import Candidate, Registry, estimate_tokens, fold
from .composer import (
    BOX_PRIMARY_FINISHES,
    Composed,
    HANDOFF_LINES,
    REPHRASES,
    _topic_answer,
    clarify_reply,
    disclosure_line,
    heuristic_turn,
    live_turn,
    select_examples,
)
from .attachments import AttachmentError, open_attachment_store
from .config import Config
from .kb import KBIndex, load_or_build
from .llm import LLMClient, LLMError
from .personas import persona_for
from .state import (
    AFFIRMATION_RE,
    BASIS_MODEL,
    CATALOGUE_OPTION_FIELDS,
    EMAIL_QUESTION,
    FAMILY_PRODUCT,
    FIELD_LABELS,
    invalid_email_reply_for,
    PRODUCT_QUESTION,
    STATUS_SUGGESTED,
    STATUS_UNKNOWN,
    STATUS_WAIVED,
    TO_BE_CONFIRMED,
    UNCERTAIN_WAIVE_FIELDS,
    UNIT_ONLY_RE,
    ConversationState,
    apply_field_updates,
    extract_contact_fields,
    asks_if_bot,
    asks_to_share_reference,
    continue_ask,
    defer_unanswered_open_field,
    extract_fields,
    family_candidates,
    field_clarify_phrase,
    field_shaped_attempt,
    family_of,
    contact_fields_refused,
    is_field_waiver_value,
    is_finish_none_token,
    is_material_only_pick,
    is_no_preference,
    is_soft_no_preference,
    is_to_be_confirmed,
    looks_like_invalid_email,
    needs_catalogue_options,
    valid_email,
    valid_phone,
    asks_language_preference,
    asks_size_guidance,
    asks_term_meaning,
    needs_language_preference_ack,
    greeting_ack,
    is_context_question,
    is_meta_question,
    is_option_request,
    is_question,
    is_visitor_greeting,
    is_goodbye,
    is_job_pitch,
    product_disambiguation_question,
    refuses_contact,
    wants_human,
    wants_recommendation,
)
from .reply_judge import (
    judge_reply,
    merge_corrections,
    settled_field_reasked,
    uncertainty_reasked_without_settle,
    waiver_fields_reasked,
)
from .turn_router import (
    catalogue_menu_focus,
    classify_turn,
    strip_checklist_locks,
)
from .reply_language import (
    LANGUAGE_S,
    SEND_BY_S,
    heuristic_language_preference_gloss,
    language_named_in_preference_ask,
    normalize_inbound,
    translate_outbound,
    turn_language_budget_s,
)
from .store import open_state_store
from .visitor_language import ENGLISH, session_language
from .vision import VisionResult, analyze_image

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
    language: str = ENGLISH
    reply_english: str = ""

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
            "language": self.language,
            "reply_english": self.reply_english,
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
        # Explicit store_path keeps local tests/replay on SQLite even when DATABASE_URL is set.
        if store_path is not None:
            self.store = open_state_store(path=store_path)
        else:
            self.store = open_state_store(
                path=config.data_dir / "chatbot.sqlite3",
                database_url=config.database_url,
            )
        self.index = index or load_or_build(config.kb_dir, config.data_dir)
        self.overrides = canon.load_overrides(config.data_dir)
        self.examples = examples if examples is not None else load_golden(config.data_dir / "golden.jsonl")
        self.llm = LLMClient(config)
        self.registry = Registry.load(config.kb_dir)
        self.primer_tokens = estimate_tokens(self.registry.render_primer())
        self.attachments = open_attachment_store(
            data_dir=config.data_dir,
            database_url=config.database_url if store_path is None else "",
            blob_token=config.blob_token,
            max_bytes=config.attachment_max_bytes,
        )

    def close(self) -> None:
        self.store.close()
        self.attachments.close()

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

    def _ambiguous_product_ask(
        self,
        state: ConversationState,
        visitor: str,
        accepted: dict[str, str],
    ) -> tuple[str, str]:
        """Keep product open: suggest the first-mentioned family, or re-ask the menu.

        Clear `{product} for {purpose}` lines are resolved in `family_of` before this
        runs. Remaining multi-family messages use propose-and-confirm instead of a
        stalled handoff.
        """
        product = state.fields["product"]
        # Attempts emptied the ask-set; keep one more confirm / menu turn.
        product.attempts = min(product.attempts, 1)
        if product.status == STATUS_SUGGESTED and product.value:
            return ("product", state.question_for("product") or PRODUCT_QUESTION)
        candidates = family_candidates(visitor)
        if len(candidates) < 2:
            candidates = family_candidates("", tuple(state.visitor_texts()[-4:]))
        if len(candidates) >= 2 and "product" not in accepted and not product.done:
            preferred = candidates[0]
            label = FAMILY_PRODUCT.get(preferred, preferred.replace("_", " "))
            # Direct suggest — avoid echo/traceable rejecting a multi-family line.
            state.set_field("product", label, BASIS_MODEL, raw="", status=STATUS_SUGGESTED)
            return ("product", product_disambiguation_question(candidates))
        return ("product", state.question_for("product") or PRODUCT_QUESTION)

    def _visitor_needs_direct_answer(
        self, state: ConversationState, visitor: str
    ) -> bool:
        """Visitor asked something that must be answered before checklist / build acks."""
        text = str(visitor or "").strip()
        if not text:
            return False
        if (
            asks_term_meaning(text)
            or asks_if_bot(text)
            or asks_to_share_reference(text)
            or is_meta_question(text)
            or is_option_request(text)
            or wants_recommendation(text)
            or needs_language_preference_ack(state, text)
            or canon.topics_to_answer(text)
        ):
            return True
        # Real question — not soft-no / bare affirmation on an open field.
        if (
            is_question(text)
            and not is_soft_no_preference(text)
            and not AFFIRMATION_RE.fullmatch(text)
        ):
            return True
        return False

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
        # Never replace a visitor question with "X is noted" — answer them first.
        if self._visitor_needs_direct_answer(state, state.last_visitor()):
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
        """Acknowledge a field given while another question was open."""
        noted: list[str] = []
        name = str(accepted.get("name") or "").strip()
        email = str(accepted.get("email") or "").strip()
        phone = str(accepted.get("phone") or "").strip()
        if name and asked != "name":
            noted.append("name")
        if email and asked != "email" and valid_email(email):
            noted.append("email")
        if phone and asked != "phone" and valid_phone(phone):
            noted.append("number")
        if noted:
            follow = self._offslot_followup(state, asked)
            if len(noted) >= 2:
                lead = "Thanks — I've got everything you shared."
            elif noted[0] == "name":
                first = name.split()[0]
                lead = f"Thanks, {first}."
            elif noted[0] == "email":
                lead = "Thanks — I've got your email."
            else:
                lead = "Thanks — I've got your number."
            return f"{lead} {follow}".strip()
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

    def _offslot_followup(self, state: ConversationState, asked: str) -> str:
        """Keep the open checklist question after an early contact answer."""
        if asked and asked in state.fields and not state.fields[asked].done:
            return (state.question_for(asked) or "").strip()
        if not state.fields["product"].done:
            return (state.question_for("product") or PRODUCT_QUESTION).strip()
        return ""

    def _vision_focus(
        self,
        state: ConversationState,
        expected: tuple[str, str] | None,
    ) -> tuple[str, str] | None:
        """Image turns follow the question already on the table when it is still open."""
        continued = continue_ask(state)
        if continued:
            return continued
        return expected

    def _vision_catalogue_terms(self, state: ConversationState, focus_field: str) -> str:
        """Approved vocabulary for the open field, so vision can map onto catalogue wording."""
        family = state.family()
        if not focus_field or family == "unknown" or self.registry is None:
            if focus_field == "finishes" and family in {"boxes", "unknown"}:
                return ", ".join(BOX_PRIMARY_FINISHES)
            return ""
        slot = {
            "style": "style",
            "finishes": "finish",
            "material": "material",
            "product": "style",
        }.get(focus_field, "")
        if focus_field == "finishes" and family == "boxes":
            return ", ".join(BOX_PRIMARY_FINISHES)
        if not slot:
            return ""
        values = self.registry.values(family, slot)
        if not values:
            return ""
        # Keep the prompt short: primary box styles / a sample of vocabulary.
        sample = list(values[:24])
        return ", ".join(sample)

    def _canonicalize_vision_updates(
        self,
        state: ConversationState,
        updates: dict[str, str],
        *,
        focus_field: str = "",
    ) -> dict[str, str]:
        """Keep vision proposals on the open field and map them to catalogue terms."""
        family = state.family()
        if focus_field == "sizes":
            return {}
        scoped = updates
        # A typed brief may carry product/qty/size alongside a finish cue — keep
        # every quote detail the vision model read, not only the open catalogue slot.
        quote_keys = {"product", "use_case", "quantity", "sizes", "email", "phone"}
        if focus_field in {"style", "finishes", "material"} and not (quote_keys & set(updates)):
            keep = {focus_field}
            if not state.fields["product"].done:
                keep.add("product")
            scoped = {key: value for key, value in updates.items() if key in keep}
        if self.registry is None or family == "unknown":
            return scoped

        from .state import is_to_be_confirmed

        slot_for = {"style": "style", "finishes": "finish", "material": "material"}
        out: dict[str, str] = {}
        for key, value in scoped.items():
            text = str(value or "").strip()
            if not text:
                continue
            if key in {"product", "use_case", "quantity", "sizes", "email", "phone"}:
                out[key] = text
                continue
            if key == "finishes" and is_to_be_confirmed(text):
                out[key] = text
                continue
            slot = slot_for.get(key)
            if not slot:
                out[key] = text
                continue
            if key == "finishes" and family == "boxes":
                folded = fold(text)
                mapped = ""
                for primary in BOX_PRIMARY_FINISHES:
                    if folded == fold(primary) or folded in fold(primary) or fold(primary) in folded:
                        mapped = primary
                        break
                if not mapped:
                    # Short forms like "matte" / "gloss" → official box finishes.
                    shorts = {
                        "matte": "matte lamination",
                        "matt": "matte lamination",
                        "gloss": "gloss lamination",
                        "glossy": "gloss lamination",
                        "soft touch": "soft touch lamination",
                        "softtouch": "soft touch lamination",
                        "spot uv": "spot UV",
                        "foil": "foil printing",
                    }
                    for tip, primary in shorts.items():
                        if tip in folded:
                            mapped = primary
                            break
                if mapped:
                    out[key] = mapped
                continue
            normalised = self.registry.normalise(family, slot, text)
            if normalised.answers_nothing or not normalised.value:
                continue
            allowed = {fold(item) for item in self.registry.values(family, normalised.slot)}
            candidate = normalised.value
            if fold(candidate) in allowed:
                out[key] = candidate
                continue
            # Partial / synonym match against vocabulary.
            hit = ""
            for item in self.registry.values(family, normalised.slot):
                if fold(candidate) in fold(item) or fold(item) in fold(candidate):
                    hit = item
                    break
            if hit:
                out[key] = hit
        return out

    def _vision_reply(
        self,
        state: ConversationState,
        vision: VisionResult,
        vision_accepted: dict[str, str],
        expected: tuple[str, str] | None,
    ) -> str:
        """Ack a reference image, confirm visible cues, or ask when the open field is unclear."""
        focused = self._vision_focus(state, expected)
        focus = focused[0] if focused else ""
        focus_question = focused[1] if focused else ""
        next_ask = ""
        if focused:
            next_ask = focused[1]
        else:
            next_ask = self._urgent_ask(state) or (
                "What should we quote from this — boxes, bags, labels, or something else?"
            )

        # Contact-only screenshot — acknowledge the contact, never invent packaging.
        email = (
            str(vision.email or "").strip()
            or str(vision_accepted.get("email") or "").strip()
            or str(state.fields["email"].value or "").strip()
        )
        phone = (
            str(vision.phone or "").strip()
            or str(vision_accepted.get("phone") or "").strip()
            or str(state.fields["phone"].value or "").strip()
        )
        if vision.is_contact_only():
            if email and valid_email(email):
                lead = f"Thanks — I can see your email as {email}. I've noted it."
            elif phone:
                lead = f"Thanks — I can see your phone number as {phone}. I've noted it."
            else:
                lead = (
                    "Thanks for the image — it looks like text or contact details rather "
                    "than a packaging mockup."
                )
            return f"{lead} {next_ask}".strip()

        summary = str(vision.summary or "").strip()
        stub = (not summary) or summary.lower().startswith("reference image received")
        if stub:
            lead = "I see the reference image you shared!"
        else:
            short = re.sub(r"\s+", " ", summary).strip()
            if len(short) > 140:
                short = short[:137].rsplit(" ", 1)[0] + "…"
            lead = f"I see the reference image you shared! {short}"
        lead = re.sub(r"\s+", " ", lead).strip()

        # Prefer confirming a suggested catalogue cue on packaging mockups.
        confirm_order = [focus] if focus in {"style", "product", "finishes", "material"} else []
        confirm_order.extend(
            key for key in ("style", "product", "finishes", "material") if key not in confirm_order
        )
        for key in confirm_order:
            value = vision_accepted.get(key) or ""
            if not value or state.fields[key].status != STATUS_SUGGESTED:
                continue
            if key == "product":
                return (
                    f"{lead} It looks like {value}. "
                    f"Should I use this for your order — are you looking for {value}?"
                )
            if key == "style":
                return (
                    f"{lead} It looks like a {value} style. "
                    "Should I use this for your order?"
                )
            if key == "finishes":
                return (
                    f"{lead} It looks like a {value} finish. "
                    "Should I use this for your order?"
                )
            return (
                f"{lead} It looks like {value}. "
                "Should I use this material for your order?"
            )

        # Typed order brief: cite what OCR already locked, then the next open ask.
        brief = vision.image_kind == "text" or bool(
            vision.quantity or vision.sizes or vision.use_case
        )
        if brief:
            noted: list[str] = []
            product = vision_accepted.get("product") or state.fields["product"].value
            use_case = vision_accepted.get("use_case") or state.fields["use_case"].value
            quantity = vision_accepted.get("quantity") or state.fields["quantity"].value
            sizes = vision_accepted.get("sizes") or state.fields["sizes"].value
            finishes = vision_accepted.get("finishes") or state.fields["finishes"].value
            if product:
                noted.append(str(product))
            if use_case:
                noted.append(f"for {use_case}")
            if quantity:
                noted.append(f"qty {quantity}")
            if sizes:
                noted.append(f"size {sizes}")
            if finishes:
                noted.append(f"finish {finishes}")
            if noted:
                lead = "Thanks — from your image I've noted " + ", ".join(noted) + "."
            return f"{lead} {next_ask}".strip()

        observation = str(vision.focus_observation or "").strip()
        if focus == "sizes":
            product = str(state.fields["product"].value or "label").strip() or "label"
            return (
                f"{lead} I can't clearly read exact dimensions from the image — "
                f"what size should we use for your {product}?"
            )
        if focus and not vision.focus_clear:
            phrase = field_clarify_phrase(focus)
            clarify = focus_question or f"Could you confirm {phrase}?"
            if observation:
                return f"{lead} {observation} {clarify}".strip()
            return (
                f"{lead} I couldn't clearly make out {phrase} from this image. "
                f"{clarify}"
            ).strip()

        return f"{lead} {next_ask}".strip()

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
        visitor = state.last_visitor()
        if state.last_question == "style" and state.fields["style"].value == "no preference":
            return heuristic_turn(
                state,
                visitor,
                expected,
                overrides=self.overrides,
            ).reply
        # "What does PE mean?" is a gloss ask — never "PE is noted" from unattested builds.
        if asks_term_meaning(visitor):
            return heuristic_turn(
                state,
                visitor,
                expected,
                overrides=self.overrides,
            ).reply
        # Any visitor ask (policy, materials, options, plain question) answers first.
        if self._visitor_needs_direct_answer(state, visitor):
            return heuristic_turn(
                state,
                visitor,
                expected,
                overrides=self.overrides,
            ).reply
        note = self._unattested_note(state, expected, guard, configs)
        if note:
            return note
        urgent = self._urgent_ask(state)
        # Language / identity first — never the generic meta line or a catalogue dump.
        if asks_if_bot(visitor):
            parts = [disclosure_line(state.persona)]
            if urgent:
                parts.append(urgent)
            return " ".join(parts)
        if needs_language_preference_ack(state, visitor):
            state.flags["language_preference_acked"] = True
            parts = [
                "Yes — I can continue in your language. "
                "I'll keep the questions focused on what the quote needs."
            ]
            if urgent:
                parts.append(urgent)
            return " ".join(parts)
        if asks_to_share_reference(visitor):
            parts = [
                "Yes — please attach your reference image with the attach control in the chat. "
                "When it arrives, we can match the visible details to your order together."
            ]
            focused = continue_ask(state) or expected
            if urgent and focused and focused[0] in {"sizes", "quantity", "use_case", "product"}:
                parts.append(focused[1])
            elif focused:
                parts.append(focused[1])
            elif urgent:
                parts.append(urgent)
            return " ".join(parts)
        if wants_recommendation(visitor) and state.last_question == "skus":
            parts = [
                "Most first runs use one design; if you have more artwork versions, "
                "count each as a design. If you do not have artwork yet, say so and "
                "we can note that for the team."
            ]
            if urgent:
                parts.append(urgent)
            return " ".join(parts)
        if (
            is_option_request(visitor)
            or wants_recommendation(visitor)
            or state.flags.get("offer_options_for")
        ):
            return heuristic_turn(
                state,
                visitor,
                expected,
                overrides=self.overrides,
            ).reply
        if is_meta_question(visitor):
            parts = ["Fair question — I'll stick to what the quote actually needs."]
            if urgent:
                parts.append(urgent)
            return " ".join(parts)
        parts: list[str] = []
        topics = canon.topics_to_answer(visitor)
        if topics:
            # Scope materials/styles to the active family so a labels chat never
            # dumps bag or box catalogue lines.
            scoped = _topic_answer(topics[0], state.family(), self.overrides)
            parts.append(scoped or canon.effective_answer(topics[0], self.overrides))
        if urgent:
            parts.append(urgent)
        elif expected:
            parts.append(REPHRASES.get(expected[0]) or expected[1])
        return " ".join(parts).strip() or "What are you looking to have made — boxes, bags, labels, or something else?"

    def _pending_suggestion(self, state: ConversationState) -> str:
        """Field key waiting on yes/no, if any."""
        for key in ("product", "style", "material", "finishes"):
            field_value = state.fields.get(key)
            if (
                field_value is not None
                and field_value.status == STATUS_SUGGESTED
                and str(field_value.value or "").strip()
            ):
                return key
        return ""

    def _llm_first_intent_turn(self, state: ConversationState, visitor: str) -> bool:
        """Live model should settle meaning before regex/heuristic phrase paths."""
        if not self.config.real_llm_enabled:
            return False
        if is_question(visitor) or wants_recommendation(visitor) or is_option_request(visitor):
            return False
        if asks_term_meaning(visitor) or asks_to_share_reference(visitor):
            return False
        if self._pending_suggestion(state):
            return True
        focus = str(state.last_question or "").strip()
        if focus not in UNCERTAIN_WAIVE_FIELDS:
            return False
        if (
            focus in state.fields
            and state.fields[focus].done
            and not (focus == "sizes" and state.size_needs_unit())
        ):
            # Already settled. The next message is not a new deferral of this slot,
            # and it must not be pinned onto whatever question comes after it.
            return False
        # Concrete answers stay on the fast heuristic/extract path.
        if field_shaped_attempt(
            focus, visitor, registry=self.registry, family=state.family()
        ):
            return False
        return len(str(visitor or "").split()) <= 12

    def _strip_early_uncertainty_extract(self, extracted: dict[str, str]) -> dict[str, str]:
        """Live owns deferral/no-preference; keep only concrete extract hits early."""
        kept: dict[str, str] = {}
        for key, value in (extracted or {}).items():
            if key in UNCERTAIN_WAIVE_FIELDS and (
                is_to_be_confirmed(value) or is_no_preference(value)
            ):
                continue
            kept[key] = value
        return kept

    def _backup_uncertainty_extract(
        self,
        state: ConversationState,
        visitor: str,
        accepted: dict[str, str],
    ) -> dict[str, str]:
        """If live left the open field unsettled, allow regex waiver as fallback only."""
        focus = str(state.last_question or "").strip()
        if focus not in UNCERTAIN_WAIVE_FIELDS:
            return {}
        if focus in accepted or state.fields[focus].done:
            return {}
        pending = self._pending_suggestion(state)
        if pending == focus and not is_soft_no_preference(visitor):
            # Still waiting on yes/no for the suggestion — unless they soft-declined.
            return {}
        updates = extract_fields(visitor, focus, state, registry=self.registry)
        value = str(updates.get(focus) or "").strip()
        if not (is_to_be_confirmed(value) or is_no_preference(value)):
            return {}
        return {focus: value}

    def _continues_settled_field(self, state: ConversationState, visitor: str) -> bool:
        """True when the message names a settled checklist field other than the one open.

        Uses the same field probes as reply checking. A repeat about designs must
        not waive zipper just because designs was already stored and the script
        had moved on.
        """
        focus = str(state.last_question or "").strip()
        named = [
            key
            for key, pattern in guards.FIELD_PROBES
            if pattern.search(str(visitor or ""))
        ]
        if not named or focus in named:
            return False
        return any(
            key in state.fields
            and state.fields[key].done
            and not (key == "sizes" and state.size_needs_unit())
            for key in named
        )

    def _apply_uncertainty_backup(
        self,
        state: ConversationState,
        visitor: str,
        accepted: dict[str, str],
        rejected: dict[str, str],
    ) -> None:
        """Settle open-field deferral into state before the outgoing reply is locked.

        Live owns meaning first. After compose: model/soft-no waiver tokens, then
        shaped-field defer (size/qty/designs with no concrete number — not a phrase
        list). Finally, if live still re-asks an uncertainty turn with no waiver,
        settle the contract token so rewrite cannot re-prompt.

        Questions are not waivers. Closing the open field on an ask turn makes the
        next visitor message land on a later field than the question they just read.
        """
        if str(state.flags.get("turn_kind") or "") == "ask":
            return
        if self._continues_settled_field(state, visitor):
            # They are still talking about a field already stored. Do not write
            # that message onto the next open slot.
            return
        backup = self._backup_uncertainty_extract(state, visitor, accepted)
        if backup:
            backup_ok, backup_rejected = apply_field_updates(
                state, backup, visitor, registry=self.registry
            )
            accepted.update(backup_ok)
            rejected.update(backup_rejected)
            offer = str(state.flags.get("offer_options_for") or "").strip()
            if offer and is_field_waiver_value(str(backup_ok.get(offer) or "")):
                state.flags.pop("offer_options_for", None)
        for deferred in defer_unanswered_open_field(state, visitor, accepted):
            rejected.pop(deferred, None)
            offer = str(state.flags.get("offer_options_for") or "").strip()
            if offer == deferred:
                state.flags.pop("offer_options_for", None)

    def _settle_uncertainty_reask_gap(
        self,
        state: ConversationState,
        visitor: str,
        composed: Composed,
        accepted: dict[str, str],
        rejected: dict[str, str],
    ) -> str:
        """If live re-asked after a non-concrete uncertainty turn, force the waiver token."""
        asked = str(composed.asked or "").strip() or guards.asked_field(composed.reply)
        focus = str(state.last_question or "").strip()
        fix = uncertainty_reasked_without_settle(
            visitor=visitor,
            asked=asked,
            last_question=focus,
            fields=composed.fields,
            registry=self.registry,
            family=state.family(),
        )
        if not fix:
            return ""
        if focus in CATALOGUE_OPTION_FIELDS and needs_catalogue_options(
            state, visitor, accepted, registry=self.registry
        ):
            # They need a menu, not a silent waiver.
            return ""
        token = "no preference" if focus in {"style", "material"} else TO_BE_CONFIRMED
        waived_ok, waived_rejected = apply_field_updates(
            state,
            {focus: token},
            visitor,
            source="model",
            registry=self.registry,
        )
        accepted.update(waived_ok)
        rejected.update(waived_rejected)
        if focus in waived_ok:
            fields = dict(composed.fields or {})
            fields[focus] = token
            composed.fields = fields
        return fix

    def _intent_reask_fix(
        self,
        state: ConversationState,
        composed: Composed,
        visitor: str = "",
    ) -> str:
        """Catch drafts that re-ask after waiver, or re-ask without settling uncertainty."""
        asked = str(composed.asked or "").strip() or guards.asked_field(composed.reply)
        fix = waiver_fields_reasked(
            asked=asked,
            fields=composed.fields,
            last_question=str(state.last_question or ""),
        )
        if fix:
            return fix
        fix = settled_field_reasked(asked=asked, state=state)
        if fix:
            return fix
        if not visitor:
            return ""
        return uncertainty_reasked_without_settle(
            visitor=visitor,
            asked=asked,
            last_question=str(state.last_question or ""),
            fields=composed.fields,
            registry=self.registry,
            family=state.family(),
        )

    def _retarget_expected_if_focus_settled(
        self,
        state: ConversationState,
        expected: tuple[str, str] | None,
    ) -> tuple[str, str] | None:
        """After a waiver, polish toward the next ask — never the settled field again."""
        focus = str(state.last_question or "").strip()
        if not (
            focus
            and focus in state.fields
            and state.fields[focus].done
            and not (focus == "sizes" and state.size_needs_unit())
        ):
            return expected
        nxt = state.next_question()
        if nxt:
            return nxt
        # Quote checklist may be complete — do not keep polishing the waived ask.
        return None

    def _coerce_compose_finish_none(self, composed: Composed, state: ConversationState) -> None:
        """Catalogue finishes=none on the open finish ask → waiver token in compose fields."""
        focus = str(state.last_question or "").strip()
        if focus != "finishes" or not composed.fields:
            return
        raw = str(composed.fields.get("finishes") or "").strip()
        if is_finish_none_token(raw):
            composed.fields["finishes"] = TO_BE_CONFIRMED

    def _model_open_field_waiver(
        self, state: ConversationState, composed: Composed, visitor: str
    ) -> str:
        """Waiver the model committed to for the open field, in any visitor wording.

        The signal is the model's own token (fields, or the canonical waiver in
        the English draft). A real shaped answer stays an answer. A question
        with no waiver token stays open.
        """
        focus = str(state.last_question or "").strip()
        if not focus or focus not in UNCERTAIN_WAIVE_FIELDS:
            return ""
        if focus in state.fields and state.fields[focus].done and not (
            focus == "sizes" and state.size_needs_unit()
        ):
            return ""
        if field_shaped_attempt(
            focus, visitor, registry=self.registry, family=state.family()
        ):
            return ""
        token = str((composed.fields or {}).get(focus) or "").strip()
        if focus == "finishes" and is_finish_none_token(token):
            token = TO_BE_CONFIRMED
        # A concrete value in fields is an answer, not a waiver hiding in prose.
        if token and not is_field_waiver_value(token):
            return ""
        if is_field_waiver_value(token):
            if focus in {"style", "material"} and is_no_preference(token):
                return "no preference"
            return TO_BE_CONFIRMED if is_to_be_confirmed(token) else token
        reply = str(composed.reply or "").lower()
        still_on_focus = (
            str(composed.asked or "").strip() in {"", focus}
            or guards.asked_field(composed.reply) == focus
        )
        if not still_on_focus:
            return ""
        if TO_BE_CONFIRMED in reply:
            if focus in {"style", "material"}:
                return "no preference"
            return TO_BE_CONFIRMED
        if focus in {"style", "material"} and "no preference" in reply:
            return "no preference"
        return ""

    def _settle_compose_waivers(
        self,
        state: ConversationState,
        visitor: str,
        composed: Composed,
        accepted: dict[str, str],
        rejected: dict[str, str],
        expected: tuple[str, str] | None,
    ) -> tuple[str, str] | None:
        """Apply live's open-field token early (waiver OR concrete) before TBC backup.

        LLM-first: for design count / size / qty the model may map wording
        ("single" → 1) into fields.* — that number must land before
        defer_unanswered_open_field would waive the slot as to-be-confirmed.

        Ask turns still do not invent a concrete lock. They do keep a waiver
        the model already committed to, then the reply moves to the next field.
        """
        self._coerce_compose_finish_none(composed, state)
        focus = str(state.last_question or "").strip()
        if not focus or focus not in UNCERTAIN_WAIVE_FIELDS:
            return expected
        token = str((composed.fields or {}).get(focus) or "").strip()
        if focus == "finishes" and is_finish_none_token(token):
            token = TO_BE_CONFIRMED
        ask_turn = str(state.flags.get("turn_kind") or "") == "ask"
        if ask_turn:
            waiver = self._model_open_field_waiver(state, composed, visitor)
            if not waiver:
                return expected
            token = waiver
            fields = dict(composed.fields or {})
            fields[focus] = token
            composed.fields = fields
        elif not token:
            return expected
        if focus in accepted or state.fields[focus].done:
            # Still redirect the ask if the draft re-asks a field we already settled.
            pass
        else:
            settled_ok, settled_rejected = apply_field_updates(
                state,
                {focus: token},
                visitor,
                source="model",
                bases=composed.bases,
                registry=self.registry,
            )
            accepted.update(settled_ok)
            rejected.update(settled_rejected)
        asked = str(composed.asked or "").strip()
        if asked == focus or not asked:
            if state.fields[focus].done:
                nxt = state.next_question()
                if nxt:
                    composed.asked = nxt[0]
                    return nxt
            elif is_field_waiver_value(token):
                nxt = state.next_question()
                if nxt:
                    composed.asked = nxt[0]
                    return nxt
        if asked and asked != focus:
            question = state.question_for(asked) or (expected[1] if expected else "")
            return (asked, question)
        return expected

    def _expected_for_polish(
        self,
        state: ConversationState,
        expected: tuple[str, str] | None,
        composed: Composed,
    ) -> tuple[str, str] | None:
        """If the draft waived the open field and moved on, polish against that ask."""
        focus = str(state.last_question or "").strip()
        asked = str(composed.asked or "").strip()
        raw = str((composed.fields or {}).get(focus) or "")
        if focus == "finishes" and is_finish_none_token(raw):
            raw = TO_BE_CONFIRMED
        waived = is_field_waiver_value(raw)
        if focus and asked and asked != focus and waived:
            question = state.question_for(asked) or (expected[1] if expected else "")
            return (asked, question)
        return expected

    def _finish_reply(
        self,
        reply: str,
        visitor: str,
        expected: tuple[str, str] | None,
        *,
        already_greeted: bool = False,
        state: ConversationState | None = None,
    ) -> str:
        """Drop an unsolicited MOQ lecture, a repeated greeting, and any extra question."""
        priority_key = expected[0] if expected else ""
        priority_text = expected[1] if expected else ""
        visitor_greeted = is_visitor_greeting(visitor)
        locked = ()
        open_field = ""
        if state is not None:
            open_field = str(state.last_question or "").strip()
            # Settled = visitor, confirmed, or waived. Live drafts must not re-ask
            # a field the visitor deferred — polish redirects to the priority ask.
            locked = tuple(
                key
                for key, field_value in state.fields.items()
                if field_value.done
                and not (key == "sizes" and state.size_needs_unit())
                and key != priority_key
            )
            # Bare "nope" on size/qty must not keep a hallucinated email-refusal ack.
            if not contact_fields_refused(visitor, open_field):
                reply = guards.strip_misattributed_contact_refusal(reply, open_field)
        polished = guards.prepare_reply(
            reply,
            visitor,
            priority_key=priority_key,
            priority_text=priority_text,
            already_greeted=already_greeted and not visitor_greeted,
            locked_fields=locked,
            overrides=self.overrides,
        )
        if not polished and expected:
            polished = expected[1]
        elif not polished:
            polished = str(reply or "").strip()
        if visitor_greeted:
            ack = greeting_ack(visitor)
            if ack.lower() not in polished.lower():
                polished = f"{ack} {polished}".strip()
        return polished

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

    def handle(
        self,
        conversation_id: str,
        text: str,
        *,
        channel: str = "website",
        image: bytes | None = None,
        image_mime: str = "",
    ) -> TurnResult:
        started = time.perf_counter()
        spent_before = self.llm.spent_usd
        state = self.store.get_or_create(conversation_id)
        visitor = str(text or "").strip()
        image_bytes = image if image else None

        if not visitor and not image_bytes:
            return TurnResult(conversation_id=conversation_id, reply="", persona=state.persona)
        if not visitor and image_bytes:
            visitor = "[shared a reference image]"

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

        vision: VisionResult | None = None
        vision_accepted: dict[str, str] = {}
        attachment_id = ""
        state.flags.pop("reference_image_this_turn", None)
        if image_bytes:
            from .attachments import validate_image

            saved = None
            mime_for_vision = image_mime or "image/jpeg"
            try:
                saved = self.attachments.save(conversation_id, image_bytes, mime_for_vision)
                attachment_id = saved.id
                mime_for_vision = saved.mime
            except AttachmentError as error:
                # Blob/disk save must not kill vision — production quote still needs OCR.
                log.warning("Attachment save failed (%s); continuing with in-memory vision", error)
                state.flags["attachment_error"] = str(error)[:200]
                try:
                    mime_for_vision = validate_image(
                        image_bytes,
                        mime_for_vision,
                        max_bytes=self.config.attachment_max_bytes,
                    )
                except AttachmentError as validate_error:
                    log.warning("Reference image rejected (%s)", validate_error)
                    state.flags["attachment_error"] = str(validate_error)[:200]
                    mime_for_vision = ""
            if mime_for_vision:
                try:
                    focused = continue_ask(state) or (
                        (state.ask_set()[0], state.question_for(state.ask_set()[0]))
                        if state.ask_set()
                        else None
                    )
                    focus_field = focused[0] if focused else ""
                    focus_hint = focused[1] if focused else ""
                    catalogue_terms = self._vision_catalogue_terms(state, focus_field)
                    vision = analyze_image(
                        self.llm,
                        self.config,
                        image_bytes,
                        mime_for_vision,
                        focus_field=focus_field,
                        focus_hint=focus_hint,
                        family=state.family(),
                        catalogue_terms=catalogue_terms,
                    )
                    state.flags["reference_image"] = True
                    state.flags["reference_image_this_turn"] = True
                    state.flags["vision_focus_field"] = focus_field
                    if saved is not None:
                        self.attachments.set_vision(saved.id, vision.summary, vision.to_dict())
                        state.flags["last_attachment_id"] = saved.id
                        self.store.append_event(
                            conversation_id,
                            "attachment",
                            {
                                "attachment_id": saved.id,
                                "mime": saved.mime,
                                "size_bytes": saved.size_bytes,
                                "storage_backend": saved.storage_backend,
                                "vision": vision.to_dict(),
                                "focus_field": focus_field,
                            },
                        )
                except LLMError as error:
                    log.warning("Reference image vision failed (%s)", error)
                    state.flags["attachment_error"] = str(error)[:200]
                    vision = None

        # Fold OCR + structured vision fields into this turn so extract/traceable
        # treat readable quote details as the visitor's own words.
        if vision is not None:
            enrichment = vision.turn_enrichment()
            if enrichment and enrichment.lower() not in visitor.lower():
                visitor = f"{visitor} {enrichment}".strip() if visitor else enrichment

        # Keep the visitor's own words on the transcript; extract runs on English.
        raw_visitor = visitor
        state.add("visitor", raw_visitor)
        asked_before = state.last_question
        language, visitor = self._inbound_language(state, raw_visitor, started=started)
        # Inbound gloss must not turn a bare material token ("kraft") into a style
        # page name ("Textured Boxes") just because that offering lists the stock.
        if asked_before == "style" and is_material_only_pick(raw_visitor):
            if str(visitor or "").strip().casefold() != str(raw_visitor).strip().casefold():
                visitor = raw_visitor
                state.flags.pop("inbound_english", None)
                state.flags.pop("inbound_anglicised", None)
                if state.messages and state.messages[-1].author == "visitor":
                    state.messages[-1].english = ""

        was_reachable = state.reachable()
        # English/catalogue spelling once for this turn so topics + extract agree
        # ("adress" → "address" while quantity is open still answers location).
        from .spelling import prepare_visitor_text

        visitor, _catalogue_fuzzy = prepare_visitor_text(
            visitor,
            asked_before,
            family=state.family(),
            registry=self.registry,
        )
        route = classify_turn(state, visitor, registry=self.registry)
        state.flags["turn_kind"] = route.kind
        state.flags["turn_kind_reason"] = route.reason
        # ask/defer → live settles meaning before phrase extract locks fields.
        llm_first = route.kind in {"ask", "defer"} or self._llm_first_intent_turn(
            state, visitor
        )
        # Soft-decline closes a suggested field even in live — model fields are primary,
        # this is the safety net when the model leaves a bad suggested token (e.g. finish none).
        # Ask turns never treat the message as yes/no on a suggestion.
        confirmed = (
            []
            if route.kind == "ask"
            else state.confirm_suggested(visitor, soft_decline=True)
        )
        extracted = extract_fields(visitor, state.last_question, state, registry=self.registry)
        # Contact details must come from the visitor's raw words. Inbound LLM calls
        # mask emails to [EMAIL], so the English gloss can drop them — raw wins.
        contacts = extract_contact_fields(raw_visitor)
        extracted.update(contacts)
        if route.kind == "ask":
            # Questions must not settle checklist slots (e.g. "any other finish?").
            extracted = strip_checklist_locks(extracted)
            extracted.update(contacts)
        elif llm_first or route.kind == "defer":
            extracted = self._strip_early_uncertainty_extract(extracted)
        # Traceable checks need the raw contact spans and any English gloss together.
        trace_text = visitor
        if contacts and raw_visitor.strip() and raw_visitor.strip() not in visitor:
            trace_text = f"{visitor} {raw_visitor}".strip()
        elif contacts:
            trace_text = raw_visitor
        accepted, rejected = apply_field_updates(
            state, extracted, trace_text, registry=self.registry
        )
        for key in confirmed:
            accepted[key] = state.fields[key].value
        if vision is not None:
            # Structured vision fields fill gaps extract missed; visitor text already
            # includes OCR so quantity/size/email stay traceable as customer facts.
            focus_field = str(state.flags.get("vision_focus_field") or "")
            vision_updates = {
                key: value
                for key, value in vision.field_updates().items()
                if (
                    key not in accepted
                    # Structured vision use_case wins over a truncated OCR parse
                    # ("labels for coffee" vs "coffee pouches").
                    or (
                        key == "use_case"
                        and value
                        and str(accepted.get(key) or "").lower() != str(value).lower()
                    )
                )
                and (
                    key not in state.fields
                    or not state.fields[key].done
                    or state.fields[key].status == STATUS_SUGGESTED
                    or (
                        key == "use_case"
                        and value
                        and str(state.fields[key].value or "").lower() != str(value).lower()
                    )
                )
            }
            vision_updates = self._canonicalize_vision_updates(
                state, vision_updates, focus_field=focus_field
            )
            # Customer-only facts from the image are still the visitor's words (OCR).
            vision_ok, vision_rejected = apply_field_updates(
                state, vision_updates, visitor, source="model", registry=self.registry
            )
            vision_accepted.update(vision_ok)
            # Also surface values extract already accepted so the reply can cite them.
            for key in ("product", "use_case", "quantity", "sizes", "finishes", "email", "phone"):
                if key in accepted and key not in vision_accepted:
                    vision_accepted[key] = accepted[key]
            accepted.update(vision_ok)
            # Prefer the structured vision use_case when both fired.
            if "use_case" in vision_ok:
                accepted["use_case"] = vision_ok["use_case"]
            rejected.update(vision_rejected)
            if vision.summary:
                state.flags["reference_summary"] = vision.summary[:300]
            if vision.image_kind:
                state.flags["reference_image_kind"] = vision.image_kind
        # Size/qty/SKUs with no concrete answer → to be confirmed.
        # Style/material/finish with no concrete pick → flag options (any wording).
        # Image turns apply OCR/vision fields; do not waive the open ask just because
        # the placeholder message is not itself a size/qty answer.
        # Ask/defer: live owns meaning first — no phrase-waive before compose.
        if (
            not state.flags.get("reference_image_this_turn")
            and not llm_first
            and route.kind == "pick"
        ):
            for deferred in defer_unanswered_open_field(state, visitor, accepted):
                rejected.pop(deferred, None)
        offer_for = needs_catalogue_options(state, visitor, accepted, registry=self.registry)
        # Turn router: open catalogue ask → always list that field's options.
        menu_focus = catalogue_menu_focus(state, route)
        if menu_focus:
            offer_for = offer_for or menu_focus
            state.last_question = menu_focus
        # Alternatives ask while a material/style/finish is only suggested (or
        # was wrongly waived): clear it and force the catalogue menu.
        if (
            (is_option_request(visitor) or wants_recommendation(visitor) or route.kind == "ask")
            and re.search(r"\bmaterials?\b", visitor, re.I)
        ):
            material = state.fields["material"]
            if material.status == STATUS_SUGGESTED or (
                material.status == STATUS_WAIVED and material.value == "no preference"
            ):
                material.value = ""
                material.status = STATUS_UNKNOWN
                material.raw_visitor_text = ""
                material.basis = ""
            offer_for = offer_for or "material"
            state.last_question = "material"
        # Bare "suggest me" / "recommend something" while a catalogue field is open
        # must keep that field — do not burn attempts and jump to finish.
        if (
            not offer_for
            and (
                is_option_request(visitor)
                or wants_recommendation(visitor)
                or route.kind == "ask"
            )
            and asked_before in CATALOGUE_OPTION_FIELDS
            and not state.fields[asked_before].done
        ):
            offer_for = asked_before
            state.last_question = asked_before
        # Same-turn "suggest me styles" after product lands — do not soft-email first.
        if (
            not offer_for
            and state.fields["product"].done
            and not state.fields["style"].done
            and (
                re.search(r"\bstyles?\b", visitor, re.I)
                and (
                    is_option_request(visitor)
                    or wants_recommendation(visitor)
                    or route.kind == "ask"
                )
            )
        ):
            offer_for = "style"
            state.last_question = "style"
        if offer_for:
            state.flags["offer_options_for"] = offer_for
            # Keep the field askable while we are listing options.
            state.fields[offer_for].attempts = min(state.fields[offer_for].attempts, 1)
        else:
            state.flags.pop("offer_options_for", None)
        if "email" in accepted:
            # Volunteered or answered — soft early window is consumed.
            state.flags["soft_email_asked"] = True
        # Bad email while we asked for one → tell them and keep the field open.
        state.flags.pop("invalid_email", None)
        if (
            asked_before == "email"
            and "email" not in accepted
            and not refuses_contact(visitor)
            and looks_like_invalid_email(visitor)
        ):
            state.flags["invalid_email"] = True
            email_field = state.fields["email"]
            if email_field.value and not valid_email(email_field.value):
                email_field.value = ""
                email_field.raw_visitor_text = ""
                email_field.status = STATUS_UNKNOWN
                email_field.basis = ""
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
            and not needs_language_preference_ack(state, visitor)
            and not asks_to_share_reference(visitor)
            and not is_visitor_greeting(visitor)
            and len(visitor.split()) <= 8
        )
        # The open slot is already settled, or this message is still about a
        # settled slot. Neither one is a miss, and neither one declines the next ask.
        focus_now = str(state.last_question or "").strip()
        if unclear and (
            self._continues_settled_field(state, visitor)
            or (
                focus_now in state.fields
                and state.fields[focus_now].done
                and not (focus_now == "sizes" and state.size_needs_unit())
                and not any(key != focus_now for key in accepted)
            )
        ):
            unclear = False

        refused_contact = (
            not was_reachable
            and state.last_question in {"email", "phone", "name"}
            and refuses_contact(visitor)
        )
        # Soft early email: "no" skips and keeps quoting while blockers OR
        # style/material/finish/designs/extras are still open. Closing refuse
        # (checklist otherwise done) still declines contact and may hand off.
        soft_email_skip = (
            refused_contact
            and asked_before == "email"
            and (state.blocking_open() or state.product_details_open())
        )
        if soft_email_skip:
            state.flags["soft_email_asked"] = True
        elif refused_contact:
            state.fields["email"].attempts = max(state.fields["email"].attempts, 2)
            state.fields["phone"].attempts = max(state.fields["phone"].attempts, 2)

        if is_visitor_greeting(visitor):
            # "morning" is not a product. A menu the model stored, or two hellos,
            # must not empty the ask-set and hand the chat away.
            product = state.fields["product"]
            if product.value and family_of(product.value) == "unknown":
                product.value = ""
                product.raw_visitor_text = ""
                product.status = "unknown"
                product.attempts = min(product.attempts, 1)
            elif not product.done and product.attempts >= 2:
                product.attempts = 1

        expected = state.next_question()
        # Reference-share and image turns keep the question already on the table.
        if asks_to_share_reference(visitor) or vision is not None:
            expected = continue_ask(state) or expected
        # A suggested catalogue pick is not in ask_set — keep yes/no on that field.
        suggested_key = self._pending_suggestion(state)
        if suggested_key and not state.fields[suggested_key].done:
            state.last_question = suggested_key
            expected = (
                suggested_key,
                state.question_for(suggested_key)
                or f"Does {state.fields[suggested_key].value} work for you?",
            )
            llm_first = True
        # Catalogue-menu asks stay on that field even if attempts were already spent.
        offer_for = str(state.flags.get("offer_options_for") or "").strip()
        if offer_for in CATALOGUE_OPTION_FIELDS and not state.fields[offer_for].done:
            expected = (offer_for, state.question_for(offer_for) or (expected[1] if expected else ""))
            state.last_question = offer_for
        handoff_reason = self._handoff_reason(state, visitor, progressed=bool(accepted))
        # Declining *their* email is a waiver. Soft early skip keeps quoting.
        # Closing refuse can hand off; a refuse that also asks for OUR contact/
        # address must answer those facts first.
        asking_our_details = (
            canon.asks_for_our_contact(visitor)
            or canon.asks_for_location(visitor)
        )
        if soft_email_skip:
            handoff_reason = ""
        elif refused_contact and not asking_our_details and not canon.topics_to_answer(visitor):
            handoff_reason = "declined"
        elif refused_contact and asking_our_details and handoff_reason in {"quote", "declined"}:
            handoff_reason = ""
        # llm-first turns may still waive the open field after live/backup — do not
        # burn the chat on max_turns before that settlement runs.
        if handoff_reason == "max_turns" and llm_first:
            handoff_reason = ""
        if not expected and not handoff_reason and not state.complete():
            if is_visitor_greeting(visitor) or vision is not None:
                # Image turns must confirm what we saw — never stall into handoff.
                expected = ("product", state.question_for("product") or PRODUCT_QUESTION)
            elif state.family() == "unknown":
                # Hybrid: multi-family with no head noun → suggest + confirm.
                # Never stall while the product family is still open.
                expected = self._ambiguous_product_ask(state, visitor, accepted)
            else:
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
        vision_line = ""
        if vision is not None and not handoff_reason:
            vision_line = self._vision_reply(state, vision, vision_accepted, expected)
        # Propose-and-confirm: affirmation already settled the open suggestion —
        # continue from the next ask instead of letting live re-interpret "yes".
        confirm_follow = ""
        if (
            confirmed
            and not handoff_reason
            and not is_question(visitor)
            and not clarification
            and vision is None
        ):
            follow = (expected[1] if expected else "") or ""
            if not follow and expected:
                follow = state.question_for(expected[0]) or ""
            confirm_follow = f"Got it. {follow}".strip() if follow else "Got it."

        composed = Composed(reply="")
        source = "heuristic"
        if state.flags.get("invalid_email") and not handoff_reason:
            composed = Composed(
                reply=invalid_email_reply_for(state),
                asked="email",
                source="heuristic",
            )
            expected = ("email", EMAIL_QUESTION)
            source = "heuristic"
        elif clarification:
            composed = Composed(reply=clarification, source="heuristic")
            base = state.question_for(state.last_question)
            if base:
                expected = (state.last_question, base)
            # A clarification question is not a failed answer, so it should not
            # use up the two attempts that move the script past a field.
            field_value = state.fields.get(state.last_question)
            if field_value and not field_value.done:
                field_value.attempts = min(field_value.attempts, 1)
        elif vision_line:
            composed = Composed(reply=vision_line, source="vision")
            source = "vision"
            # Ask confirmation on the first suggested slot so yes/no can settle it.
            for key in ("style", "product", "finishes", "material"):
                if key in vision_accepted and state.fields[key].status == STATUS_SUGGESTED:
                    expected = (key, state.question_for(key) or vision_line)
                    break
        elif offslot:
            composed = Composed(reply=offslot, source="heuristic")
        elif confirm_follow:
            composed = Composed(
                reply=confirm_follow,
                asked=expected[0] if expected else "",
                source="heuristic",
            )
        elif needs_language_preference_ack(state, visitor) and not handoff_reason:
            # Deterministic yes + open field — avoid live drafts that fail meta guards.
            composed = heuristic_turn(
                state,
                visitor,
                expected,
                handoff_reason=handoff_reason,
                overrides=self.overrides,
                unclear=unclear,
            )
            source = "heuristic"
        elif (
            wants_recommendation(visitor)
            and state.last_question == "skus"
            and not handoff_reason
        ):
            # Designs suggestion: stable English guidance, then re-ask skus.
            composed = heuristic_turn(
                state,
                visitor,
                expected,
                handoff_reason=handoff_reason,
                overrides=self.overrides,
                unclear=unclear,
            )
            source = "heuristic"
        elif asks_term_meaning(visitor) and not handoff_reason:
            # Prefer live for a plain-language gloss; heuristic if live is off/fails.
            composed = Composed(reply="")
            source = "heuristic"
            if self.config.real_llm_enabled:
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
                    log.warning("Live meaning gloss failed (%s); using heuristic", error)
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
        elif (
            not handoff_reason
            and not asks_term_meaning(visitor)
            and str(state.flags.get("offer_options_for") or "").strip()
            in CATALOGUE_OPTION_FIELDS
            and (
                wants_recommendation(visitor)
                or is_option_request(visitor)
                or str(state.flags.get("turn_kind") or "") == "ask"
            )
        ):
            # Options / "any other finish?" asks → catalogue menu for the open field.
            # Deferrals without a menu ask still go to live to waive.
            composed = heuristic_turn(
                state,
                visitor,
                expected,
                handoff_reason=handoff_reason,
                overrides=self.overrides,
                unclear=unclear,
            )
            source = "heuristic"
        elif (
            not handoff_reason
            and not asks_term_meaning(visitor)
            and not is_question(visitor)
            and not wants_recommendation(visitor)
            and not is_option_request(visitor)
            and not llm_first
            and state.last_question in CATALOGUE_OPTION_FIELDS
            and len(visitor.split()) <= 8
            and field_shaped_attempt(
                state.last_question,
                visitor,
                registry=self.registry,
                family=state.family(),
            )
        ):
            # Clear style/material/finish pick → next ask. Live often emits a
            # full proposed_configs laundry list and fails reply_config_mismatch
            # / unknown_capability_unhedged on the draft (then rewrite).
            composed = heuristic_turn(
                state,
                visitor,
                expected,
                handoff_reason=handoff_reason,
                overrides=self.overrides,
                unclear=unclear,
            )
            source = "heuristic"
        elif (
            llm_first
            and self.config.real_llm_enabled
            and not handoff_reason
            and language.casefold() == ENGLISH.casefold()
        ):
            # Intent-first: deferral / soft-no / suggested yes-no → live fields,
            # not phrase regex or catalogue re-ask loops.
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
                log.warning("Live intent settle failed (%s); using heuristic", error)
                state.flags["llm_error"] = str(error)[:200]
                composed = Composed(reply="")
                source = "heuristic"
        elif soft_email_skip:
            # Soft-email "no" must continue the quote ask — never a live style dump.
            composed = heuristic_turn(
                state,
                visitor,
                expected,
                handoff_reason=handoff_reason,
                overrides=self.overrides,
                unclear=unclear,
            )
            source = "heuristic"
        elif (
            self.config.real_llm_enabled
            and not handoff_reason
            and language.casefold() != ENGLISH.casefold()
            and len(visitor.split()) <= 8
            and not is_question(visitor)
            and not wants_recommendation(visitor)
            and not is_option_request(visitor)
            and not asks_term_meaning(visitor)
        ):
            # Short catalogue answers in a non-English session: keep the turn on
            # heuristic so outbound translate still has a full language window
            # (live + rewrite was starving translate → English replies).
            composed = heuristic_turn(
                state,
                visitor,
                expected,
                handoff_reason=handoff_reason,
                overrides=self.overrides,
                unclear=unclear,
            )
            source = "heuristic"
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
            # Model did not return a draft (fake mode, call cap, or a failed call).
            # Settle the open deferral first so the scripted reply asks the next
            # field instead of saying it missed an answer it just stored.
            if str(state.flags.get("turn_kind") or "") != "ask" and (
                llm_first or route.kind == "defer"
            ):
                self._apply_uncertainty_backup(state, visitor, accepted, rejected)
                expected = self._retarget_expected_if_focus_settled(state, expected)
                focus_now = str(state.last_question or "").strip()
                if self._continues_settled_field(state, visitor) or (
                    focus_now in state.fields
                    and state.fields[focus_now].done
                    and not (focus_now == "sizes" and state.size_needs_unit())
                ):
                    unclear = False
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
        if source in {"live", "live-rewrite"}:
            expected = self._settle_compose_waivers(
                state, visitor, composed, accepted, rejected, expected
            )
            # Backup before guard/judge: soft decline live left open must be settled
            # in state first, so re-asking that field is a contract miss (not a late
            # panel-only waiver after the bad reply is locked).
            self._apply_uncertainty_backup(state, visitor, accepted, rejected)
            if str(state.flags.get("turn_kind") or "") != "ask":
                self._settle_uncertainty_reask_gap(
                    state, visitor, composed, accepted, rejected
                )
            else:
                # Ask turns never lock checklist fields from the draft.
                if composed.fields:
                    composed.fields = strip_checklist_locks(composed.fields)
            # Polish / rewrite toward the next ask (or none); keep composed.asked
            # so intent_fix still sees a draft re-asking the settled field.
            expected = self._retarget_expected_if_focus_settled(state, expected)
        polish_expected = self._expected_for_polish(state, expected, composed)
        composed.reply = self._finish_reply(
            composed.reply,
            visitor,
            polish_expected,
            already_greeted=already_greeted,
            state=state,
        )
        result = self._guard(
            composed.reply,
            state,
            visitor,
            prompt_chunks,
            polish_expected,
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
        # Deterministic: waived in compose fields, or already settled in state, but re-asked.
        intent_fix = ""
        if source == "live":
            intent_fix = self._intent_reask_fix(state, composed, visitor)
        # LLM intent judge — only when hard guards already passed and fields look
        # consistent. Fail open on timeout/error so a judge blip never stalls chat.
        judge_fix = ""
        if (
            source == "live"
            and result.ok
            and not recommendation_gap
            and not intent_fix
            and self.config.real_llm_enabled
            and language.casefold() == ENGLISH.casefold()
        ):
            try:
                verdict = judge_reply(
                    self.llm,
                    visitor=visitor,
                    reply=composed.reply,
                    open_field=str(state.last_question or ""),
                    asked=str(composed.asked or ""),
                    fields=composed.fields,
                    ms_left=self._language_ms_left(started),
                )
                if not verdict.ok:
                    judge_fix = verdict.reason
            except LLMError as error:
                log.warning("Reply judge failed (%s); keeping draft", error)

        needs_intent_rewrite = bool(intent_fix or judge_fix)
        if source == "live" and (not result.ok or recommendation_gap or needs_intent_rewrite):
            rejected_drafts.append(self._draft_record("draft", composed, result))
        # Meaning glosses: skip rewrite spam; heuristic explains without locking the term.
        if (
            source == "live"
            and (not result.ok or recommendation_gap or needs_intent_rewrite)
            and asks_term_meaning(visitor)
        ):
            composed = heuristic_turn(
                state,
                visitor,
                expected,
                handoff_reason=handoff_reason,
                overrides=self.overrides,
                unclear=unclear,
            )
            composed.source = "fallback"
            polish_expected = self._expected_for_polish(state, expected, composed)
            composed.reply = self._finish_reply(
                composed.reply,
                visitor,
                polish_expected,
                already_greeted=already_greeted,
                state=state,
            )
            result = self._guard(
                composed.reply,
                state,
                visitor,
                prompt_chunks,
                polish_expected,
                bool(handoff_reason),
                composed.proposed_configs,
            )
            source = "fallback"
            if result.ok:
                blocked = []
        elif (
            (not result.ok or recommendation_gap or needs_intent_rewrite)
            and source == "live"
            and language.casefold() != ENGLISH.casefold()
        ):
            # Non-English: skip paid rewrite so outbound translate still runs.
            # Heuristic fallback is applied below when result stays blocked.
            pass
        elif (not result.ok or recommendation_gap or needs_intent_rewrite) and source == "live":
            fixes = result.blockers or [
                issue for issue in result.warnings if issue.code == "recommendation_unanswered"
            ]
            correction = merge_corrections(
                guards.describe(fixes) if fixes else "",
                intent_fix,
                judge_fix,
            )
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
                expected = self._settle_compose_waivers(
                    state, visitor, rewritten, accepted, rejected, expected
                )
                self._apply_uncertainty_backup(state, visitor, accepted, rejected)
                if str(state.flags.get("turn_kind") or "") != "ask":
                    self._settle_uncertainty_reask_gap(
                        state, visitor, rewritten, accepted, rejected
                    )
                else:
                    if rewritten.fields:
                        rewritten.fields = strip_checklist_locks(rewritten.fields)
                expected = self._retarget_expected_if_focus_settled(state, expected)
                polish_expected = self._expected_for_polish(state, expected, rewritten)
                rewritten.reply = self._finish_reply(
                    rewritten.reply,
                    visitor,
                    polish_expected,
                    already_greeted=already_greeted,
                    state=state,
                )
                # A rewrite is reconciled again. Fixing a price and quietly adding
                # an option the new configs do not name still blocks.
                rewritten_result = self._guard(
                    rewritten.reply,
                    state,
                    visitor,
                    prompt_chunks,
                    polish_expected,
                    bool(handoff_reason),
                    rewritten.proposed_configs,
                )
                rewritten_gap = any(
                    issue.code == "recommendation_unanswered"
                    for issue in rewritten_result.warnings
                )
                rewritten_intent = self._intent_reask_fix(state, rewritten, visitor)
                if (
                    rewritten.reply
                    and rewritten_result.ok
                    and not rewritten_gap
                    and not rewritten_intent
                ):
                    composed = rewritten
                    result = rewritten_result
                    source = "live-rewrite"
                    blocked = []
                elif rewritten.reply:
                    rejected_drafts.append(self._draft_record("rewrite", rewritten, rewritten_result))
            except LLMError as error:
                log.warning("Live rewrite failed (%s); continuing with fallback", error)

        if not result.ok and state.flags.get("invalid_email"):
            # Keep correcting the address; do not fall through to phone / generic ask.
            composed = Composed(
                reply=invalid_email_reply_for(state),
                asked="email",
                source="heuristic",
            )
            composed.reply = self._finish_reply(
                composed.reply, visitor, expected, already_greeted=already_greeted, state=state
            )
            result = self._guard(
                composed.reply, state, visitor, prompt_chunks, expected, bool(handoff_reason)
            )
            source = "heuristic"
            if result.ok:
                blocked = []

        if not result.ok:
            offer = str(state.flags.get("offer_options_for") or "").strip()
            visitor_ask = self._visitor_needs_direct_answer(state, visitor)
            if (
                offer in CATALOGUE_OPTION_FIELDS
                or is_option_request(visitor)
                or wants_recommendation(visitor)
                or visitor_ask
            ):
                # Keep heuristic fields (e.g. suggested standard material) so a
                # following "yes" can confirm via propose-and-confirm.
                # Visitor questions always take the answer-first heuristic path —
                # never the unattested "X is noted" shortcut.
                composed = heuristic_turn(
                    state,
                    visitor,
                    expected,
                    handoff_reason=handoff_reason,
                    overrides=self.overrides,
                    unclear=unclear,
                )
                composed.source = "fallback"
                composed.reply = self._finish_reply(
                    composed.reply,
                    visitor,
                    expected,
                    already_greeted=already_greeted,
                    state=state,
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
                if result.blockers and not offer:
                    # Size-help heuristic already explains custom sizing — never replace it
                    # with the bare "what size are you looking for?" script line.
                    keep_size_help = asks_size_guidance(
                        visitor, state.last_question
                    ) and re.search(r"\bno standard size\b", composed.reply, re.I)
                    if keep_size_help:
                        result = guards.GuardResult()
                        blocked = []
                    else:
                        fallback = self._finish_reply(
                            expected[1] if expected else (HANDOFF_LINES.get(handoff_reason) or ""),
                            visitor,
                            expected,
                            already_greeted=already_greeted,
                            state=state,
                        )
                        composed = Composed(reply=fallback, source="fallback")
                        result = self._guard(
                            fallback, state, visitor, prompt_chunks, expected, bool(handoff_reason)
                        )
                source = "fallback"
            else:
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
                    state=state,
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
                        state=state,
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
            # echo cannot overwrite an answer already on file. Waived / settled
            # values (e.g. SKUs → to be confirmed) must not be rewritten.
            if str(state.flags.get("turn_kind") or "") == "ask":
                composed.fields = strip_checklist_locks(composed.fields)
            focus = str(composed.asked or "").strip()
            if not focus and expected:
                focus = expected[0]
            llm_fields = {
                key: value
                for key, value in composed.fields.items()
                if key not in accepted
                and not (key in state.fields and state.fields[key].done)
                and (
                    key not in state.fields
                    or not state.fields[key].stated
                    or key == state.last_question
                )
            }
            # Never silently lock style/material/finish from a catalogue echo while
            # the visitor is answering a different field (qty "300", SKUs "not sure").
            for key in list(llm_fields):
                if key not in CATALOGUE_OPTION_FIELDS:
                    continue
                if field_shaped_attempt(
                    key, visitor, registry=self.registry, family=state.family()
                ):
                    continue
                if key == focus or key == state.last_question:
                    continue
                llm_fields.pop(key, None)
            llm_accepted, llm_rejected = apply_field_updates(
                state,
                llm_fields,
                visitor,
                source="model",
                bases=composed.bases,
                registry=self.registry,
            )
            accepted.update(llm_accepted)
            rejected.update(llm_rejected)
            # Model waived a catalogue field — stop forcing the options menu.
            offer = str(state.flags.get("offer_options_for") or "").strip()
            if offer and is_field_waiver_value(str(llm_accepted.get(offer) or "")):
                state.flags.pop("offer_options_for", None)

        # Late backup is a no-op when early settle already closed the field.
        if llm_first or source in {"live", "live-rewrite"}:
            self._apply_uncertainty_backup(state, visitor, accepted, rejected)

        # Re-check turn cap after live/backup settlement (deferred above for llm-first).
        if not state.handoff:
            late_handoff = self._handoff_reason(
                state, visitor, progressed=bool(accepted)
            )
            if late_handoff == "max_turns":
                state.handoff = late_handoff
                reply = HANDOFF_LINES.get(late_handoff, HANDOFF_LINES["stalled"])
                composed.reply = reply
                composed.asked = ""
                composed.move = "handoff"

        reply_asked = guards.asked_field(reply)
        asked = reply_asked
        asking = guards.count_questions(reply) > 0
        if not asked and asking and expected:
            asked = expected[0]
        if state.flags.get("invalid_email"):
            asked = "email"
        # If the sentence still asks a settled field, the visitor's next message
        # answers that sentence. Only move on when the reply itself moved on.
        if (
            asked
            and asked in state.fields
            and state.fields[asked].done
            and not (asked == "sizes" and state.size_needs_unit())
            and reply_asked != asked
        ):
            nxt = state.next_question()
            asked = nxt[0] if nxt else ""
        if asked:
            state.last_question = asked
            if asked == "email":
                # Soft early ask is one-shot whether they answer, skip, or refuse.
                state.flags["soft_email_asked"] = True
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
            elif (
                asked == "sizes"
                and UNIT_ONLY_RE.match(visitor)
                and not state.fields["sizes"].value
            ):
                # Visitor named a unit ("feet") while size is open — next ask gets
                # the dimension prompt; do not spend an attempt on the unit alone.
                pass
            elif state.flags.get("invalid_email"):
                # A bad address is a correction turn, not a failed email ask.
                pass
            elif state.flags.get("offer_options_for"):
                # Listing catalogue options is not a failed answer — keep the field open.
                if field_value and not field_value.done:
                    field_value.attempts = min(field_value.attempts, 1)
            elif field_value and not field_value.done and not is_visitor_greeting(visitor):
                field_value.attempts += 1
        else:
            state.last_question = ""

        if re.search(r"\b(?:moq|minimum)\b", reply, re.I):
            state.flags["minimum_stated"] = True
        if re.search(r"\bno standard size\b|\bmade to fit\b", reply, re.I):
            state.flags["size_no_standard_explained"] = True

        # Transcript stays English for guards/extract; visitor sees the translation.
        english = reply
        language = session_language(state.flags)
        shown = self._outbound_language(state, english, language=language, started=started)
        state.add("ai", english, shown=shown if shown != english else "")
        state.flags["language"] = language
        if shown != english:
            state.flags["translated"] = True
        self.store.save(state)
        self.store.append_event(
            conversation_id,
            "turn",
            {
                "channel": channel,
                "visitor": visitor,
                "reply": shown,
                "reply_english": english if shown != english else "",
                "language": language,
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
                "attachment_id": attachment_id,
                "vision": vision.to_dict() if vision is not None else None,
            },
        )
        sent_configs = composed.proposed_configs or []
        return TurnResult(
            conversation_id=conversation_id,
            reply=shown,
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
            language=language,
            reply_english=english if shown != english else "",
        )

    def _language_ms_left(self, started: float) -> float:
        budget_s = turn_language_budget_s(self.config.timeout_s)
        # Never starve outbound below one language call when compose ran long.
        return max(
            LANGUAGE_S * 1000,
            (started + max(budget_s, SEND_BY_S) - time.perf_counter()) * 1000,
        )

    def _inbound_language(
        self,
        state: ConversationState,
        raw_visitor: str,
        *,
        started: float,
    ) -> tuple[str, str]:
        """Detect language + English gloss via LLM. Returns (language, text_for_extract)."""
        language = session_language(state.flags)
        state.flags.pop("inbound_language_skipped", None)
        state.flags.pop("inbound_gloss_failed", None)
        state.flags.pop("inbound_anglicised", None)
        state.flags.pop("translate_skipped", None)
        if not self.config.real_llm_enabled:
            # Fake/live-off still needs ¿Hablas…? → language sticky for tests + offline.
            glossed = heuristic_language_preference_gloss(raw_visitor)
            if glossed:
                language, english = glossed
                state.flags["language"] = language
                state.flags["inbound_english"] = english[:200]
                state.flags["inbound_anglicised"] = True
                if state.messages:
                    state.messages[-1].english = english
                return language, english
            state.flags.setdefault("language", language)
            return language, raw_visitor
        recent = [
            message.text
            for message in state.messages[:-1]
            if message.author == "visitor" and message.text.strip()
        ]
        open_field = str(state.last_question or "").strip()
        catalogue_terms: list[str] = []
        if open_field in CATALOGUE_OPTION_FIELDS:
            slot = "finish" if open_field == "finishes" else open_field
            family = state.family()
            if family and family != "unknown":
                catalogue_terms = list(self.registry.values(family, slot))
            else:
                for fam in self.registry.families:
                    catalogue_terms.extend(self.registry.values(fam, slot))
        inbound = normalize_inbound(
            self.llm,
            raw_visitor,
            prior_language=language,
            recent_visitor=recent,
            open_field=open_field,
            catalogue_terms=catalogue_terms,
            ms_left=self._language_ms_left(started),
        )
        if inbound is None:
            # ¿Hablas español? must still hit language-ack when the gloss LLM fails.
            glossed = heuristic_language_preference_gloss(raw_visitor)
            if glossed:
                language, english = glossed
                state.flags["language"] = language
                state.flags["inbound_english"] = english[:200]
                state.flags["inbound_language_skipped"] = "timeout_or_error"
                state.flags["inbound_anglicised"] = True
                state.messages[-1].english = english
                return language, english
            state.flags["inbound_language_skipped"] = "timeout_or_error"
            state.flags["language"] = language
            return language, raw_visitor
        language = inbound.language or language
        english = inbound.english or raw_visitor
        # Mid-chat "please speak Spanish" must re-stick the session language even
        # after the first language-preference yes was already sent.
        named = language_named_in_preference_ask(english) or language_named_in_preference_ask(
            raw_visitor
        )
        if named:
            language = named
        # Raw language chip with a bad gloss → force the English ack path.
        if asks_language_preference(raw_visitor) and not asks_language_preference(english):
            glossed = heuristic_language_preference_gloss(raw_visitor)
            if glossed:
                language, english = glossed[0] or language, glossed[1]
        state.flags["language"] = language
        state.flags["inbound_english"] = english[:200]
        if english.strip().casefold() != raw_visitor.strip().casefold():
            state.messages[-1].english = english
            state.flags["inbound_anglicised"] = True
        elif language.strip().casefold() != ENGLISH.casefold():
            # Same spelling already usable in English (loanwords like "pizza", emails).
            # Only flag a real gloss miss when the raw still looks non-English.
            if re.search(r"[^\x00-\x7F]", raw_visitor) or not re.fullmatch(
                r"[A-Za-z0-9][A-Za-z0-9\s.,'\-+@]*",
                raw_visitor.strip(),
            ):
                state.flags["inbound_anglicised"] = False
                state.flags["inbound_gloss_failed"] = True
        return language, english

    def _outbound_language(
        self,
        state: ConversationState,
        english: str,
        *,
        language: str,
        started: float,
    ) -> str:
        """Translate the English reply into the session language on the way out.

        Returns visitor-facing text. On timeout or fake mode the English goes out.
        """
        if language == ENGLISH or not str(english or "").strip():
            return english
        if not self.config.real_llm_enabled:
            state.flags["translate_skipped"] = "fake_mode"
            return english
        # Always allow a full language-call window so the first non-English turn
        # still translates after a slow compose (cajas → English reply bug).
        ms_left = max(LANGUAGE_S * 1000, self._language_ms_left(started))
        samples = [
            message.text
            for message in state.messages
            if message.author == "visitor" and message.text.strip()
        ]
        translated = translate_outbound(
            [english],
            language=language,
            client=self.llm,
            visitor_samples=samples,
            ms_left=ms_left,
        )
        if not translated or not translated[0].strip():
            log.info(
                "%s: translation not ready in time, sending English",
                state.id,
            )
            state.flags["translate_skipped"] = "timeout_or_error"
            return english
        state.flags.pop("translate_skipped", None)
        return translated[0]

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
