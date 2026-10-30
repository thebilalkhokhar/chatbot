from __future__ import annotations

from dataclasses import replace

from fastapi.testclient import TestClient

from chatbot.bot.service import create_app


def test_health_and_webhook_fake_flow(config, orchestrator):
    app = create_app(config, orchestrator)
    client = TestClient(app)

    health = client.get("/health")
    assert health.status_code == 200
    assert health.json()["ok"] is True
    assert health.json()["personas"] == 9

    trigger = client.post(
        "/salesiq/webhook", json={"handler": "trigger", "visitor": {"uvid": "visitor-1"}}
    )
    assert trigger.status_code == 200
    payload = trigger.json()
    assert payload["action"] == "reply"
    assert payload["replies"]
    assert "what are you looking" in payload["replies"][0]["text"].lower()

    message = client.post(
        "/salesiq/webhook",
        json={
            "handler": "message",
            "visitor": {"uvid": "visitor-1"},
            "message": {"text": "I need custom boxes", "type": "text"},
        },
    )
    assert message.status_code == 200
    reply = message.json()["replies"][0]["text"]
    assert "inside" in reply.lower()


def test_webhook_close_and_empty_message(config, orchestrator):
    app = create_app(config, orchestrator)
    client = TestClient(app)

    closed = client.post(
        "/salesiq/webhook", json={"handler": "closed", "visitor": {"uvid": "visitor-2"}}
    )
    assert closed.status_code == 200
    assert closed.json()["replies"] == []

    empty = client.post(
        "/salesiq/webhook",
        json={"handler": "message", "visitor": {"uvid": "visitor-2"}, "message": {"text": ""}},
    )
    assert empty.status_code == 200
    assert empty.json()["replies"] == []


def test_webhook_trigger_without_id_is_ignored(config, orchestrator):
    app = create_app(config, orchestrator)
    client = TestClient(app)
    response = client.post("/salesiq/webhook", json={"handler": "trigger", "visitor": {}})
    assert response.status_code == 200
    assert response.json()["replies"] == []


def test_local_chat_ui_flow(config, orchestrator):
    client = TestClient(create_app(config, orchestrator))

    page = client.get("/")
    assert page.status_code == 200
    assert "Print247 chat" in page.text

    started = client.post("/api/start", json={"conversation_id": "ui-1"})
    assert started.status_code == 200
    greeting = started.json()
    assert greeting["persona"]
    assert "what are you looking" in greeting["reply"].lower()

    message = client.post(
        "/api/chat", json={"conversation_id": "ui-1", "text": "I need custom boxes"}
    )
    assert message.status_code == 200
    turn = message.json()
    assert "inside" in turn["reply"].lower()
    assert turn["source"] == "heuristic"
    assert "product" in turn["known"]

    empty = client.post("/api/chat", json={"conversation_id": "ui-1", "text": ""})
    assert empty.status_code == 422


def test_local_chat_ui_can_be_disabled(config, orchestrator):
    client = TestClient(create_app(replace(config, ui_enabled=False), orchestrator))

    assert client.get("/").status_code == 404
    assert client.post("/api/start", json={"conversation_id": "ui-2"}).status_code == 404
    assert client.post("/api/chat", json={"conversation_id": "ui-2", "text": "hi"}).status_code == 404
