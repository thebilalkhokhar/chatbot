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
        log.info(
            "llm %s model=%s ms=%d in=%s out=%s total=%s",
            name,
            body.get("model") or self.config.model,
            int((time.perf_counter() - started) * 1000),
            usage.get("prompt_tokens", "?"),
            usage.get("completion_tokens", "?"),
            usage.get("total_tokens", "?"),
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


REPLY_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "reply": {
            "type": "string",
            "description": "Plain-text chat message. One short answer and at most one question.",
        },
        "asked": {
            "type": "string",
            "enum": [
                "product", "style", "sizes", "finishes", "quantity", "skus",
                "material", "extras", "name", "email", "phone", "",
            ],
            "description": "The one detail this message asks for, or empty string.",
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
                "name": {"type": "string"},
                "email": {"type": "string"},
                "phone": {"type": "string"},
            },
            "required": [
                "product", "style", "sizes", "finishes", "quantity", "skus",
                "material", "extras", "name", "email", "phone",
            ],
        },
    },
    "required": ["reply", "asked", "fields"],
}
