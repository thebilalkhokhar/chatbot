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
from .state import (
    EMAIL_RE,
    FAMILY_PRODUCT,
    FIELD_LABELS,
    PHONE_RE,
    TO_BE_CONFIRMED,
    is_to_be_confirmed,
    valid_email,
    valid_phone,
)

log = logging.getLogger("chatbot.vision")

IMAGE_KINDS = ("packaging", "contact", "text", "other", "unclear")

VISION_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "summary": {
            "type": "string",
            "description": "One or two short sentences describing what the image actually shows.",
        },
        "image_kind": {
            "type": "string",
            "enum": list(IMAGE_KINDS),
            "description": (
                "packaging = product/mockup/dieline; contact = email/phone/business card only; "
                "text = typed brief/specs/notes (may include product, qty, size, finish); "
                "other/unclear otherwise."
            ),
        },
        "family": {
            "type": "string",
            "enum": ["boxes", "bags", "labels", "banners", "business_cards", "print", ""],
        },
        "style": {"type": "string"},
        "material": {"type": "string"},
        "finishes": {"type": "string"},
        "use_case": {
            "type": "string",
            "description": "What the packaging is for, when clearly readable (e.g. coffee pouches).",
        },
        "quantity": {
            "type": "string",
            "description": "Order quantity digits only when clearly readable, else empty.",
        },
        "sizes": {
            "type": "string",
            "description": "Printed dimensions with unit when clearly readable, else empty. Never invent.",
        },
        "notes": {
            "type": "string",
            "description": "Extra cues useful for quoting. Do not invent dimensions.",
        },
        "readable_text": {
            "type": "string",
            "description": "Full OCR of clearly readable text from the image.",
        },
        "email": {
            "type": "string",
            "description": "A clearly readable email address from the image, else empty.",
        },
        "phone": {
            "type": "string",
            "description": "A clearly readable phone number from the image, else empty.",
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
        "image_kind",
        "family",
        "style",
        "material",
        "finishes",
        "use_case",
        "quantity",
        "sizes",
        "notes",
        "readable_text",
        "email",
        "phone",
        "focus_clear",
        "focus_observation",
    ],
}

SYSTEM_PROMPT = """You analyse a customer-uploaded image for Print247 sales chat.
Return JSON only.
Rules:
- Always fill readable_text with a full OCR of every clearly readable word. Never leave it
  empty when text is visible. Do not invent text that is not in the image.
- Extract every quote detail that is clearly visible into the matching fields:
  family, style, material, finishes, use_case, quantity, sizes, email, phone.
  Leave a field empty when it is not clearly readable. Never invent dimensions, qty, MOQ, price, or dates.
- Classify image_kind carefully:
  text = typed brief / specs / notepad / screenshot that lists order details
         (product, quantity, size, finish, use case, etc.). This is NOT contact.
  contact = ONLY when the image is mainly an email address, phone number, or business card
            and has no order brief. If both appear, prefer text and still extract both.
  packaging = a box, bag/pouch, label artwork, banner, card, dieline, or print mockup photo.
  other / unclear = anything else.
- Never use image_kind=contact for an order brief. A page that says what to make, how many,
  and what size is image_kind=text even if it has no photo of a product.
- For contact images: do not invent packaging family/style/material/finish/quantity/sizes.
  Put transcribed words in readable_text; copy email/phone exactly.
- For text briefs: fill every readable order field from the OCR.
  family = product family when named (labels/boxes/bags/…).
  use_case = what it is for (e.g. coffee pouches), not the family word alone.
  quantity = digits only; sizes = dimensions with unit; finishes may be "to be confirmed".
- For packaging images: describe what you see; map style/material/finish onto APPROVED
  catalogue terms when a list is supplied. Correlate with the ACTIVE OPEN FIELD when given.
- Set focus_clear true only when the active open field is clearly supported by the image.
- If unsure, leave that field as an empty string.
"""


@dataclass
class VisionResult:
    summary: str
    image_kind: str = "unclear"
    family: str = ""
    style: str = ""
    material: str = ""
    finishes: str = ""
    use_case: str = ""
    quantity: str = ""
    sizes: str = ""
    notes: str = ""
    readable_text: str = ""
    email: str = ""
    phone: str = ""
    focus_clear: bool = False
    focus_observation: str = ""
    source: str = "fake"
    raw: dict[str, Any] = field(default_factory=dict)

    def has_order_details(self) -> bool:
        return bool(
            self.family
            or self.style
            or self.material
            or self.finishes
            or self.use_case
            or self.quantity
            or self.sizes
        )

    def is_contact_only(self) -> bool:
        """True only for email/phone shots — never for order briefs."""
        if self.has_order_details():
            return False
        ocr = str(self.readable_text or "").strip()
        if ocr and not (self.email or self.phone):
            # Visible text with no contact detail is a brief/other, not contact-only.
            return False
        if ocr and (self.email or self.phone):
            leftover = ocr
            if self.email:
                leftover = re.sub(re.escape(self.email), " ", leftover, flags=re.I)
            if self.phone:
                leftover = re.sub(re.escape(self.phone), " ", leftover, flags=re.I)
            leftover = re.sub(r"[\s|,;:.\-_/\\]+", "", leftover)
            if len(leftover) > 8:
                return False
        if self.image_kind == "contact":
            return bool(self.email or self.phone)
        return bool(self.email or self.phone) and self.image_kind in {
            "contact",
            "text",
            "unclear",
            "other",
        }

    def field_updates(self) -> dict[str, str]:
        updates: dict[str, str] = {}
        if self.email and valid_email(self.email):
            updates["email"] = self.email
        if self.phone and valid_phone(self.phone):
            updates["phone"] = self.phone
        if self.is_contact_only():
            return updates
        if self.family:
            updates["product"] = FAMILY_PRODUCT.get(
                self.family, self.family.replace("_", " ")
            )
        if self.style:
            updates["style"] = self.style
        if self.material:
            updates["material"] = self.material
        # "FINISH: TO BE CONFIRMED" on a brief means not chosen yet — leave finishes
        # open so the checklist can ask. Do not waive from the image alone.
        if self.finishes and not is_to_be_confirmed(self.finishes):
            updates["finishes"] = self.finishes
        if self.use_case:
            updates["use_case"] = self.use_case
        if self.quantity:
            updates["quantity"] = self.quantity
        if self.sizes:
            updates["sizes"] = self.sizes
        return updates

    def turn_enrichment(self) -> str:
        """Merge OCR + customer facts into the visitor turn for extract/traceable.

        Catalogue style/material/finish stay out so packaging cues remain suggested
        until the visitor confirms them. Explicit \"to be confirmed\" finishes are
        included so waiver tracing still works for typed briefs.
        """
        parts: list[str] = []
        seen = ""
        chunks = [
            self.readable_text,
            self.use_case,
            self.quantity,
            self.sizes,
            self.email,
            self.phone,
        ]
        for chunk in chunks:
            text = str(chunk or "").strip()
            if not text:
                continue
            if text.lower() in seen.lower():
                continue
            parts.append(text)
            seen = f"{seen} {text}".strip()
        return " ".join(parts)

    def contact_enrichment(self) -> str:
        return self.turn_enrichment()

    def to_dict(self) -> dict:
        return {
            "summary": self.summary,
            "image_kind": self.image_kind,
            "family": self.family,
            "style": self.style,
            "material": self.material,
            "finishes": self.finishes,
            "use_case": self.use_case,
            "quantity": self.quantity,
            "sizes": self.sizes,
            "notes": self.notes,
            "readable_text": self.readable_text,
            "email": self.email,
            "phone": self.phone,
            "focus_clear": self.focus_clear,
            "focus_observation": self.focus_observation,
            "source": self.source,
        }


def fake_vision_result(*, focus_field: str = "") -> VisionResult:
    focus = str(focus_field or "").strip()
    return VisionResult(
        summary="Reference image received. It looks like a packaging or print mockup.",
        image_kind="packaging",
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
            "Still extract EVERY other clearly readable quote field (product family, "
            "use case, quantity, sizes, finish, email, phone). Only invent nothing. "
            "Set focus_clear from the active field alone."
        )
    else:
        focus_lines.append(
            "No single active field — OCR the image and extract every clearly readable "
            "quote detail. If it is contact-only, extract email/phone and do not invent packaging."
        )

    instruction = (
        "Analyse this customer-uploaded image for a packaging quote. "
        "OCR all readable text into readable_text first, classify image_kind, "
        "and fill every visible quote field. Typed order briefs are image_kind=text, "
        "not contact. Do not invent sizes or packaging when the image is only "
        "an email/phone.\n"
        + "\n".join(focus_lines)
    )
    result = _vision_model_call(client, model, data_url, instruction)
    if _vision_needs_ocr_retry(result):
        log.info("Vision returned no OCR/order fields; retrying with OCR-first prompt")
        retry = _vision_model_call(
            client,
            model,
            data_url,
            (
                "Read EVERY visible word in this image into readable_text. "
                "If it lists a product, quantity, size, or finish, set image_kind=text "
                "and fill family, use_case, quantity, sizes, finishes from that text. "
                "Only use image_kind=contact when the image is mainly an email or phone."
            ),
        )
        if retry.readable_text or retry.has_order_details() or retry.email or retry.phone:
            return retry
    return result


def _vision_needs_ocr_retry(result: VisionResult) -> bool:
    if result.readable_text.strip():
        return False
    if result.has_order_details():
        return False
    if result.email or result.phone:
        return False
    return True


def _vision_model_call(
    client: LLMClient,
    model: str,
    data_url: str,
    instruction: str,
) -> VisionResult:
    user_content = [
        {"type": "text", "text": instruction},
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
        payload["max_completion_tokens"] = 700
        payload["reasoning_effort"] = "minimal"
    else:
        payload["temperature"] = 0.1
        payload["max_tokens"] = 700

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
    kind = str(parsed.get("image_kind") or "").strip().lower()
    if kind not in IMAGE_KINDS:
        kind = "unclear"
    summary = str(parsed.get("summary") or "").strip() or "Reference image received."
    style = _clean_slot(parsed.get("style"))
    material = _clean_slot(parsed.get("material"))
    finishes = _clean_finish(parsed.get("finishes"))
    use_case = str(parsed.get("use_case") or "").strip()[:80]
    quantity = _clean_quantity(parsed.get("quantity"))
    sizes = _clean_size(parsed.get("sizes"))
    notes = str(parsed.get("notes") or "").strip()
    readable_text = str(parsed.get("readable_text") or "").strip()
    email = str(parsed.get("email") or "").strip()
    phone = str(parsed.get("phone") or "").strip()
    # Notes/observations must not smuggle invented dimensions into free text we show.
    if re.search(r"\b\d+(\.\d+)?\s*(mm|cm|in|inch|inches)\b", notes, re.I) and not sizes:
        notes = re.sub(
            r"\b\d+(\.\d+)?\s*(mm|cm|in|inch|inches)\b",
            "[size omitted]",
            notes,
            flags=re.I,
        )
    focus_observation = str(parsed.get("focus_observation") or "").strip()
    if re.search(r"\b\d+(\.\d+)?\s*(mm|cm|in|inch|inches)\b", focus_observation, re.I) and not sizes:
        focus_observation = re.sub(
            r"\b\d+(\.\d+)?\s*(mm|cm|in|inch|inches)\b",
            "[size omitted]",
            focus_observation,
            flags=re.I,
        )
    focus_clear = bool(parsed.get("focus_clear")) and bool(focus_observation)

    blob = " ".join(part for part in (email, phone, readable_text, notes, summary) if part)
    if not valid_email(email):
        found = EMAIL_RE.search(blob)
        email = found.group(0) if found and valid_email(found.group(0)) else ""
    if not valid_phone(phone):
        found_phone = PHONE_RE.search(blob)
        phone = found_phone.group(0) if found_phone and valid_phone(found_phone.group(0)) else ""

    # contact with order fields or OCR body is a mislabel — keep the facts.
    if kind == "contact" and not email and not phone:
        if quantity or sizes or use_case or family or readable_text.strip():
            kind = "text"
        else:
            kind = "unclear"

    # Email/phone-only shots must not keep a hallucinated pouch/family.
    # Trust OCR leftovers over a model-invented family/style.
    if _looks_like_contact_only(kind, email, phone, readable_text, quantity, sizes, use_case):
        kind = "contact"
        family = ""
        style = ""
        material = ""
        finishes = ""
        use_case = ""
        quantity = ""
        sizes = ""
        focus_clear = False
        if (
            not summary
            or re.search(r"\b(?:pouch|packaging|mockup|dieline|mailer|label)\b", summary, re.I)
        ):
            if email:
                summary = f"The image shows the email address {email}."
            elif phone:
                summary = f"The image shows the phone number {phone}."
            else:
                summary = "The image shows contact details, not a packaging mockup."

    return VisionResult(
        summary=summary[:400],
        image_kind=kind,
        family=family,
        style=style,
        material=material,
        finishes=finishes,
        use_case=use_case,
        quantity=quantity,
        sizes=sizes,
        notes=notes[:400],
        readable_text=readable_text[:800],
        email=email[:120],
        phone=phone[:40],
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


def _clean_finish(value: Any) -> str:
    text = str(value or "").strip()
    if not text or len(text) > 60:
        return ""
    if is_to_be_confirmed(text) or re.search(r"\bto\s*be\s*confirmed\b", text, re.I):
        return TO_BE_CONFIRMED
    return _clean_slot(text)


def _clean_quantity(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    digits = re.sub(r"[^\d]", "", text)
    if not digits or len(digits) > 8:
        return ""
    return str(int(digits))


def _clean_size(value: Any) -> str:
    text = str(value or "").strip()
    if not text or len(text) > 40:
        return ""
    # Keep only values that look like dimensions with optional unit — never free prose.
    if not re.search(r"\d", text):
        return ""
    if is_to_be_confirmed(text):
        return TO_BE_CONFIRMED
    return re.sub(r"\s+", " ", text.replace("*", "x").replace("×", "x")).strip()


def _looks_like_contact_only(
    kind: str,
    email: str,
    phone: str,
    readable_text: str,
    quantity: str = "",
    sizes: str = "",
    use_case: str = "",
) -> bool:
    """True only for contact-only uploads — not typed order briefs."""
    if quantity or sizes or use_case:
        return False
    if not (email or phone):
        return False
    text = str(readable_text or "").strip()
    if not text:
        return kind in {"contact", "unclear", "other"}
    cleaned = text
    if email:
        cleaned = re.sub(re.escape(email), " ", cleaned, flags=re.I)
    if phone:
        cleaned = re.sub(re.escape(phone), " ", cleaned, flags=re.I)
    cleaned = re.sub(r"[\s|,;:.\-_/\\]+", "", cleaned)
    return len(cleaned) <= 2
