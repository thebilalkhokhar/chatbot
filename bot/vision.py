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
from .state import FAMILY_PRODUCT, FIELD_LABELS

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
        "focus_clear": {
            "type": "boolean",
            "description": "True only when the active open checklist field is clearly readable in the image.",
        },
        "focus_observation": {
            "type": "string",
            "description": "What you can say about the active open field from the image, or empty if unclear.",
        },
    },
    "required": [
        "summary",
        "family",
        "style",
        "material",
        "finishes",
        "notes",
        "focus_clear",
        "focus_observation",
    ],
}

SYSTEM_PROMPT = """You analyse a packaging or print reference image for Print247 sales chat.
Return JSON only.
Rules:
- Describe what you see briefly for a sales quote.
- Correlate the image STRICTLY with the ACTIVE OPEN FIELD from the sales checklist when one is provided.
  Prefer that field over other visible cues; do not invent values for closed fields.
  size → only report printed dimensions if clearly readable; never invent or estimate sizes.
  style → shape/construction cues using APPROVED CATALOGUE style terms for this family when supplied.
  finishes → surface sheen/texture using APPROVED CATALOGUE finish terms for this family when supplied.
  material → substrate cues using APPROVED CATALOGUE material terms when supplied.
  product/use_case → family or packed product only when obvious.
- When an approved vocabulary list is provided for the open field, map what you see onto the
  closest exact term from that list. Never invent a finish or style name outside the list.
- Suggest family/style/material/finish only when clearly visible.
- Set focus_clear true only when the active open field is clearly supported by the image;
  otherwise false and leave focus_observation empty or explain the uncertainty briefly.
- Never invent dimensions, MOQ, price, turnaround, or fit guarantees.
- If unsure, leave that field as an empty string.
- style examples when no list is given: mailer, rigid, tuck end, stand-up pouch, flat pouch, die-cut label.
- finishes examples when no list is given: matte lamination, gloss lamination, soft touch lamination, spot UV, foil printing.
"""


@dataclass
class VisionResult:
    summary: str
    family: str = ""
    style: str = ""
    material: str = ""
    finishes: str = ""
    notes: str = ""
    focus_clear: bool = False
    focus_observation: str = ""
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
            "focus_clear": self.focus_clear,
            "focus_observation": self.focus_observation,
            "source": self.source,
        }


def fake_vision_result(*, focus_field: str = "") -> VisionResult:
    focus = str(focus_field or "").strip()
    return VisionResult(
        summary="Reference image received. It looks like a packaging or print mockup.",
        notes="Stored for the quote. Confirm style with the visitor before locking fields.",
        focus_clear=False,
        focus_observation="" if focus else "",
        source="fake",
    )


def analyze_image(
    client: LLMClient,
    config: Config,
    data: bytes,
    mime: str,
    *,
    focus_field: str = "",
    focus_hint: str = "",
    family: str = "",
    catalogue_terms: str = "",
) -> VisionResult:
    """Describe a reference image. Fake mode returns a deterministic stub (no API call)."""
    focus = str(focus_field or "").strip()
    hint = str(focus_hint or "").strip()
    if not config.real_llm_enabled:
        return fake_vision_result(focus_field=focus)

    model = (config.vision_model or config.model or "").strip()
    if not model:
        raise LLMError("No vision model configured")

    encoded = base64.b64encode(data).decode("ascii")
    data_url = f"data:{mime};base64,{encoded}"
    focus_label = FIELD_LABELS.get(focus, focus.replace("_", " ") if focus else "")
    focus_lines = []
    if focus:
        focus_lines.append(f"Active open checklist field: {focus} ({focus_label}).")
        if hint:
            focus_lines.append(f"Current question wording: {hint}")
        if family:
            focus_lines.append(f"Active product family: {family}.")
        if catalogue_terms:
            focus_lines.append(
                "Approved catalogue vocabulary for the open field "
                f"(use an exact term from this list when focus_clear is true): {catalogue_terms}."
            )
        focus_lines.append(
            "Prioritise cues for that field only. If it is not clearly readable, set "
            "focus_clear=false and do not invent a value. Leave other slot fields empty "
            "unless they are required to name the open-field term."
        )
    else:
        focus_lines.append("No single active field — describe the packaging reference generally.")

    user_content = [
        {
            "type": "text",
            "text": (
                "Analyse this customer reference image for a packaging quote. "
                "Do not invent sizes.\n"
                + "\n".join(focus_lines)
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
    focus_observation = str(parsed.get("focus_observation") or "").strip()
    if re.search(r"\b\d+(\.\d+)?\s*(mm|cm|in|inch|inches)\b", focus_observation, re.I):
        # Dimensions are never auto-applied; keep observation free of invented measures.
        focus_observation = re.sub(
            r"\b\d+(\.\d+)?\s*(mm|cm|in|inch|inches)\b",
            "[size omitted]",
            focus_observation,
            flags=re.I,
        )
    focus_clear = bool(parsed.get("focus_clear")) and bool(focus_observation)
    return VisionResult(
        summary=summary[:400],
        family=family,
        style=style,
        material=material,
        finishes=finishes,
        notes=notes[:400],
        focus_clear=focus_clear,
        focus_observation=focus_observation[:200],
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
