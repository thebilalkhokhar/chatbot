from __future__ import annotations

import base64
import logging
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field

from . import canon
from .config import Config
from .orchestrator import Orchestrator
from .personas import PERSONAS, validate_personas

log = logging.getLogger("chatbot")
UI_PATH = Path(__file__).resolve().parent.parent / "web" / "index.html"


class LocalStart(BaseModel):
    conversation_id: str = Field(..., min_length=1, max_length=120)


class LocalChat(LocalStart):
    text: str = Field(..., min_length=1, max_length=4000)

SIGNATURE_HEADERS = (
    "x-siqsignature",
    "x-salesiq-signature",
    "x-zoho-signature",
    "salesiq-signature",
    "x-signature",
    "signature",
)
CLOSE_HANDLERS = {
    "closed", "chat_closed", "end", "chat_end", "visitor_left", "missed",
    "operator_closed", "visitor_closed", "session_end", "session_closed",
    "complete", "completed",
}
FAILURE_REPLY = "Sorry — something went wrong on our side. Please try again in a moment."


def verify_signature(raw: bytes, signature: str, public_key: str) -> bool | None:
    """RSA-SHA256 over the exact body, as SalesIQ sends it.

    Returns None when verification is not possible (no key or no cryptography
    library), so the caller can decide whether to fail open or closed.
    """
    if not public_key:
        return None
    if not signature:
        return False
    try:
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import padding
    except ImportError:
        return None
    try:
        key = serialization.load_pem_public_key(public_key.encode("utf-8"))
    except (ValueError, TypeError):
        return None
    for encoding in ("base64", "hex"):
        try:
            signature_bytes = base64.b64decode(signature) if encoding == "base64" else bytes.fromhex(signature)
            key.verify(signature_bytes, raw, padding.PKCS1v15(), hashes.SHA256())
            return True
        except Exception:
            continue
    return False


def _signature_header(headers) -> str:
    for name in SIGNATURE_HEADERS:
        value = headers.get(name)
        if value:
            return str(value)
    return ""


def _conversation_id(body: dict) -> str:
    visitor = body.get("visitor") or {}
    return str(
        visitor.get("uvid")
        or visitor.get("active_conversation_id")
        or visitor.get("visitor_id")
        or body.get("conversation_id")
        or ""
    )


def _handler(body: dict) -> str:
    return str(body.get("handler") or body.get("event") or body.get("type") or "").strip().lower()


def _message_text(body: dict) -> str:
    message = body.get("message") or {}
    text = message.get("text")
    if text is None:
        text = body.get("text")
    placeholder = str(text or "").strip().lower() == "file shared"
    if placeholder:
        comments = (message.get("meta") or {}).get("comments") or {}
        return " ".join(value for value in comments.values() if isinstance(value, str)).strip()
    return str(text or "").strip()


def _reply(texts: list[str]) -> dict:
    return {"action": "reply", "replies": [{"text": text} for text in texts if text]}


def _forward(texts: list[str], operators: list[str]) -> dict:
    return {
        "action": "forward",
        "operators": operators,
        "replies": [{"text": text} for text in texts if text],
    }


def create_app(config: Config | None = None, orchestrator: Orchestrator | None = None) -> FastAPI:
    app = FastAPI(title="Print247 support chat", version="0.1.0")
    cfg = config or Config.load()
    state: dict[str, Any] = {"orchestrator": orchestrator}

    def engine() -> Orchestrator:
        if state["orchestrator"] is None:
            state["orchestrator"] = Orchestrator(cfg)
        return state["orchestrator"]

    @app.get("/health")
    def health() -> dict:
        return {
            "ok": True,
            "mode": cfg.mode,
            "real_llm_enabled": cfg.real_llm_enabled,
            "personas": len(PERSONAS),
            "persona_errors": validate_personas(),
            "kb": engine().index.stats(),
            "store": engine().store.stats(),
        }

    @app.get("/", response_class=HTMLResponse)
    def local_chat_page():
        if not cfg.ui_enabled:
            return HTMLResponse("Not found", status_code=404)
        if not UI_PATH.exists():
            return HTMLResponse("Chat UI file is missing", status_code=500)
        return HTMLResponse(UI_PATH.read_text(encoding="utf-8"))

    @app.post("/api/start")
    def api_start(payload: LocalStart):
        if not cfg.ui_enabled:
            return JSONResponse({"error": "Not found"}, status_code=404)
        result = engine().start(payload.conversation_id, channel="ui")
        return result.to_dict()

    @app.post("/api/chat")
    def api_chat(payload: LocalChat):
        if not cfg.ui_enabled:
            return JSONResponse({"error": "Not found"}, status_code=404)
        try:
            result = engine().handle(payload.conversation_id, payload.text, channel="ui")
        except Exception:
            log.exception("UI chat failed")
            return JSONResponse({"error": "The reply failed. Please send that again."}, status_code=500)
        return result.to_dict()

    @app.get("/signoff")
    def signoff() -> dict:
        return {"facts_needing_signoff": canon.signoff_report()}

    @app.post("/salesiq/webhook")
    async def salesiq_webhook(request: Request):
        raw = await request.body()
        try:
            body = await request.json()
        except Exception:
            return JSONResponse({"error": "invalid json"}, status_code=400)

        signature = _signature_header(request.headers)
        verified = verify_signature(raw, signature, cfg.salesiq_public_key)
        if verified is False and not cfg.allow_unverified:
            log.warning("SalesIQ signature did not verify")
            return JSONResponse({"error": "Unauthorised"}, status_code=401)
        if verified is None and cfg.salesiq_public_key and not cfg.allow_unverified:
            log.error("Signature verification unavailable and BOT_ALLOW_UNVERIFIED is off")
            return JSONResponse({"error": "Signature verification unavailable"}, status_code=401)
        if verified is False:
            log.warning("Accepting unverified SalesIQ call (BOT_ALLOW_UNVERIFIED=1)")

        handler = _handler(body)
        conversation_id = _conversation_id(body)
        visitor = body.get("visitor") or {}
        channel = str(visitor.get("channel") or "website")

        if handler == "failure":
            cause = body.get("cause") or {}
            log.error("SalesIQ action failed: %s %s", cause.get("code"), cause.get("desc"))
            return _reply([FAILURE_REPLY])

        if handler in CLOSE_HANDLERS:
            if conversation_id:
                engine().store.append_event(conversation_id, "closed", {"handler": handler})
            return _reply([])

        if not conversation_id:
            return _reply([])

        if handler == "trigger":
            result = engine().start(conversation_id, channel=channel)
        else:
            text = _message_text(body)
            if not text:
                return _reply([])
            result = engine().handle(conversation_id, text, channel=channel)

        shadowed = cfg.mode in {"dry_run", "shadow"}
        if shadowed:
            log.info(
                "SHADOW %s [%s] %s -> %s",
                conversation_id,
                result.persona,
                "handoff" if result.handoff else result.source,
                result.reply,
            )
            return _reply([])

        if result.handoff and cfg.forward_on_handoff:
            return _forward([result.reply], [cfg.handoff_operator])
        return _reply([result.reply])

    return app


app = create_app()
