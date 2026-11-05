"""Turn router: ask / defer / pick before checklist mutation."""

from __future__ import annotations

from dataclasses import replace

from chatbot.bot.composer import Composed
from chatbot.bot.orchestrator import Orchestrator
from chatbot.bot.reply_judge import JudgeVerdict
from chatbot.bot.state import (
    STATUS_SUGGESTED,
    STATUS_VISITOR,
    STATUS_WAIVED,
    TO_BE_CONFIRMED,
    is_option_request,
)
from chatbot.bot.turn_router import classify_turn, strip_checklist_locks


def _engine(config, kb_index, tmp_path, name: str) -> Orchestrator:
    live_config = replace(config, mode="live", allow_live=True, api_key="test-key")
    return Orchestrator(
        live_config,
        store_path=tmp_path / f"{name}.sqlite3",
        index=kb_index,
        examples=[],
    )


def _mute_side_llms(monkeypatch) -> None:
    monkeypatch.setattr(
        "chatbot.bot.orchestrator.normalize_inbound",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        "chatbot.bot.orchestrator.judge_reply",
        lambda *args, **kwargs: JudgeVerdict(ok=True),
    )


def test_classify_other_finish_question_is_ask(config, kb_index, tmp_path):
    engine = _engine(config, kb_index, tmp_path, "route-ask")
    try:
        state = engine.store.get_or_create("c-ask")
        state.set_field("product", "boxes", status=STATUS_VISITOR)
        state.last_question = "finishes"
        route = classify_turn(state, "do you have any other finish?", registry=engine.registry)
        assert route.kind == "ask"
        assert is_option_request("do you have any other finish?")
    finally:
        engine.close()


def test_classify_nah_on_material_is_defer(config, kb_index, tmp_path):
    engine = _engine(config, kb_index, tmp_path, "route-defer")
    try:
        state = engine.store.get_or_create("c-defer")
        state.set_field("product", "boxes", status=STATUS_VISITOR)
        state.last_question = "material"
        assert classify_turn(state, "nah", registry=engine.registry).kind == "defer"
    finally:
        engine.close()


def test_classify_mailer_on_style_is_pick(config, kb_index, tmp_path):
    engine = _engine(config, kb_index, tmp_path, "route-pick")
    try:
        state = engine.store.get_or_create("c-pick")
        state.set_field("product", "boxes", status=STATUS_VISITOR)
        state.last_question = "style"
        assert classify_turn(state, "mailer box", registry=engine.registry).kind == "pick"
    finally:
        engine.close()


def test_classify_bare_name_is_pick(config, kb_index, tmp_path):
    engine = _engine(config, kb_index, tmp_path, "route-name")
    try:
        state = engine.store.get_or_create("c-name")
        state.set_field("product", "boxes", status=STATUS_VISITOR)
        state.last_question = "name"
        assert classify_turn(state, "bilal", registry=engine.registry).kind == "pick"
    finally:
        engine.close()


def test_live_maps_single_to_design_count_before_tbc_backup(
    config, kb_index, tmp_path, monkeypatch
):
    """LLM-first: 'single' is not a digit — live fields.skus=1 must beat TBC defer."""
    engine = _engine(config, kb_index, tmp_path, "skus-single")
    _mute_side_llms(monkeypatch)
    try:
        state = engine.store.get_or_create("c-skus-single")
        state.set_field("product", "bags", status=STATUS_VISITOR)
        state.set_field("use_case", "coffee", status=STATUS_VISITOR)
        state.set_field("sizes", TO_BE_CONFIRMED, status=STATUS_WAIVED)
        state.set_field("quantity", "3000", status=STATUS_VISITOR)
        state.set_field("style", "Mylar Bags", status=STATUS_VISITOR)
        state.set_field("material", "mylar", status=STATUS_VISITOR)
        state.set_field("finishes", TO_BE_CONFIRMED, status=STATUS_WAIVED)
        state.flags["soft_email_asked"] = True
        state.last_question = "skus"
        engine.store.save(state)

        monkeypatch.setattr(
            "chatbot.bot.orchestrator.live_turn",
            lambda *args, **kwargs: Composed(
                reply="Got it — one design. Any extras like a zipper or tear notch?",
                asked="extras",
                fields={"skus": "1"},
                source="live",
            ),
        )
        result = engine.handle("c-skus-single", "single")
        state = engine.store.get_or_create("c-skus-single")
        # Short non-digit → defer path; live still owns the number.
        assert state.flags.get("turn_kind") == "defer"
        assert str(state.fields["skus"].value or "") == "1"
        assert state.fields["skus"].status in {STATUS_VISITOR, STATUS_SUGGESTED}
        assert result.accepted.get("skus") == "1"
        assert TO_BE_CONFIRMED not in str(state.fields["skus"].value or "").lower()
    finally:
        engine.close()


def test_bare_name_locks_without_spellcheck_mangle(
    config, kb_index, tmp_path, monkeypatch
):
    engine = _engine(config, kb_index, tmp_path, "name-lock")
    _mute_side_llms(monkeypatch)
    try:
        state = engine.store.get_or_create("c-name-lock")
        state.set_field("product", "boxes", status=STATUS_VISITOR)
        state.set_field("use_case", "food", status=STATUS_VISITOR)
        state.set_field("sizes", TO_BE_CONFIRMED, status=STATUS_WAIVED)
        state.set_field("quantity", "5000", status=STATUS_VISITOR)
        state.set_field("style", "Tuck Boxes", status=STATUS_VISITOR)
        state.set_field("material", "no preference", status=STATUS_WAIVED)
        state.set_field("finishes", TO_BE_CONFIRMED, status=STATUS_WAIVED)
        state.set_field("skus", TO_BE_CONFIRMED, status=STATUS_WAIVED)
        state.set_field("email", "bilal@gmail.com", status=STATUS_VISITOR)
        state.flags["soft_email_asked"] = True
        state.last_question = "name"
        engine.store.save(state)

        monkeypatch.setattr(
            "chatbot.bot.orchestrator.live_turn",
            lambda *args, **kwargs: Composed(
                reply="Thanks Bilal — the team will email your quote.",
                asked="",
                fields={"name": "bilal"},
                source="live",
            ),
        )
        result = engine.handle("c-name-lock", "bilal")
        state = engine.store.get_or_create("c-name-lock")
        assert state.flags.get("turn_kind") == "pick"
        assert str(state.fields["name"].value or "").lower() == "bilal"
        assert state.fields["name"].status == STATUS_VISITOR
        assert result.accepted.get("name", "").lower() == "bilal"
    finally:
        engine.close()


def test_strip_checklist_locks_keeps_email():
    assert strip_checklist_locks(
        {"finishes": "matte", "email": "a@b.com", "quantity": "10"}
    ) == {"email": "a@b.com"}


def test_other_finish_ask_does_not_lock_matte(config, kb_index, tmp_path, monkeypatch):
    engine = _engine(config, kb_index, tmp_path, "finish-ask")
    _mute_side_llms(monkeypatch)
    try:
        state = engine.store.get_or_create("c-finish-ask")
        state.set_field("product", "boxes", status=STATUS_VISITOR)
        state.set_field("use_case", "pizza", status=STATUS_VISITOR)
        state.set_field("sizes", TO_BE_CONFIRMED, status=STATUS_WAIVED)
        state.set_field("quantity", "3210", status=STATUS_VISITOR)
        state.set_field("style", "Mailer Boxes", status=STATUS_VISITOR)
        state.set_field("material", "no preference", status=STATUS_WAIVED)
        state.set_field("email", "bilal@gmail.com", status=STATUS_VISITOR)
        state.flags["soft_email_asked"] = True
        state.last_question = "finishes"
        engine.store.save(state)

        monkeypatch.setattr(
            "chatbot.bot.orchestrator.live_turn",
            lambda *args, **kwargs: Composed(
                reply=(
                    "Got it — matte lamination works. How many total designs do you have?"
                ),
                asked="skus",
                fields={"finishes": "matte lamination"},
                source="live",
            ),
        )
        result = engine.handle("c-finish-ask", "do you have any other finish?")
        state = engine.store.get_or_create("c-finish-ask")
        assert state.flags.get("turn_kind") == "ask"
        assert not state.fields["finishes"].done
        assert "matte" not in str(state.fields["finishes"].value or "").lower()
        lower = result.reply.lower()
        # Must address finishes / options — not jump past with a silent matte lock.
        assert "design" not in lower or "finish" in lower or "lamination" in lower
        assert state.last_question == "finishes" or "finish" in lower
    finally:
        engine.close()


def test_nah_still_waives_material(config, kb_index, tmp_path, monkeypatch):
    engine = _engine(config, kb_index, tmp_path, "nah-mat")
    _mute_side_llms(monkeypatch)
    try:
        state = engine.store.get_or_create("c-nah-mat")
        state.set_field("product", "boxes", status=STATUS_VISITOR)
        state.set_field("use_case", "pizza", status=STATUS_VISITOR)
        state.set_field("sizes", TO_BE_CONFIRMED, status=STATUS_WAIVED)
        state.set_field("quantity", "500", status=STATUS_VISITOR)
        state.set_field("style", "mailer", status=STATUS_VISITOR)
        state.flags["soft_email_asked"] = True
        state.last_question = "material"
        engine.store.save(state)

        monkeypatch.setattr(
            "chatbot.bot.orchestrator.live_turn",
            lambda *args, **kwargs: Composed(
                reply="No problem — no material preference. What finish do you prefer?",
                asked="finishes",
                fields={"material": "no preference"},
                source="live",
            ),
        )
        result = engine.handle("c-nah-mat", "nah")
        state = engine.store.get_or_create("c-nah-mat")
        assert state.flags.get("turn_kind") == "defer"
        assert state.fields["material"].status == STATUS_WAIVED
        assert "material" not in state.ask_set()
        assert "special features" not in result.reply.lower()
    finally:
        engine.close()
