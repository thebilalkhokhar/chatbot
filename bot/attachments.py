from __future__ import annotations

import json
import re
import sqlite3
import threading
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from .state import now_iso

ALLOWED_MIME = {
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
}
MAX_ATTACHMENT_BYTES_DEFAULT = 8 * 1024 * 1024


class AttachmentError(ValueError):
    pass


@dataclass
class Attachment:
    id: str
    conversation_id: str
    mime: str
    size_bytes: int
    storage_backend: str
    storage_key: str
    url: str = ""
    vision_summary: str = ""
    vision: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=now_iso)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "conversation_id": self.conversation_id,
            "mime": self.mime,
            "size_bytes": self.size_bytes,
            "storage_backend": self.storage_backend,
            "storage_key": self.storage_key,
            "url": self.url,
            "vision_summary": self.vision_summary,
            "vision": dict(self.vision),
            "created_at": self.created_at,
        }


class ObjectStore(Protocol):
    name: str

    def put(self, key: str, data: bytes, mime: str) -> str:
        """Persist bytes and return a retrievable URL or path token."""

    def get(self, key: str) -> bytes:
        ...


class LocalObjectStore:
    """Filesystem object store under data/uploads — default for local and tests."""

    name = "local"

    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def put(self, key: str, data: bytes, mime: str) -> str:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path.as_uri()

    def get(self, key: str) -> bytes:
        path = self._path(key)
        if not path.is_file():
            raise AttachmentError(f"attachment missing: {key}")
        return path.read_bytes()

    def _path(self, key: str) -> Path:
        safe = Path(key)
        if safe.is_absolute() or ".." in safe.parts:
            raise AttachmentError("invalid storage key")
        return self.root / safe


class VercelBlobStore:
    """Vercel Blob via REST. Used when BLOB_READ_WRITE_TOKEN is set.

    Same Attachment API as local disk, so a future SalesIQ ingress only needs to
    call save() — no new storage layer.
    """

    name = "vercel_blob"

    def __init__(self, token: str, *, timeout_s: float = 20.0) -> None:
        self.token = token.strip()
        self.timeout_s = timeout_s
        if not self.token:
            raise AttachmentError("BLOB_READ_WRITE_TOKEN is empty")

    def put(self, key: str, data: bytes, mime: str) -> str:
        import httpx

        pathname = key.lstrip("/")
        url = f"https://vercel.com/api/blob?pathname={pathname}&access=private"
        headers = {
            "Authorization": f"Bearer {self.token}",
            "X-API-Version": "7",
            "Content-Type": mime or "application/octet-stream",
        }
        try:
            with httpx.Client(timeout=self.timeout_s) as client:
                response = client.put(url, headers=headers, content=data)
        except httpx.HTTPError as error:
            raise AttachmentError(f"blob upload failed: {error}") from error
        if response.status_code >= 400:
            raise AttachmentError(f"blob upload returned {response.status_code}: {response.text[:300]}")
        body = response.json()
        return str(body.get("url") or body.get("downloadUrl") or "")

    def get(self, key: str) -> bytes:
        # Private blob reads go through the stored URL on the Attachment row, not the key alone.
        raise AttachmentError("vercel blob get requires the stored URL; use AttachmentStore.read")


def normalise_mime(mime: str) -> str:
    value = str(mime or "").strip().lower().split(";")[0].strip()
    if value == "image/jpg":
        return "image/jpeg"
    return value


def validate_image(data: bytes, mime: str, *, max_bytes: int) -> str:
    if not data:
        raise AttachmentError("empty image")
    if len(data) > max_bytes:
        raise AttachmentError(f"image too large (max {max_bytes} bytes)")
    normalised = normalise_mime(mime)
    if normalised not in ALLOWED_MIME:
        raise AttachmentError(f"unsupported image type: {mime or 'unknown'}")
    # Light magic-byte check so a renamed .exe cannot pass as png.
    if normalised == "image/png" and not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise AttachmentError("image bytes do not match image/png")
    if normalised == "image/jpeg" and not data.startswith(b"\xff\xd8"):
        raise AttachmentError("image bytes do not match image/jpeg")
    if normalised == "image/webp" and not (data[:4] == b"RIFF" and data[8:12] == b"WEBP"):
        raise AttachmentError("image bytes do not match image/webp")
    if normalised == "image/gif" and not data.startswith((b"GIF87a", b"GIF89a")):
        raise AttachmentError("image bytes do not match image/gif")
    return normalised


class AttachmentStore:
    """Object bytes + attachment metadata. Backend-agnostic for future webhook ingress."""

    def __init__(
        self,
        *,
        object_store: ObjectStore,
        path: Path | None = None,
        database_url: str = "",
        max_bytes: int = MAX_ATTACHMENT_BYTES_DEFAULT,
    ) -> None:
        self.objects = object_store
        self.max_bytes = max_bytes
        self._lock = threading.RLock()
        self._pg = None
        self._sqlite: sqlite3.Connection | None = None
        url = (database_url or "").strip()
        if url:
            import psycopg
            from psycopg.rows import dict_row

            self._pg = psycopg.connect(url, row_factory=dict_row, autocommit=False)
            self._init_postgres()
        else:
            if path is None:
                raise ValueError("AttachmentStore requires path when database_url is empty")
            path.parent.mkdir(parents=True, exist_ok=True)
            self._sqlite = sqlite3.connect(str(path), check_same_thread=False)
            self._sqlite.row_factory = sqlite3.Row
            self._init_sqlite()

    def close(self) -> None:
        with self._lock:
            if self._sqlite is not None:
                self._sqlite.close()
                self._sqlite = None
            if self._pg is not None:
                self._pg.close()
                self._pg = None

    def save(
        self,
        conversation_id: str,
        data: bytes,
        mime: str,
        *,
        attachment_id: str | None = None,
    ) -> Attachment:
        conversation_id = str(conversation_id or "").strip()
        if not conversation_id:
            raise AttachmentError("conversation_id required")
        normalised = validate_image(data, mime, max_bytes=self.max_bytes)
        ext = ALLOWED_MIME[normalised]
        attachment_id = attachment_id or uuid.uuid4().hex
        key = f"attachments/{_safe_segment(conversation_id)}/{attachment_id}{ext}"
        url = self.objects.put(key, data, normalised)
        record = Attachment(
            id=attachment_id,
            conversation_id=conversation_id,
            mime=normalised,
            size_bytes=len(data),
            storage_backend=self.objects.name,
            storage_key=key,
            url=url,
        )
        self._insert(record)
        return record

    def set_vision(self, attachment_id: str, summary: str, vision: dict[str, Any] | None = None) -> None:
        with self._lock:
            payload = json.dumps(vision or {}, ensure_ascii=False)
            if self._sqlite is not None:
                with self._sqlite:
                    self._sqlite.execute(
                        "UPDATE attachments SET vision_summary = ?, vision_json = ? WHERE id = ?",
                        (str(summary or ""), payload, attachment_id),
                    )
                return
            assert self._pg is not None
            with self._pg.cursor() as cur:
                cur.execute(
                    "UPDATE attachments SET vision_summary = %s, vision_json = %s WHERE id = %s",
                    (str(summary or ""), payload, attachment_id),
                )
                self._pg.commit()

    def get(self, attachment_id: str) -> Attachment | None:
        with self._lock:
            if self._sqlite is not None:
                row = self._sqlite.execute(
                    "SELECT * FROM attachments WHERE id = ?", (attachment_id,)
                ).fetchone()
                return _row_to_attachment(row) if row else None
            assert self._pg is not None
            with self._pg.cursor() as cur:
                cur.execute("SELECT * FROM attachments WHERE id = %s", (attachment_id,))
                row = cur.fetchone()
                return _row_to_attachment(row) if row else None

    def list_for(self, conversation_id: str) -> list[Attachment]:
        with self._lock:
            if self._sqlite is not None:
                rows = self._sqlite.execute(
                    "SELECT * FROM attachments WHERE conversation_id = ? ORDER BY created_at ASC",
                    (conversation_id,),
                ).fetchall()
                return [_row_to_attachment(row) for row in rows]
            assert self._pg is not None
            with self._pg.cursor() as cur:
                cur.execute(
                    "SELECT * FROM attachments WHERE conversation_id = %s ORDER BY created_at ASC",
                    (conversation_id,),
                )
                return [_row_to_attachment(row) for row in cur.fetchall()]

    def read_bytes(self, attachment: Attachment) -> bytes:
        if attachment.storage_backend == "local" or isinstance(self.objects, LocalObjectStore):
            return self.objects.get(attachment.storage_key)
        if attachment.url:
            import httpx

            headers = {}
            if isinstance(self.objects, VercelBlobStore):
                headers["Authorization"] = f"Bearer {self.objects.token}"
            with httpx.Client(timeout=20.0) as client:
                response = client.get(attachment.url, headers=headers)
            if response.status_code >= 400:
                raise AttachmentError(f"failed to download attachment: {response.status_code}")
            return response.content
        return self.objects.get(attachment.storage_key)

    def _insert(self, record: Attachment) -> None:
        with self._lock:
            if self._sqlite is not None:
                with self._sqlite:
                    self._sqlite.execute(
                        """
                        INSERT INTO attachments (
                            id, conversation_id, mime, size_bytes, storage_backend,
                            storage_key, url, vision_summary, vision_json, created_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            record.id,
                            record.conversation_id,
                            record.mime,
                            record.size_bytes,
                            record.storage_backend,
                            record.storage_key,
                            record.url,
                            record.vision_summary,
                            json.dumps(record.vision, ensure_ascii=False),
                            record.created_at,
                        ),
                    )
                return
            assert self._pg is not None
            with self._pg.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO attachments (
                        id, conversation_id, mime, size_bytes, storage_backend,
                        storage_key, url, vision_summary, vision_json, created_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        record.id,
                        record.conversation_id,
                        record.mime,
                        record.size_bytes,
                        record.storage_backend,
                        record.storage_key,
                        record.url,
                        record.vision_summary,
                        json.dumps(record.vision, ensure_ascii=False),
                        record.created_at,
                    ),
                )
                self._pg.commit()

    def _init_sqlite(self) -> None:
        assert self._sqlite is not None
        with self._lock, self._sqlite:
            self._sqlite.execute(
                """
                CREATE TABLE IF NOT EXISTS attachments (
                    id TEXT PRIMARY KEY,
                    conversation_id TEXT NOT NULL,
                    mime TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL,
                    storage_backend TEXT NOT NULL,
                    storage_key TEXT NOT NULL,
                    url TEXT NOT NULL DEFAULT '',
                    vision_summary TEXT NOT NULL DEFAULT '',
                    vision_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL
                )
                """
            )
            self._sqlite.execute(
                "CREATE INDEX IF NOT EXISTS idx_attachments_conversation ON attachments(conversation_id)"
            )

    def _init_postgres(self) -> None:
        assert self._pg is not None
        with self._lock, self._pg.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS attachments (
                    id TEXT PRIMARY KEY,
                    conversation_id TEXT NOT NULL,
                    mime TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL,
                    storage_backend TEXT NOT NULL,
                    storage_key TEXT NOT NULL,
                    url TEXT NOT NULL DEFAULT '',
                    vision_summary TEXT NOT NULL DEFAULT '',
                    vision_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL
                )
                """
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_attachments_conversation ON attachments(conversation_id)"
            )
            self._pg.commit()


def open_attachment_store(
    *,
    data_dir: Path,
    database_url: str = "",
    blob_token: str = "",
    max_bytes: int = MAX_ATTACHMENT_BYTES_DEFAULT,
) -> AttachmentStore:
    token = (blob_token or "").strip()
    if token:
        objects: ObjectStore = VercelBlobStore(token)
    else:
        objects = LocalObjectStore(data_dir / "uploads")
    meta_path = data_dir / "attachments.sqlite3"
    return AttachmentStore(
        object_store=objects,
        path=None if database_url.strip() else meta_path,
        database_url=database_url,
        max_bytes=max_bytes,
    )


def _safe_segment(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("._") or "unknown"
    return cleaned[:120]


def _row_to_attachment(row: Any) -> Attachment:
    data = dict(row)
    vision_raw = data.get("vision_json") or "{}"
    if isinstance(vision_raw, dict):
        vision = vision_raw
    else:
        try:
            vision = json.loads(vision_raw)
        except json.JSONDecodeError:
            vision = {}
    return Attachment(
        id=str(data["id"]),
        conversation_id=str(data["conversation_id"]),
        mime=str(data["mime"]),
        size_bytes=int(data["size_bytes"]),
        storage_backend=str(data["storage_backend"]),
        storage_key=str(data["storage_key"]),
        url=str(data.get("url") or ""),
        vision_summary=str(data.get("vision_summary") or ""),
        vision=vision if isinstance(vision, dict) else {},
        created_at=str(data.get("created_at") or ""),
    )
