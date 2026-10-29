from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from .pii import mask
from .state import family_of

PRICE = re.compile(r"[$€£]\s*\d|\b\d[\d,]*(?:\.\d+)?\s*(?:usd|dollars?|per unit)\b", re.I)
CHECK = re.compile(r"\b(?:i|we)(?:'ll| will)\s+(?:check|confirm|verify|get back|find out)\b", re.I)
MARKDOWN = re.compile(r"\*\*|^\s*[-*•]\s|^\s*#{1,6}\s", re.M)


def load_chats(path: Path) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_judged(path: Path) -> list[dict]:
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return records


def _id_variants(value: str) -> list[str]:
    raw = str(value or "").strip()
    if not raw:
        return []
    base = raw.split("~", 1)[0]
    return list(dict.fromkeys([raw, base]))


def _pairs(messages: list[dict]) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for index, message in enumerate(messages):
        if message.get("author") != "visitor":
            continue
        visitor = str(message.get("text") or "").strip()
        if not visitor:
            continue
        reply = ""
        for later in messages[index + 1 :]:
            if later.get("author") == "ai":
                reply = str(later.get("text") or "").strip()
                break
            if later.get("author") == "visitor":
                break
        if reply:
            pairs.append((visitor, reply))
    return pairs


def _clean_pair(visitor: str, reply: str) -> bool:
    if not visitor or not reply:
        return False
    if len(visitor.split()) > 60 or not (5 <= len(reply.split()) <= 70):
        return False
    if reply.count("?") > 1:
        return False
    if PRICE.search(reply) or CHECK.search(reply) or MARKDOWN.search(reply):
        return False
    if reply.lower().startswith(("hi, i'm", "hello, i'm", "hey, i'm")) and reply.count("?") == 1:
        return False
    if re.fullmatch(r"\s*(?:hi|hello|hey|thanks|thank you|ok(?:ay)?)\s*[.!]*", visitor, re.I):
        return False
    return True


def build_golden(
    chats_path: Path,
    judged_path: Path,
    out_path: Path,
    *,
    per_family_cap: int = 22,
    total_cap: int = 150,
) -> dict:
    chats = load_chats(chats_path)
    judged = load_judged(judged_path)

    by_id: dict[str, dict] = {}
    for chat in chats:
        for variant in _id_variants(chat.get("conversationId", "")):
            by_id.setdefault(variant, chat)

    matched = 0
    missing = 0
    buckets: dict[str, list[dict]] = defaultdict(list)
    seen: set[str] = set()

    for record in judged:
        if str(record.get("verdict") or "").lower() != "correct":
            continue
        chat = None
        for variant in _id_variants(record.get("conversationId", "")):
            chat = by_id.get(variant)
            if chat:
                break
        if not chat:
            missing += 1
            continue
        matched += 1
        for visitor, reply in _pairs(chat.get("messages", [])):
            if not _clean_pair(visitor, reply):
                continue
            key = re.sub(r"\W+", " ", mask(visitor).lower()).strip()
            if key in seen:
                continue
            seen.add(key)
            family = family_of("", (visitor, reply))
            if family == "unknown":
                family = "general"
            buckets[family].append(
                {
                    "visitor": mask(visitor),
                    "reply": mask(reply),
                    "family": family.split(":")[0],
                    "conversation_id": chat.get("conversationId", ""),
                    "source": "judge_correct",
                }
            )

    examples: list[dict] = []
    order = sorted(buckets, key=lambda name: (-len(buckets[name]), name))
    for family in order:
        examples.extend(buckets[family][:per_family_cap])
    examples = examples[:total_cap]

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as handle:
        for item in examples:
            handle.write(json.dumps(item, ensure_ascii=False) + "\n")

    return {
        "built_at": datetime.now(timezone.utc).isoformat(),
        "judged_records": len(judged),
        "correct_records": sum(1 for item in judged if str(item.get("verdict")).lower() == "correct"),
        "matched_chats": matched,
        "unmatched_correct_chats": missing,
        "examples": len(examples),
        "families": Counter(item["family"] for item in examples).most_common(),
        "out_path": str(out_path),
    }
