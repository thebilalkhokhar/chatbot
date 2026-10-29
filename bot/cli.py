from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from . import canon
from .config import Config, ConfigError
from .golden import build_golden
from .kb import KBIndex
from .llm import LLMClient, LLMError
from .orchestrator import Orchestrator
from .replay import run_replay


def _print_json(value) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2))


def cmd_ingest(config: Config, args) -> int:
    index = KBIndex.build(config.kb_dir)
    path = config.data_dir / "kb_index.json"
    index.save(path)
    print("KB indexed:", json.dumps(index.stats(), ensure_ascii=False))
    print("Index file:", path)
    report = canon.signoff_report()
    print(f"\nFacts needing sign-off: {len(report)}")
    for item in report:
        print(f"- {item['label']} [{item['key']}]: {item['note']}")
    return 0


def cmd_signoff(config: Config, args) -> int:
    _print_json({"facts_needing_signoff": canon.signoff_report()})
    return 0


def cmd_llm_check(config: Config, args) -> int:
    try:
        config.require_live()
    except ConfigError as error:
        print(f"not ready: {error}", file=sys.stderr)
        return 2
    schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {"ok": {"type": "boolean"}, "message": {"type": "string"}},
        "required": ["ok", "message"],
    }
    client = LLMClient(config)
    try:
        parsed = client.complete_json(
            "You are a connectivity check. Reply only with the requested JSON.",
            'Return exactly {"ok": true, "message": "pong"} as JSON.',
            schema,
            name="ping",
        )
    except LLMError as error:
        print(f"LLM check failed: {error}", file=sys.stderr)
        return 1
    _print_json({"ok": True, "model": config.model, "calls": client.calls, "response": parsed})
    return 0


def cmd_golden(config: Config, args) -> int:
    project = config.kb_dir.parent
    chats = Path(args.chats) if args.chats else project / "server" / "data" / "chats.json"
    judged = Path(args.judged) if args.judged else project / "server" / "out" / "judge_300.jsonl"
    out = Path(args.out) if args.out else config.data_dir / "golden.jsonl"
    stats = build_golden(
        chats,
        judged,
        out,
        per_family_cap=args.per_family_cap,
        total_cap=args.total_cap,
    )
    _print_json(stats)
    return 0


def cmd_replay(config: Config, args) -> int:
    project = config.kb_dir.parent
    chats = Path(args.chats) if args.chats else project / "server" / "data" / "chats.json"
    judged = Path(args.judged) if args.judged else project / "server" / "out" / "judge_300.jsonl"
    stats = run_replay(
        config,
        chats_path=chats,
        limit=args.limit,
        judged_path=judged,
        out_dir=config.out_dir,
    )
    summary = {key: stats[key] for key in (
        "chats_replayed", "turns", "avg_replies_per_chat", "avg_words_per_reply",
        "question_reply_rate", "blocker_rate", "blockers", "handoffs", "sources",
        "personas", "errors", "json_path", "md_path",
    )}
    _print_json(summary)
    return 0


def cmd_ask(config: Config, args) -> int:
    orchestrator = Orchestrator(config)
    try:
        if args.start:
            started = orchestrator.start(args.conversation_id)
            _print_json({"start": started.to_dict()})
        result = orchestrator.handle(args.conversation_id, args.text)
        _print_json(result.to_dict())
    finally:
        orchestrator.close()
    return 0


def cmd_chat(config: Config, args) -> int:
    orchestrator = Orchestrator(config)
    conversation_id = args.conversation_id or f"cli-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    try:
        greeting = orchestrator.start(conversation_id)
        print(f"[{greeting.persona}] {greeting.reply}")
        while True:
            try:
                text = input("You: ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break
            if not text:
                continue
            if text.lower() in {"exit", "quit"}:
                break
            result = orchestrator.handle(conversation_id, text)
            if not result.reply:
                print(f"(chat is handed off: {result.handoff or 'closed'})")
                break
            print(f"[{result.persona}] {result.reply}")
            if result.issues:
                print(f"  ! {', '.join(issue['code'] for issue in result.issues)}")
            if result.handoff:
                print(f"(handoff: {result.handoff})")
                break
    finally:
        orchestrator.close()
    return 0


def cmd_transcript(config: Config, args) -> int:
    import sqlite3

    from .state import ConversationState

    db = Path(args.db)
    if not db.exists():
        print(f"no such database: {db}", file=sys.stderr)
        return 1
    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT state_json FROM conversations ORDER BY rowid LIMIT ?", (args.limit,)
        ).fetchall()
    finally:
        conn.close()
    for row in rows:
        state = ConversationState.from_dict(json.loads(row["state_json"]))
        collected = ", ".join(sorted(key for key, value in state.fields.items() if value.done))
        print(f"\n=== {state.id} · {state.persona} · handoff={state.handoff or '-'} · collected={collected or '-'}")
        for message in state.messages:
            who = state.persona if message.author == "ai" else "Visitor"
            print(f"{who}: {message.text}")
    return 0


def cmd_serve(config: Config, args) -> int:
    import uvicorn

    uvicorn.run("chatbot.bot.service:app", host=args.host, port=args.port, reload=False)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="chatbot", description="Print247 support chat service")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("ingest", help="build the KB search index").set_defaults(func=cmd_ingest)
    sub.add_parser("signoff", help="list facts that need sales sign-off").set_defaults(func=cmd_signoff)
    sub.add_parser(
        "llm-check",
        help="send one tiny live OpenAI call to verify the key and model (paid)",
    ).set_defaults(func=cmd_llm_check)

    golden_parser = sub.add_parser("golden", help="build golden examples from judged chats")
    golden_parser.add_argument("--chats")
    golden_parser.add_argument("--judged")
    golden_parser.add_argument("--out")
    golden_parser.add_argument("--per-family-cap", type=int, default=22)
    golden_parser.add_argument("--total-cap", type=int, default=150)
    golden_parser.set_defaults(func=cmd_golden)

    replay_parser = sub.add_parser("replay", help="replay old chats through the new pipeline")
    replay_parser.add_argument("--chats")
    replay_parser.add_argument("--judged")
    replay_parser.add_argument("--limit", type=int, default=100)
    replay_parser.set_defaults(func=cmd_replay)

    ask_parser = sub.add_parser("ask", help="send one message")
    ask_parser.add_argument("--conversation-id", default="cli-test")
    ask_parser.add_argument("--text", required=True)
    ask_parser.add_argument("--start", action="store_true", help="send the opening greeting first")
    ask_parser.set_defaults(func=cmd_ask)

    chat_parser = sub.add_parser("chat", help="interactive local chat")
    chat_parser.add_argument("--conversation-id")
    chat_parser.set_defaults(func=cmd_chat)

    transcript_parser = sub.add_parser("transcript", help="print conversations from a state database")
    transcript_parser.add_argument("--db", required=True, help="sqlite file, e.g. out/replay_<stamp>.sqlite3")
    transcript_parser.add_argument("--limit", type=int, default=5)
    transcript_parser.set_defaults(func=cmd_transcript)

    serve_parser = sub.add_parser("serve", help="run the SalesIQ webhook")
    serve_parser.add_argument("--host", default="127.0.0.1")
    serve_parser.add_argument("--port", type=int, default=8000)
    serve_parser.set_defaults(func=cmd_serve)

    args = parser.parse_args(argv)
    config = Config.load()
    config.ensure_dirs()
    return args.func(config, args)


if __name__ == "__main__":
    sys.exit(main())
