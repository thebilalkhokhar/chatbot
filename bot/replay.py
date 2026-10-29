from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from . import guards
from .config import Config
from .orchestrator import Orchestrator
from .pii import mask


def _visitor_messages(chat: dict) -> list[str]:
    return [
        str(message.get("text") or "").strip()
        for message in chat.get("messages", [])
        if message.get("author") == "visitor" and str(message.get("text") or "").strip()
    ]


def _baseline(judged_path: Path | None) -> dict:
    if not judged_path or not judged_path.exists():
        return {}
    verdicts: Counter[str] = Counter()
    issues: Counter[str] = Counter()
    total = 0
    for line in judged_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        total += 1
        verdicts[str(record.get("verdict") or "unknown")] += 1
        for issue in record.get("issues", []):
            issues[str(issue.get("type") or "other")] += 1
    return {
        "judged": total,
        "verdicts": dict(verdicts),
        "top_issue_types": issues.most_common(12),
    }


def run_replay(
    config: Config,
    *,
    chats_path: Path,
    limit: int = 100,
    judged_path: Path | None = None,
    out_dir: Path | None = None,
) -> dict:
    chats = json.loads(chats_path.read_text(encoding="utf-8"))
    real = [chat for chat in chats if _visitor_messages(chat)]
    selected = real[:limit]

    out_dir = out_dir or config.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    db_path = out_dir / f"replay_{stamp}.sqlite3"
    if db_path.exists():
        db_path.unlink()

    orchestrator = Orchestrator(config, store_path=db_path)
    issue_counts: Counter[str] = Counter()
    blocker_counts: Counter[str] = Counter()
    handoff_counts: Counter[str] = Counter()
    source_counts: Counter[str] = Counter()
    persona_counts: Counter[str] = Counter()
    accepted_counts: Counter[str] = Counter()
    per_chat: list[dict] = []
    blocker_examples: list[dict] = []
    issue_examples: dict[str, list[dict]] = {}
    blocked_counts: Counter[str] = Counter()
    blocked_examples: list[dict] = []
    errors: list[dict] = []
    total_words = 0
    total_replies = 0
    question_replies = 0
    empty_retrieval = 0

    try:
        for index, chat in enumerate(selected, start=1):
            conversation_id = f"replay-{index}-{str(chat.get('conversationId') or '')[:24]}"
            turns: list[dict] = []
            try:
                orchestrator.start(conversation_id)
                for visitor in _visitor_messages(chat)[: config.max_turns]:
                    result = orchestrator.handle(conversation_id, visitor)
                    if not result.reply:
                        turns.append(
                            {
                                "visitor_words": len(visitor.split()),
                                "reply": "",
                                "issues": result.issues,
                                "blocked": result.blocked,
                                "handoff": result.handoff,
                                "source": result.source,
                            }
                        )
                        break
                    turns.append(
                        {
                            "visitor": mask(visitor),
                            "visitor_words": len(visitor.split()),
                            "reply_words": len(result.reply.split()),
                            "reply": result.reply,
                            "issues": result.issues,
                            "blocked": result.blocked,
                            "handoff": result.handoff,
                            "source": result.source,
                        }
                    )
                    for key in result.accepted:
                        accepted_counts[key] += 1
                    if not result.retrieved:
                        empty_retrieval += 1
                    if result.handoff:
                        break
            except Exception as error:  # a replay must survive one bad chat
                errors.append({"conversation": conversation_id, "error": f"{type(error).__name__}: {error}"})
                continue

            replies = [turn for turn in turns if turn.get("reply")]
            total_replies += len(replies)
            total_words += sum(turn.get("reply_words", 0) for turn in replies)
            for turn in replies:
                source_counts[turn.get("source", "heuristic")] += 1
                for issue in turn.get("blocked") or []:
                    blocked_counts[issue["code"]] += 1
                    if len(blocked_examples) < 8:
                        blocked_examples.append(
                            {
                                "code": issue["code"],
                                "detail": issue.get("detail", ""),
                                "visitor": turn.get("visitor", ""),
                                "reply": mask(turn["reply"]),
                            }
                        )
                if guards.count_questions(turn["reply"]) > 0:
                    question_replies += 1
                for issue in turn.get("issues", []):
                    issue_counts[issue["code"]] += 1
                    if issue.get("severity") == guards.BLOCK:
                        blocker_counts[issue["code"]] += 1
                        if len(blocker_examples) < 12:
                            blocker_examples.append(
                                {
                                    "code": issue["code"],
                                    "detail": issue.get("detail", ""),
                                    "visitor": turn.get("visitor", ""),
                                    "reply": mask(turn["reply"]),
                                }
                            )
                    elif len(issue_examples.setdefault(issue["code"], [])) < 3:
                        issue_examples[issue["code"]].append(
                            {
                                "detail": issue.get("detail", ""),
                                "visitor": turn.get("visitor", ""),
                                "reply": mask(turn["reply"]),
                            }
                        )
            handoff = turns[-1].get("handoff", "") if turns else ""
            if handoff:
                handoff_counts[handoff] += 1
            last_reply = replies[-1]["reply"] if replies else ""
            persona = ""
            if last_reply:
                persona = orchestrator.store.get_or_create(conversation_id).persona
                persona_counts[persona] += 1

            per_chat.append(
                {
                    "conversation_id": conversation_id,
                    "source_messages": len(_visitor_messages(chat)),
                    "turns": len(replies),
                    "handoff": handoff,
                    "persona": persona,
                    "blocker_codes": sorted(
                        {issue["code"] for turn in replies for issue in turn.get("issues", []) if issue.get("severity") == guards.BLOCK}
                    ),
                }
            )
    finally:
        orchestrator.close()

    replies_count = total_replies or 1
    stats = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": config.mode,
        "chats_in_export": len(chats),
        "real_chats": len(real),
        "chats_replayed": len(per_chat),
        "errors": errors,
        "turns": total_replies,
        "avg_replies_per_chat": round(total_replies / len(per_chat), 2) if per_chat else 0,
        "avg_words_per_reply": round(total_words / replies_count, 1),
        "question_reply_rate": round(question_replies / replies_count, 3),
        "blocker_rate": round(sum(blocker_counts.values()) / replies_count, 4),
        "blockers": blocker_counts.most_common(),
        "blocker_examples": blocker_examples,
        "blocked_drafts": blocked_counts.most_common(),
        "blocked_draft_examples": blocked_examples,
        "issues": issue_counts.most_common(),
        "issue_examples": issue_examples,
        "handoffs": handoff_counts.most_common(),
        "sources": source_counts.most_common(),
        "personas": persona_counts.most_common(),
        "fields_collected": accepted_counts.most_common(),
        "empty_retrieval_replies": empty_retrieval,
        "baseline": _baseline(judged_path),
        "chats": per_chat,
    }

    json_path = out_dir / f"replay_{stamp}.json"
    json_path.write_text(json.dumps(stats, ensure_ascii=False, indent=1), encoding="utf-8")
    md_path = out_dir / f"replay_{stamp}.md"
    md_path.write_text(_report(stats), encoding="utf-8")
    stats["json_path"] = str(json_path)
    stats["md_path"] = str(md_path)
    return stats


def _table(rows: list[tuple[str, object]], headers: tuple[str, str]) -> str:
    lines = [f"| {headers[0]} | {headers[1]} |", "| --- | --- |"]
    lines.extend(f"| {left} | {right} |" for left, right in rows)
    return "\n".join(lines)


def _report(stats: dict) -> str:
    baseline = stats.get("baseline") or {}
    lines = [
        "# Chatbot replay report",
        "",
        f"- Generated: {stats['generated_at']}",
        f"- Mode: {stats['mode']}",
        f"- Export chats: {stats['chats_in_export']} ({stats['real_chats']} with a visitor message)",
        f"- Replayed: {stats['chats_replayed']} chats, {stats['turns']} replies",
        f"- Avg replies per chat: {stats['avg_replies_per_chat']}",
        f"- Avg words per reply: {stats['avg_words_per_reply']}",
        f"- Replies containing a question: {stats['question_reply_rate']:.0%}",
        f"- Deterministic blocker rate: {stats['blocker_rate']:.2%}",
        f"- Replies with no KB hits: {stats['empty_retrieval_replies']}",
        f"- Replies replaced by a safer fallback: {dict(stats['sources']).get('fallback', 0)}",
        "",
        "## Guard results",
        _table(stats["blockers"] or [("none", 0)], ("Blocker", "Count")),
    ]
    if stats.get("blocker_examples"):
        lines.append("")
        lines.append("### Blocked reply examples (masked)")
        for item in stats["blocker_examples"]:
            lines.append(
                f"- **{item['code']}**: visitor: {item['visitor']!r} -> reply: {item['reply']!r} — {item['detail']}"
            )
    if stats.get("blocked_drafts"):
        lines.append("")
        lines.append("## Rejected drafts")
        lines.append(_table(stats["blocked_drafts"], ("Code", "Count")))
        lines.append("")
        lines.append("### Rejected draft examples (masked; the reply shown is what was sent instead)")
        for item in stats.get("blocked_draft_examples", []):
            lines.append(
                f"- **{item['code']}**: visitor: {item['visitor']!r} -> sent: {item['reply']!r} — {item['detail']}"
            )
    lines.extend(
        [
            "",
            "## All codes",
            _table(stats["issues"] or [("none", 0)], ("Code", "Count")),
        ]
    )
    for code, examples in (stats.get("issue_examples") or {}).items():
        lines.append("")
        lines.append(f"### {code} examples (masked)")
        for item in examples:
            lines.append(
                f"- visitor: {item['visitor']!r} -> reply: {item['reply']!r} — {item['detail']}"
            )
    lines.extend(
        [
            "",
            "## Handoffs",
            _table(stats["handoffs"] or [("none", 0)], ("Reason", "Chats")),
            "",
            "## Personas",
            _table(stats["personas"] or [("none", 0)], ("Persona", "Chats")),
            "",
            "## Fields collected",
            _table(stats["fields_collected"] or [("none", 0)], ("Field", "Times")),
            "",
            "## Production baseline (300 judged chats)",
        ]
    )
    if baseline:
        lines.append(f"- Judged: {baseline.get('judged', 0)}")
        lines.append(f"- Verdicts: {baseline.get('verdicts', {})}")
        lines.append("")
        lines.append(_table(baseline.get("top_issue_types", []), ("Production issue type", "Count")))
    else:
        lines.append("- No judged baseline found.")
    lines.extend(
        [
            "",
            "## How to read this",
            "",
            "- A blocker is a reply this system refused to send and replaced with a safe fallback.",
            "- A rejected draft is also refused, but the fallback sent in its place passed every rule; only blockers are counted in the blocker rate.",
            "- The production baseline counts issues a judge found in old chats; the two columns are not the same measurement.",
            "- A fake-mode run measures rule compliance and pipeline behaviour only, not sales quality.",
            "",
        ]
    )
    return "\n".join(lines)
