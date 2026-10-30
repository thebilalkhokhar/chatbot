from __future__ import annotations

import json
import logging
import re
import threading
import time
from dataclasses import dataclass, field

from .config import Config
from .pii import mask

log = logging.getLogger("chatbot.llm")

# Published text rates, USD per million tokens. Cached input is billed at the cache rate.
# https://developers.openai.com/api/docs/pricing — gpt-5-nano and gpt-5-mini.
_MODEL_RATES = (
    ("gpt-5-nano", (0.05, 0.005, 0.40)),
    ("gpt-5-mini", (0.25, 0.025, 2.00)),
    ("gpt-5", (1.25, 0.125, 10.00)),
)


def cost_usd(model: str, usage: dict | None) -> float:
    """Dollar cost of one completion. Unknown models use the mini rate so a guess cannot under-bill."""
    usage = usage or {}
    name = str(model or "").lower()
    # Longest prefix first. "gpt-5" is a prefix of "gpt-5-nano", and matching the
    # short name first would bill nano at the full gpt-5 rate.
    rates = _MODEL_RATES[-2][1]
    for prefix, candidate in sorted(_MODEL_RATES, key=lambda item: len(item[0]), reverse=True):
        if name.startswith(prefix):
            rates = candidate
            break
    prompt = int(usage.get("prompt_tokens") or 0)
    completion = int(usage.get("completion_tokens") or 0)
    details = usage.get("prompt_tokens_details") or {}
    cached = int(details.get("cached_tokens") or 0) if isinstance(details, dict) else 0
    cached = min(cached, prompt)
    fresh = prompt - cached
    input_rate, cached_rate, output_rate = rates
    return (fresh * input_rate + cached * cached_rate + completion * output_rate) / 1_000_000

REASONING_MODEL = re.compile(
    r"^o[0-9]|^gpt-5(\.\d+)?(-mini|-nano|-pro)?(-\d{4}-\d{2}-\d{2})?$", re.I
)


class LLMError(RuntimeError):
    pass


def is_reasoning_model(model: str) -> bool:
    return bool(REASONING_MODEL.match(str(model or "").strip()))


def build_payload(
    config: Config,
    system: str,
    user: str,
    schema: dict,
    *,
    name: str = "chat_reply",
) -> dict:
    payload = {
        "model": config.model,
        "messages": [
            {"role": "system", "content": mask(system)},
            {"role": "user", "content": mask(user)},
        ],
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": name, "strict": True, "schema": schema},
        },
    }
    if is_reasoning_model(config.model):
        # gpt-5-nano rejects temperature and max_tokens; reasoning models take
        # max_completion_tokens and answer faster at minimal effort.
        payload["max_completion_tokens"] = 800
        payload["reasoning_effort"] = "minimal"
    else:
        payload["temperature"] = 0.4
        payload["max_tokens"] = 400
    return payload


@dataclass
class LLMClient:
    """OpenAI-compatible chat completions over httpx.

    Nothing here runs in fake mode; Config.real_llm_enabled is the single gate
    that keeps test runs free. BOT_MAX_LLM_CALLS caps a whole server process.
    """

    config: Config
    calls: int = field(default=0, init=False)
    spent_usd: float = field(default=0.0, init=False)
    last_usage: dict = field(default_factory=dict, init=False)
    last_cost_usd: float = field(default=0.0, init=False)
    last_latency_ms: int = field(default=0, init=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)

    def _reserve_call(self) -> None:
        with self._lock:
            cap = self.config.max_llm_calls
            if cap and self.calls >= cap:
                raise LLMError(f"LLM call cap reached (BOT_MAX_LLM_CALLS={cap})")
            self.calls += 1

    def _post(self, payload: dict) -> dict:
        import httpx

        url = f"{self.config.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.config.api_key}",
            "Content-Type": "application/json",
        }
        try:
            with httpx.Client(timeout=self.config.timeout_s) as client:
                response = client.post(url, headers=headers, json=payload)
        except httpx.HTTPError as error:
            raise LLMError(f"LLM request failed: {error}") from error
        if response.status_code >= 400:
            raise LLMError(f"LLM returned {response.status_code}: {response.text[:300]}")
        return response.json()

    def complete_json(self, system: str, user: str, schema: dict, *, name: str = "chat_reply") -> dict:
        if not self.config.real_llm_enabled:
            raise LLMError("Real LLM calls are disabled; BOT_MODE=fake or BOT_ALLOW_LIVE=0")
        payload = build_payload(self.config, system, user, schema, name=name)
        started = time.perf_counter()
        self._reserve_call()
        try:
            body = self._post(payload)
        except LLMError as error:
            message = str(error).lower()
            if "400" in message and ("schema" in message or "response_format" in message):
                payload["response_format"] = {"type": "json_object"}
                self._reserve_call()
                body = self._post(payload)
            else:
                raise
        try:
            raw = body["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as error:
            raise LLMError(f"Unexpected LLM response: {body}") from error
        usage = body.get("usage") or {}
        elapsed = int((time.perf_counter() - started) * 1000)
        billed = cost_usd(body.get("model") or self.config.model, usage)
        self.last_usage = usage
        self.last_cost_usd = billed
        self.last_latency_ms = elapsed
        self.spent_usd += billed
        log.info(
            "llm %s model=%s ms=%d in=%s out=%s total=%s cost=%.6f",
            name,
            body.get("model") or self.config.model,
            elapsed,
            usage.get("prompt_tokens", "?"),
            usage.get("completion_tokens", "?"),
            usage.get("total_tokens", "?"),
            billed,
        )
        text = str(raw or "").strip()
        if text.startswith("```"):
            text = text.strip("`")
            text = text.split("\n", 1)[1] if "\n" in text else text
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as error:
            raise LLMError(f"LLM returned non-JSON: {text[:300]}") from error
        if not isinstance(parsed, dict):
            raise LLMError(f"LLM returned JSON that is not an object: {text[:300]}")
        return parsed


_BASIS_ENUM = ["canon", "catalogue", "model_knowledge", "visitor", ""]
_CONFIG_ITEM = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "family": {"type": "string"},
        "style": {"type": "string"},
        "style_card": {"type": "string"},
        "material": {"type": "string"},
        "gauge": {"type": "string"},
        "finish": {"type": "array", "items": {"type": "string"}},
        "insert": {"type": "array", "items": {"type": "string"}},
        "extras": {"type": "array", "items": {"type": "string"}},
        "size": {"type": "string"},
        "size_source": {"type": "string", "enum": ["catalogue", "visitor", ""]},
        "basis": {"type": "string", "enum": _BASIS_ENUM},
    },
    "required": [
        "family", "style", "style_card", "material", "gauge", "finish", "insert",
        "extras", "size", "size_source", "basis",
    ],
}
_FIELD_PROPOSED = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "key": {"type": "string"},
        "value": {"type": "string"},
        "basis": {"type": "string", "enum": _BASIS_ENUM},
    },
    "required": ["key", "value", "basis"],
}

REPLY_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "reply": {
            "type": "string",
            "description": (
                "Plain-text chat message. You MUST ask ONLY ONE single question. "
                "Never combine multiple asks. Do not mention MOQ or the minimum unless "
                "they asked what the minimum is."
            ),
        },
        "move": {
            "type": "string",
            "enum": ["answer", "ask", "propose", "offer_contact", "handoff", ""],
            "description": "The conversation move this message takes.",
        },
        "asked": {
            "type": "string",
            "enum": [
                "product", "style", "sizes", "finishes", "quantity", "skus",
                "material", "extras", "use_case", "name", "email", "phone", "",
            ],
            "description": "The one detail this message asks for, or empty string.",
        },
        "proposed_configs": {
            "type": "array",
            "description": "One object per option the reply names. Empty when the turn is only a greeting, an off-topic answer, or a correction of an impossible spec.",
            "items": _CONFIG_ITEM,
        },
        "fields_proposed": {
            "type": "array",
            "description": "Goal fields this turn proposes, each with where the value came from.",
            "items": _FIELD_PROPOSED,
        },
        "fields": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "product": {"type": "string"},
                "style": {"type": "string"},
                "sizes": {"type": "string"},
                "finishes": {"type": "string"},
                "quantity": {"type": "string"},
                "skus": {"type": "string"},
                "material": {"type": "string"},
                "extras": {"type": "string"},
                "use_case": {"type": "string"},
                "name": {"type": "string"},
                "email": {"type": "string"},
                "phone": {"type": "string"},
            },
            "required": [
                "product", "style", "sizes", "finishes", "quantity", "skus",
                "material", "extras", "use_case", "name", "email", "phone",
            ],
        },
    },
    "required": ["reply", "move", "asked", "proposed_configs", "fields_proposed", "fields"],
}
