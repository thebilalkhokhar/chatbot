from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Any, Protocol

from .personas import PERSONAS, persona_for
from .state import ConversationState, now_iso


class StateStore(Protocol):
    def next_persona(self): ...

    def get_or_create(self, conversation_id: str, persona_name: str | None = None) -> ConversationState: ...

    def save(self, state: ConversationState) -> None: ...

    def append_event(self, conversation_id: str, event_type: str, data: dict | None = None) -> None: ...

    def stats(self) -> dict: ...

    def close(self) -> None: ...


class SqliteStateStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.backend = "sqlite"
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
            "backend": self.backend,
            "conversations": total,
            "handed_off": handed,
            "events": events,
            "persona_counter": int(counter["value"]) if counter else 0,
        }

    def close(self) -> None:
        with self._lock:
            self._conn.close()


class PostgresStateStore:
    """Conversation state backed by Postgres (Neon / any DATABASE_URL)."""

    def __init__(self, database_url: str) -> None:
        self.backend = "postgres"
        self.database_url = database_url
        self._lock = threading.RLock()
        self._conn = None
        self._connect()
        self._init()

    def _connect(self) -> None:
        import psycopg
        from psycopg.rows import dict_row

        old = self._conn
        self._conn = psycopg.connect(
            self.database_url,
            row_factory=dict_row,
            # Serverless + Neon: never leave an open transaction between requests.
            autocommit=True,
            connect_timeout=10,
        )
        if old is not None:
            try:
                old.close()
            except Exception:
                pass

    @staticmethod
    def _is_conn_error(error: BaseException) -> bool:
        try:
            from psycopg import OperationalError
            from psycopg.errors import IdleInTransactionSessionTimeout
        except ImportError:
            return "connection is closed" in str(error).lower() or "terminating connection" in str(error).lower()
        return isinstance(error, (OperationalError, IdleInTransactionSessionTimeout))

    def _ensure_conn(self) -> None:
        if self._conn is None or self._conn.closed:
            self._connect()

    def _run(self, op):
        """Run DB work once, reconnect + retry on a dead serverless connection."""
        with self._lock:
            self._ensure_conn()
            try:
                return op()
            except Exception as error:
                if not self._is_conn_error(error):
                    raise
                self._connect()
                return op()

    def _init(self) -> None:
        def work():
            with self._conn.cursor() as cur:
                cur.execute(
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
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS counter (
                        name TEXT PRIMARY KEY,
                        value INTEGER NOT NULL
                    )
                    """
                )
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS events (
                        id BIGSERIAL PRIMARY KEY,
                        conversation_id TEXT NOT NULL,
                        at TEXT NOT NULL,
                        type TEXT NOT NULL,
                        data_json TEXT NOT NULL
                    )
                    """
                )

        self._run(work)

    def next_persona(self):
        def work():
            with self._conn.cursor() as cur:
                # Atomically allocate the previous counter value as the persona index.
                cur.execute(
                    """
                    INSERT INTO counter (name, value) VALUES ('persona', 1)
                    ON CONFLICT (name) DO UPDATE SET value = counter.value + 1
                    RETURNING (value - 1) AS position
                    """
                )
                return int(cur.fetchone()["position"])

        position = self._run(work)
        return PERSONAS[position % len(PERSONAS)]

    def get_or_create(self, conversation_id: str, persona_name: str | None = None) -> ConversationState:
        def work():
            with self._conn.cursor() as cur:
                cur.execute("SELECT state_json FROM conversations WHERE id = %s", (conversation_id,))
                return cur.fetchone()

        row = self._run(work)
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

        def work():
            with self._conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO conversations (id, persona, state_json, created_at, updated_at, status)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO UPDATE SET
                        state_json = EXCLUDED.state_json,
                        updated_at = EXCLUDED.updated_at,
                        status = EXCLUDED.status
                    """,
                    (state.id, state.persona, payload, state.created_at, now_iso(), status),
                )

        self._run(work)

    def append_event(self, conversation_id: str, event_type: str, data: dict | None = None) -> None:
        def work():
            with self._conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO events (conversation_id, at, type, data_json) VALUES (%s, %s, %s, %s)",
                    (conversation_id, now_iso(), event_type, json.dumps(data or {}, ensure_ascii=False)),
                )

        self._run(work)

    def stats(self) -> dict:
        def work():
            with self._conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) AS n FROM conversations")
                total = cur.fetchone()["n"]
                cur.execute("SELECT COUNT(*) AS n FROM conversations WHERE status = 'handed_off'")
                handed = cur.fetchone()["n"]
                cur.execute("SELECT COUNT(*) AS n FROM events")
                events = cur.fetchone()["n"]
                cur.execute("SELECT value FROM counter WHERE name = 'persona'")
                counter = cur.fetchone()
            return {
                "backend": self.backend,
                "conversations": int(total),
                "handed_off": int(handed),
                "events": int(events),
                "persona_counter": int(counter["value"]) if counter else 0,
            }

        return self._run(work)

    def close(self) -> None:
        with self._lock:
            if self._conn is not None and not self._conn.closed:
                self._conn.close()
            self._conn = None


def open_state_store(
    *,
    path: Path | None = None,
    database_url: str | None = None,
) -> Any:
    """Prefer Postgres when DATABASE_URL is set; otherwise SQLite for local/tests."""
    url = (database_url or "").strip()
    if url:
        return PostgresStateStore(url)
    if path is None:
        raise ValueError("open_state_store requires path when database_url is empty")
    return SqliteStateStore(path)
