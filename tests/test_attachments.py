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


def test_vercel_blob_put_sends_private_access_header(monkeypatch):
    # Private Blob stores 400 if access defaults to public (query param alone is ignored).
    from chatbot.bot.attachments import VercelBlobStore

    captured: dict = {}

    class FakeResponse:
        status_code = 200

        def json(self):
            return {"url": "https://store.private.blob.vercel-storage.com/attachments/a.png"}

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def put(self, url, headers=None, content=None):
            captured["url"] = url
            captured["headers"] = dict(headers or {})
            captured["content"] = content
            return FakeResponse()

    monkeypatch.setattr("httpx.Client", FakeClient)
    store = VercelBlobStore("vercel_blob_rw_test_token")
    url = store.put("attachments/demo/a.png", PNG_1X1, "image/png")
    assert url.endswith("a.png")
    assert "access=" not in captured["url"] or "access=private" in captured["url"]
    assert captured["headers"].get("x-vercel-blob-access") == "private"
    assert captured["headers"].get("x-content-type") == "image/png"
    assert captured["content"] == PNG_1X1


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
    assert result.image_kind == "packaging"
    assert result.field_updates() == {}


def test_vision_payload_email_screenshot_strips_packaging_hallucination():
    from chatbot.bot.vision import _from_payload

    result = _from_payload(
        {
            "summary": "The image depicts a packaging reference that appears to be a flat pouch.",
            "image_kind": "packaging",
            "family": "bags",
            "style": "flat pouch",
            "material": "",
            "finishes": "",
            "use_case": "",
            "quantity": "",
            "sizes": "",
            "notes": "",
            "readable_text": "annlee@gmail.com",
            "email": "annlee@gmail.com",
            "phone": "",
            "focus_clear": False,
            "focus_observation": "",
        },
        source="live",
    )
    assert result.image_kind == "contact"
    assert result.email == "annlee@gmail.com"
    assert result.family == ""
    assert result.style == ""
    assert "pouch" not in result.summary.lower()
    assert "annlee@gmail.com" in result.summary
    assert result.field_updates() == {"email": "annlee@gmail.com"}


def test_contact_mislabel_with_order_ocr_is_treated_as_brief():
    from chatbot.bot.vision import _from_payload

    result = _from_payload(
        {
            "summary": "Text or contact details",
            "image_kind": "contact",
            "family": "",
            "style": "",
            "material": "",
            "finishes": "",
            "use_case": "",
            "quantity": "",
            "sizes": "",
            "notes": "",
            "readable_text": (
                "labels for coffee pouches QUANTITY: 250 SIZE: 10x15 CM "
                "FINISH: TO BE CONFIRMED"
            ),
            "email": "",
            "phone": "",
            "focus_clear": False,
            "focus_observation": "",
        },
        source="live",
    )
    assert result.image_kind == "text"
    assert not result.is_contact_only()
    assert "labels for coffee pouches" in result.turn_enrichment().lower()


def test_contact_mislabel_keeps_structured_order_fields():
    from chatbot.bot.vision import _from_payload

    result = _from_payload(
        {
            "summary": "Contact card",
            "image_kind": "contact",
            "family": "labels",
            "style": "",
            "material": "",
            "finishes": "to be confirmed",
            "use_case": "coffee pouches",
            "quantity": "250",
            "sizes": "10x15 CM",
            "notes": "",
            "readable_text": "",
            "email": "",
            "phone": "",
            "focus_clear": False,
            "focus_observation": "",
        },
        source="live",
    )
    assert result.image_kind == "text"
    assert result.quantity == "250"
    assert "15" in result.sizes or "10" in result.sizes
    assert result.field_updates()["product"]
    assert result.field_updates()["quantity"] == "250"
    assert not result.is_contact_only()


def test_shared_image_placeholder_is_not_an_attach_request():
    from chatbot.bot.state import asks_to_share_reference

    assert asks_to_share_reference("can i share a reference image?")
    assert not asks_to_share_reference("[shared a reference image]")
    assert not asks_to_share_reference(
        "[shared a reference image] labels for coffee pouches QUANTITY: 350"
    )


def test_email_only_image_is_captured_not_treated_as_pouch(orchestrator, monkeypatch):
    def fake_analyze(client, cfg, data, mime, focus_field="", focus_hint="", **_kwargs):
        return VisionResult(
            summary="The image shows the email address annlee@gmail.com.",
            image_kind="contact",
            email="annlee@gmail.com",
            readable_text="annlee@gmail.com",
            focus_clear=False,
            source="live",
        )

    monkeypatch.setattr("chatbot.bot.orchestrator.analyze_image", fake_analyze)
    orchestrator.start("img-email")
    result = orchestrator.handle(
        "img-email",
        "[shared a reference image]",
        image=PNG_1X1,
        image_mime="image/png",
    )
    lowered = result.reply.lower()
    assert "annlee@gmail.com" in lowered
    assert "noted" in lowered or "email" in lowered
    assert "pouch" not in lowered
    assert "packaging reference" not in lowered
    assert "please attach" not in lowered
    assert result.source == "vision"
    state = orchestrator.store.get_or_create("img-email")
    assert state.fields["email"].value == "annlee@gmail.com"
    assert not state.fields["product"].done
    assert "boxes" in lowered or "bags" in lowered or "labels" in lowered


def test_vision_still_runs_when_attachment_save_fails(orchestrator, monkeypatch):
    # Production Blob 400 used to abort the whole image path before OCR.
    def boom(*_args, **_kwargs):
        raise AttachmentError(
            'blob upload returned 400: Cannot use public access on a private store'
        )

    def fake_analyze(client, cfg, data, mime, focus_field="", focus_hint="", **_kwargs):
        return VisionResult(
            summary="A typed brief for coffee pouch labels.",
            image_kind="text",
            family="labels",
            use_case="coffee pouches",
            quantity="350",
            sizes="15x15 cm",
            readable_text="labels for coffee pouches QUANTITY: 350 SIZE: 15x15 CM",
            focus_clear=True,
            source="live",
        )

    monkeypatch.setattr(orchestrator.attachments, "save", boom)
    monkeypatch.setattr("chatbot.bot.orchestrator.analyze_image", fake_analyze)
    orchestrator.start("img-blob-fail")
    result = orchestrator.handle(
        "img-blob-fail",
        "[shared a reference image]",
        image=PNG_1X1,
        image_mime="image/png",
    )
    state = orchestrator.store.get_or_create("img-blob-fail")
    assert result.source == "vision"
    assert "label" in state.fields["product"].value.lower()
    assert state.fields["quantity"].value == "350"
    assert state.flags.get("attachment_error")


def test_order_brief_image_extracts_product_qty_size_finish(orchestrator, monkeypatch):
    def fake_analyze(client, cfg, data, mime, focus_field="", focus_hint="", **_kwargs):
        return VisionResult(
            summary="A typed brief for coffee pouch labels.",
            image_kind="text",
            family="labels",
            use_case="coffee pouches",
            quantity="350",
            sizes="15x15 CM",
            finishes="to be confirmed",
            readable_text=(
                "labels for coffee pouches QUANTITY: 350 SIZE: 15 * 15 CM "
                "FINISH: TO BE CONFIRMED"
            ),
            focus_clear=True,
            focus_observation="labels",
            source="live",
        )

    monkeypatch.setattr("chatbot.bot.orchestrator.analyze_image", fake_analyze)
    orchestrator.start("img-brief")
    result = orchestrator.handle(
        "img-brief",
        "[shared a reference image]",
        image=PNG_1X1,
        image_mime="image/png",
    )
    lowered = result.reply.lower()
    assert result.source == "vision"
    assert "please attach" not in lowered
    assert "350" in result.reply or "350" in lowered
    assert "label" in lowered
    state = orchestrator.store.get_or_create("img-brief")
    assert "label" in state.fields["product"].value.lower()
    assert state.fields["quantity"].value == "350"
    assert "15" in state.fields["sizes"].value
    assert "cm" in state.fields["sizes"].value.lower()
    assert "coffee" in state.fields["use_case"].value.lower()
    assert "pouch" in state.fields["use_case"].value.lower()
    assert "labels for coffee" not in state.fields["use_case"].value.lower()
    # Brief "FINISH: TO BE CONFIRMED" means not chosen yet — leave finish open.
    assert not state.fields["finishes"].done


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
    def fake_analyze(client, cfg, data, mime, focus_field="", focus_hint="", **_kwargs):
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
    assert "print products" in turn["reply"].lower() or "should i use this" in turn["reply"].lower()
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


def test_asks_to_share_reference_is_invited_not_ignored(orchestrator):
    from chatbot.bot.state import asks_to_share_reference

    assert asks_to_share_reference("can i add reference image for this?")
    orchestrator.start("img-ask")
    first = orchestrator.handle("img-ask", "whiskey bottle label")
    state = orchestrator.store.get_or_create("img-ask")
    assert state.fields["use_case"].value == "whiskey bottle"
    assert "use_case" not in state.ask_set()
    result = orchestrator.handle("img-ask", "can i add reference image for this?")
    lowered = result.reply.lower()
    assert "yes" in lowered or "attach" in lowered
    assert "reference" in lowered or "image" in lowered
    # Keep the open size ask — do not bounce back to use case.
    assert "inside" not in lowered
    assert "size" in lowered or "what size" in first.reply.lower() or state.last_question == "sizes"
    assert "possibly_unanswered_question" not in {
        issue.get("code") for issue in (result.issues or [])
    }


def test_vision_reply_confirms_detected_style_conversationally(orchestrator, monkeypatch):
    def fake_analyze(client, cfg, data, mime, focus_field="", focus_hint="", **_kwargs):
        return VisionResult(
            summary="A matte die-cut whiskey bottle label mockup.",
            family="labels",
            style="die-cut label",
            finishes="matte",
            focus_clear=True,
            focus_observation="die-cut label with matte finish",
            source="live",
        )

    monkeypatch.setattr("chatbot.bot.orchestrator.analyze_image", fake_analyze)
    orchestrator.start("img-confirm")
    orchestrator.handle("img-confirm", "labels for whisky bottle")
    result = orchestrator.handle(
        "img-confirm",
        "",
        image=PNG_1X1,
        image_mime="image/png",
    )
    lowered = result.reply.lower()
    assert "i see the reference image" in lowered
    assert "should i use this" in lowered or "die-cut" in lowered or "matte" in lowered
    assert result.source == "vision"


def test_vision_unclear_size_asks_for_clarification(orchestrator, monkeypatch):
    def fake_analyze(client, cfg, data, mime, focus_field="", focus_hint="", **_kwargs):
        assert focus_field == "sizes"
        return VisionResult(
            summary="A whiskey bottle label design without readable dimensions.",
            family="labels",
            focus_clear=False,
            focus_observation="",
            source="live",
        )

    monkeypatch.setattr("chatbot.bot.orchestrator.analyze_image", fake_analyze)
    orchestrator.start("img-size")
    orchestrator.handle("img-size", "labels for whisky bottle")
    # Drive last_question toward sizes if needed.
    state = orchestrator.store.get_or_create("img-size")
    state.last_question = "sizes"
    orchestrator.store.save(state)
    result = orchestrator.handle(
        "img-size",
        "",
        image=PNG_1X1,
        image_mime="image/png",
    )
    lowered = result.reply.lower()
    assert "i see the reference image" in lowered
    assert "dimension" in lowered or "size" in lowered
    assert "the what it is for" not in lowered
    assert "inside" not in lowered
    assert result.source == "vision"


def test_vision_unclear_use_case_wording_is_natural(orchestrator):
    from chatbot.bot.state import STATUS_VISITOR, field_clarify_phrase
    from chatbot.bot.vision import VisionResult

    assert field_clarify_phrase("use_case") == "what this is for"

    orchestrator.start("img-usecase")
    state = orchestrator.store.get_or_create("img-usecase")
    state.set_field("product", "labels", status=STATUS_VISITOR)
    state.last_question = "use_case"
    vision = VisionResult(
        summary="A bottle with a large brand label.",
        family="labels",
        focus_clear=False,
        focus_observation="",
        source="live",
    )
    reply = orchestrator._vision_reply(
        state,
        vision,
        {},
        ("use_case", "What will you be using the bags for?"),
    )
    lowered = reply.lower()
    assert "i see the reference image" in lowered
    assert "the what it is for" not in lowered
    assert "what this is for" in lowered or "inside" in lowered or "going to" in lowered


def test_image_after_size_ask_does_not_reask_use_case(orchestrator, monkeypatch):
    def fake_analyze(client, cfg, data, mime, focus_field="", focus_hint="", **_kwargs):
        assert focus_field == "sizes"
        return VisionResult(
            summary="Blenders Pride whisky bottle label at sunset.",
            family="labels",
            focus_clear=False,
            focus_observation="",
            source="live",
        )

    monkeypatch.setattr("chatbot.bot.orchestrator.analyze_image", fake_analyze)
    orchestrator.start("img-keep-size")
    orchestrator.handle("img-keep-size", "whiskey bottle label")
    state = orchestrator.store.get_or_create("img-keep-size")
    assert state.fields["use_case"].value == "whiskey bottle"
    state.last_question = "sizes"
    # Leave use_case askable noise: attempts spent should not yank focus from size.
    state.fields["use_case"].attempts = 2
    orchestrator.store.save(state)
    result = orchestrator.handle(
        "img-keep-size",
        "",
        image=PNG_1X1,
        image_mime="image/png",
    )
    lowered = result.reply.lower()
    assert "size" in lowered or "dimension" in lowered
    assert "inside" not in lowered
    assert "the what it is for" not in lowered
    state = orchestrator.store.get_or_create("img-keep-size")
    missing = " ".join(state.missing_for_prompt()).lower()
    assert "what it is for" not in missing


def test_vision_box_finish_uses_catalogue_term(orchestrator, monkeypatch):
    from chatbot.bot.state import STATUS_VISITOR

    def fake_analyze(client, cfg, data, mime, focus_field="", focus_hint="", **kwargs):
        assert focus_field == "finishes"
        assert "matte lamination" in str(kwargs.get("catalogue_terms") or "")
        return VisionResult(
            summary="A rigid gift box with a soft matte surface.",
            family="boxes",
            style="gift",
            finishes="matte",
            focus_clear=True,
            focus_observation="matte surface on a gift box",
            source="live",
        )

    monkeypatch.setattr("chatbot.bot.orchestrator.analyze_image", fake_analyze)
    orchestrator.start("img-box-finish")
    state = orchestrator.store.get_or_create("img-box-finish")
    for key, value in (
        ("product", "boxes"),
        ("use_case", "candles"),
        ("sizes", "4x4x4 in"),
        ("quantity", "500"),
        ("style", "gift"),
    ):
        state.set_field(key, value, raw=value, status=STATUS_VISITOR)
    # Soft early email would otherwise jump ahead of finishes on image focus.
    state.flags["soft_email_asked"] = True
    state.last_question = "finishes"
    orchestrator.store.save(state)

    result = orchestrator.handle(
        "img-box-finish",
        "",
        image=PNG_1X1,
        image_mime="image/png",
    )
    lowered = result.reply.lower()
    assert "i see the reference image" in lowered
    assert "matte lamination" in lowered
    assert "drip" not in lowered
    assert "should i use this" in lowered
    state = orchestrator.store.get_or_create("img-box-finish")
    assert state.fields["finishes"].value == "matte lamination"
    # Style was already settled; vision must not reopen it from a side cue.
    assert state.fields["style"].value == "gift"

