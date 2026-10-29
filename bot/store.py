from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path

from .personas import PERSONAS, persona_for
from .state import ConversationState, now_iso


class StateStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init()

    def _init(self) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS conversations (
                    id TEXT PRIMARY KEY,
                    persona TEXT NOT NULL,
                    state_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'active'
                )
                """
            )
            self._conn.execute(
                "CREATE TABLE IF NOT EXISTS counter (name TEXT PRIMARY KEY, value INTEGER NOT NULL)"
            )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    conversation_id TEXT NOT NULL,
                    at TEXT NOT NULL,
                    type TEXT NOT NULL,
                    data_json TEXT NOT NULL
                )
                """
            )

    def next_persona(self):
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                row = self._conn.execute("SELECT value FROM counter WHERE name = 'persona'").fetchone()
                if row is None:
                    position = 0
                    self._conn.execute("INSERT INTO counter (name, value) VALUES ('persona', 1)")
                else:
                    position = int(row["value"])
                    self._conn.execute("UPDATE counter SET value = value + 1 WHERE name = 'persona'")
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise
        return PERSONAS[position % len(PERSONAS)]

    def get_or_create(self, conversation_id: str, persona_name: str | None = None) -> ConversationState:
        with self._lock:
            row = self._conn.execute(
                "SELECT state_json FROM conversations WHERE id = ?", (conversation_id,)
            ).fetchone()
            if row is not None:
                return ConversationState.from_dict(json.loads(row["state_json"]))
        persona = persona_for(persona_name) or self.next_persona()
        state = ConversationState(id=conversation_id, persona=persona.name)
        self.save(state)
        self.append_event(conversation_id, "created", {"persona": persona.name})
        return state

    def save(self, state: ConversationState) -> None:
        payload = json.dumps(state.to_dict(), ensure_ascii=False)
        status = "handed_off" if state.handoff else "active"
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO conversations (id, persona, state_json, created_at, updated_at, status)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    state_json = excluded.state_json,
                    updated_at = excluded.updated_at,
                    status = excluded.status
                """,
                (state.id, state.persona, payload, state.created_at, now_iso(), status),
            )

    def append_event(self, conversation_id: str, event_type: str, data: dict | None = None) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO events (conversation_id, at, type, data_json) VALUES (?, ?, ?, ?)",
                (conversation_id, now_iso(), event_type, json.dumps(data or {}, ensure_ascii=False)),
            )

    def stats(self) -> dict:
        with self._lock:
            total = self._conn.execute("SELECT COUNT(*) AS n FROM conversations").fetchone()["n"]
            handed = self._conn.execute(
                "SELECT COUNT(*) AS n FROM conversations WHERE status = 'handed_off'"
            ).fetchone()["n"]
            events = self._conn.execute("SELECT COUNT(*) AS n FROM events").fetchone()["n"]
            counter = self._conn.execute("SELECT value FROM counter WHERE name = 'persona'").fetchone()
        return {
            "conversations": total,
            "handed_off": handed,
            "events": events,
            "persona_counter": int(counter["value"]) if counter else 0,
        }

    def close(self) -> None:
        with self._lock:
            self._conn.close()
