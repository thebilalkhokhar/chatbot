from __future__ import annotations

import base64

from fastapi.testclient import TestClient

from chatbot.bot.attachments import AttachmentError, LocalObjectStore, open_attachment_store
from chatbot.bot.service import create_app
from chatbot.bot.state import ConversationState, STATUS_SUGGESTED
from chatbot.bot.vision import VisionResult, fake_vision_result

# 1x1 PNG
PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


def test_local_object_store_round_trip(tmp_path):
    store = LocalObjectStore(tmp_path / "uploads")
    url = store.put("attachments/demo/a.png", PNG_1X1, "image/png")
    assert url.startswith("file:")
    assert store.get("attachments/demo/a.png") == PNG_1X1


def test_attachment_store_persists_metadata_and_bytes(tmp_path):
    repo = open_attachment_store(data_dir=tmp_path / "data")
    try:
        saved = repo.save("conv-1", PNG_1X1, "image/png")
        repo.set_vision(saved.id, "a box mockup", {"summary": "a box mockup", "family": "boxes"})
        loaded = repo.get(saved.id)
        assert loaded is not None
        assert loaded.conversation_id == "conv-1"
        assert loaded.mime == "image/png"
        assert loaded.vision_summary == "a box mockup"
        assert loaded.vision["family"] == "boxes"
        assert repo.read_bytes(loaded) == PNG_1X1
        assert [item.id for item in repo.list_for("conv-1")] == [saved.id]
    finally:
        repo.close()


def test_attachment_store_rejects_bad_bytes(tmp_path):
    repo = open_attachment_store(data_dir=tmp_path / "data")
    try:
        try:
            repo.save("conv-1", b"not-an-image", "image/png")
            assert False, "expected AttachmentError"
        except AttachmentError:
            pass
    finally:
        repo.close()


def test_fake_vision_result_has_summary():
    result = fake_vision_result()
    assert result.summary
    assert result.source == "fake"
    assert result.field_updates() == {}


def test_local_chat_accepts_reference_image(config, orchestrator):
    client = TestClient(create_app(config, orchestrator))
    started = client.post("/api/start", json={"conversation_id": "img-1"})
    assert started.status_code == 200

    response = client.post(
        "/api/chat",
        json={
            "conversation_id": "img-1",
            "text": "",
            "image_base64": base64.b64encode(PNG_1X1).decode("ascii"),
            "image_mime": "image/png",
        },
    )
    assert response.status_code == 200
    turn = response.json()
    assert turn["source"] == "vision"
    assert "reference" in turn["reply"].lower()
    assert turn["flags"].get("reference_image") is True

    stored = orchestrator.attachments.list_for("img-1")
    assert len(stored) == 1
    assert stored[0].mime == "image/png"
    assert stored[0].vision_summary
    assert orchestrator.attachments.read_bytes(stored[0]) == PNG_1X1


def test_local_chat_rejects_non_image_payload(config, orchestrator):
    client = TestClient(create_app(config, orchestrator))
    client.post("/api/start", json={"conversation_id": "img-2"})
    response = client.post(
        "/api/chat",
        json={
            "conversation_id": "img-2",
            "text": "hi",
            "image_base64": base64.b64encode(b"hello").decode("ascii"),
            "image_mime": "image/png",
        },
    )
    assert response.status_code == 200
    # Decoder accepts mime, orchestrator rejects magic bytes and continues as text.
    assert response.json()["reply"]


def test_print_product_label_resolves_family():
    state = ConversationState(id="x", persona="Max Carter")
    state.set_field("product", "print", status=STATUS_SUGGESTED)
    assert state.family() == "print"
    state.set_field("product", "print products", status=STATUS_SUGGESTED)
    assert state.family() == "print"
    assert state.ask_set()


def test_vision_print_suggestion_does_not_handoff(config, orchestrator, monkeypatch):
    def fake_analyze(client, cfg, data, mime):
        return VisionResult(
            summary="A cricket match poster graphic.",
            family="print",
            source="live",
        )

    monkeypatch.setattr("chatbot.bot.orchestrator.analyze_image", fake_analyze)
    client = TestClient(create_app(config, orchestrator))
    client.post("/api/start", json={"conversation_id": "img-print"})
    response = client.post(
        "/api/chat",
        json={
            "conversation_id": "img-print",
            "text": "",
            "image_base64": base64.b64encode(PNG_1X1).decode("ascii"),
            "image_mime": "image/png",
        },
    )
    assert response.status_code == 200
    turn = response.json()
    assert not turn["handoff"]
    assert turn["source"] == "vision"
    assert "specialist" not in turn["reply"].lower()
    assert "for product" not in turn["reply"].lower()
    assert "are you looking for print products" in turn["reply"].lower()
    assert turn["goal"]["family"] == "print"
    assert "print" in turn["known"].get("product", "").lower()
    assert not any(issue.get("code") == "no_question_asked" for issue in turn.get("issues") or [])


def test_asked_field_detects_vision_product_confirm():
    from chatbot.bot.guards import asked_field

    assert (
        asked_field("Thanks. Are you looking for print products from this artwork?")
        == "product"
    )


def test_goal_summary_keeps_reference_image_context():
    state = ConversationState(id="ref-goal", persona="Hazel Grace")
    state.flags["reference_image"] = True
    state.flags["reference_summary"] = "A cricket match promotional poster."
    text = state.summary()
    assert "reference image" in text.lower()
    assert "cricket match promotional poster" in text.lower()
    assert "re-send artwork" in text.lower()

