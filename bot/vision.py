from __future__ import annotations

import base64
import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any

from .config import Config
from .llm import LLMClient, LLMError, cost_usd, is_reasoning_model
from .state import FAMILY_PRODUCT

log = logging.getLogger("chatbot.vision")

VISION_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "summary": {
            "type": "string",
            "description": "One or two short sentences describing the packaging reference.",
        },
        "family": {
            "type": "string",
            "enum": ["boxes", "bags", "labels", "banners", "business_cards", "print", ""],
        },
        "style": {"type": "string"},
        "material": {"type": "string"},
        "finishes": {"type": "string"},
        "notes": {
            "type": "string",
            "description": "Extra cues useful for quoting. Do not invent dimensions.",
        },
    },
    "required": ["summary", "family", "style", "material", "finishes", "notes"],
}

SYSTEM_PROMPT = """You analyse a packaging or print reference image for Print247 sales chat.
Return JSON only.
Rules:
- Describe what you see briefly for a sales quote.
- Suggest family/style/material/finish only when clearly visible.
- Never invent dimensions, MOQ, price, turnaround, or fit guarantees.
- If unsure, leave that field as an empty string.
- style examples: mailer, rigid, tuck end, stand-up pouch, flat pouch, die-cut label.
- finishes examples: matte, gloss, soft touch.
"""


@dataclass
class VisionResult:
    summary: str
    family: str = ""
    style: str = ""
    material: str = ""
    finishes: str = ""
    notes: str = ""
    source: str = "fake"
    raw: dict[str, Any] = field(default_factory=dict)

    def field_updates(self) -> dict[str, str]:
        updates: dict[str, str] = {}
        if self.family:
            # Same labels ConversationState.family() / FAMILY_PRODUCT expect.
            updates["product"] = FAMILY_PRODUCT.get(
                self.family, self.family.replace("_", " ")
            )
        if self.style:
            updates["style"] = self.style
        if self.material:
            updates["material"] = self.material
        if self.finishes:
            updates["finishes"] = self.finishes
        return updates

    def to_dict(self) -> dict:
        return {
            "summary": self.summary,
            "family": self.family,
            "style": self.style,
            "material": self.material,
            "finishes": self.finishes,
            "notes": self.notes,
            "source": self.source,
        }


def fake_vision_result() -> VisionResult:
    return VisionResult(
        summary="Reference image received. It looks like a packaging or print mockup.",
        notes="Stored for the quote. Confirm style with the visitor before locking fields.",
        source="fake",
    )


def analyze_image(
    client: LLMClient,
    config: Config,
    data: bytes,
    mime: str,
) -> VisionResult:
    """Describe a reference image. Fake mode returns a deterministic stub (no API call)."""
    if not config.real_llm_enabled:
        return fake_vision_result()

    model = (config.vision_model or config.model or "").strip()
    if not model:
        raise LLMError("No vision model configured")

    encoded = base64.b64encode(data).decode("ascii")
    data_url = f"data:{mime};base64,{encoded}"
    user_content = [
        {
            "type": "text",
            "text": (
                "Analyse this customer reference image for a packaging quote. "
                "Do not invent sizes."
            ),
        },
        {"type": "image_url", "image_url": {"url": data_url}},
    ]
    payload: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": "image_analysis", "strict": True, "schema": VISION_SCHEMA},
        },
    }
    if is_reasoning_model(model):
        payload["max_completion_tokens"] = 500
        payload["reasoning_effort"] = "minimal"
    else:
        payload["temperature"] = 0.2
        payload["max_tokens"] = 400

    # Reuse the client's spend/cap accounting without going through text-only complete_json.
    started = time.perf_counter()
    client._reserve_call()
    try:
        body = client._post(payload)
    except LLMError as error:
        message = str(error).lower()
        if "400" in message and ("schema" in message or "response_format" in message):
            payload["response_format"] = {"type": "json_object"}
            client._reserve_call()
            body = client._post(payload)
        else:
            raise

    try:
        raw = body["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as error:
        raise LLMError(f"Unexpected vision response: {body}") from error

    usage = body.get("usage") or {}
    elapsed = int((time.perf_counter() - started) * 1000)
    billed = cost_usd(body.get("model") or model, usage)
    client.last_usage = usage
    client.last_cost_usd = billed
    client.last_latency_ms = elapsed
    client.spent_usd += billed
    log.info(
        "vision model=%s ms=%d in=%s out=%s cost=%.6f",
        body.get("model") or model,
        elapsed,
        usage.get("prompt_tokens", "?"),
        usage.get("completion_tokens", "?"),
        billed,
    )

    text = str(raw or "").strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text.split("\n", 1)[1] if "\n" in text else text
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as error:
        raise LLMError(f"Vision returned non-JSON: {text[:300]}") from error
    if not isinstance(parsed, dict):
        raise LLMError(f"Vision returned JSON that is not an object: {text[:300]}")
    return _from_payload(parsed, source="live")


def _from_payload(parsed: dict, *, source: str) -> VisionResult:
    family = str(parsed.get("family") or "").strip().lower()
    if family not in {"boxes", "bags", "labels", "banners", "business_cards", "print", ""}:
        family = ""
    summary = str(parsed.get("summary") or "").strip() or "Reference image received."
    # Strip any dimension-like invention from free-text slots we may apply later.
    style = _clean_slot(parsed.get("style"))
    material = _clean_slot(parsed.get("material"))
    finishes = _clean_slot(parsed.get("finishes"))
    notes = str(parsed.get("notes") or "").strip()
    if re.search(r"\b\d+(\.\d+)?\s*(mm|cm|in|inch|inches)\b", notes, re.I):
        notes = re.sub(
            r"\b\d+(\.\d+)?\s*(mm|cm|in|inch|inches)\b",
            "[size omitted]",
            notes,
            flags=re.I,
        )
    return VisionResult(
        summary=summary[:400],
        family=family,
        style=style,
        material=material,
        finishes=finishes,
        notes=notes[:400],
        source=source,
        raw=parsed,
    )


def _clean_slot(value: Any) -> str:
    text = str(value or "").strip()
    if not text or len(text) > 40 or len(text.split()) > 5:
        return ""
    if re.search(r"\b\d+(\.\d+)?\s*(mm|cm|in|inch|inches)\b", text, re.I):
        return ""
    return text
