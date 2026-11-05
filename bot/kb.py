from __future__ import annotations

import json
import math
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

TOKEN = re.compile(r"[a-z0-9]+")
STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "has", "have",
    "if", "in", "is", "it", "its", "not", "of", "on", "or", "that", "the", "their",
    "this", "to", "was", "were", "will", "with", "you", "your", "we", "our", "can",
    "do", "does", "no", "so", "than", "then", "them", "they", "there", "what", "when",
    "which", "who", "how", "all", "any", "but", "into", "only", "also",
}

FAMILY_PATTERNS = {
    "bags": r"\b(bags?|pouch(?:es)?|mylar|stand[- ]?up|flat[- ]?bottom|zipper|tear notch|film|rolls?)\b",
    "boxes": r"\b(box(?:es)?|cartons?|mailers?|rigid|corrugated|tuck)\b",
    "labels": r"\b(labels?|stickers?|decals?|die[- ]?cut)\b",
    "banners": r"\b(banners?|pull[- ]?ups?|roll[- ]?ups?|pop[- ]?ups?|retractable|backdrops?)\b",
    "business_cards": r"\b(business cards?)\b",
    "print": r"\b(flyers?|brochures?|postcards?|booklets?|folders?|magnets?|invitations?|greeting cards?)\b",
}

INDEX_VERSION = 1


def tokenize(text: str) -> list[str]:
    return [t for t in TOKEN.findall(str(text).lower()) if len(t) > 1 and t not in STOPWORDS]


def parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end == -1:
        return {}, text
    header = text[3:end].strip("\n")
    body = text[end + 4 :].lstrip("\n")
    meta: dict[str, str] = {}
    for line in header.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        meta[key.strip()] = value.strip().strip('"').strip("'")
    return meta, body


def families_in(*texts: str) -> tuple[str, ...]:
    blob = " ".join(texts).lower()
    return tuple(name for name, pattern in FAMILY_PATTERNS.items() if re.search(pattern, blob))


@dataclass(frozen=True)
class Chunk:
    id: str
    doc_id: str
    title: str
    category: str
    source: str
    status: str
    last_reviewed: str
    section: str
    text: str
    families: tuple[str, ...] = field(default_factory=tuple)

    @property
    def search_text(self) -> str:
        return f"{self.title} {self.section} {self.text}"

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "doc_id": self.doc_id,
            "title": self.title,
            "category": self.category,
            "source": self.source,
            "status": self.status,
            "last_reviewed": self.last_reviewed,
            "section": self.section,
            "text": self.text,
            "families": list(self.families),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Chunk":
        return cls(**{**data, "families": tuple(data.get("families", ()))})


@dataclass(frozen=True)
class ScoredChunk:
    chunk: Chunk
    score: float


def _paragraphs(body: str) -> list[tuple[str, str]]:
    section = ""
    blocks: list[tuple[str, str]] = []
    current: list[str] = []

    def flush() -> None:
        nonlocal current
        if current:
            blocks.append((section, "\n".join(current).strip()))
            current = []

    for raw in body.splitlines():
        line = raw.strip()
        if line.startswith("#"):
            flush()
            section = line.lstrip("#").strip()
            continue
        if not line:
            flush()
            continue
        current.append(line)
    flush()
    return [(sec, text) for sec, text in blocks if text]


def _split_long(text: str, max_words: int) -> list[str]:
    words = text.split()
    if len(words) <= max_words:
        return [text]
    step = max(1, max_words - 20)
    return [" ".join(words[i : i + max_words]) for i in range(0, len(words), step)]


def chunk_document(path: Path, max_words: int = 130) -> list[Chunk]:
    raw = path.read_text(encoding="utf-8")
    meta, body = parse_frontmatter(raw)
    doc_id = meta.get("id") or path.stem
    title = meta.get("title") or path.stem
    category = meta.get("category") or path.parent.name
    status = (meta.get("status") or "draft").lower()
    source = meta.get("source", "")
    last_reviewed = meta.get("last_reviewed", "")

    groups: list[tuple[str, list[str]]] = []
    section = ""
    buf: list[str] = []
    size = 0
    for sec, text in _paragraphs(body):
        words = len(text.split())
        if buf and (sec != section or size + words > max_words):
            groups.append((section, buf))
            buf, size = [], 0
        section = sec
        for piece in _split_long(text, max_words):
            piece_words = len(piece.split())
            if buf and size + piece_words > max_words:
                groups.append((section, buf))
                buf, size = [], 0
            buf.append(piece)
            size += piece_words
    if buf:
        groups.append((section, buf))

    chunks: list[Chunk] = []
    for index, (section, pieces) in enumerate(groups, start=1):
        text = "\n".join(pieces).strip()
        if not text:
            continue
        chunks.append(
            Chunk(
                id=f"{doc_id}#{index}",
                doc_id=doc_id,
                title=title,
                category=category,
                source=source,
                status=status,
                last_reviewed=last_reviewed,
                section=section,
                text=text,
                families=families_in(doc_id, title, text),
            )
        )
    return chunks


class BM25:
    def __init__(self, texts: list[str], k1: float = 1.5, b: float = 0.75) -> None:
        self.k1 = k1
        self.b = b
        self.tokens = [tokenize(text) for text in texts]
        self.tfs = [Counter(tokens) for tokens in self.tokens]
        self.lengths = [len(tokens) for tokens in self.tokens]
        self.n = len(texts)
        self.avgdl = (sum(self.lengths) / self.n) if self.n else 0.0
        self.df: Counter[str] = Counter()
        for tf in self.tfs:
            self.df.update(tf.keys())

    def idf(self, term: str) -> float:
        df = self.df.get(term, 0)
        return math.log(1 + (self.n - df + 0.5) / (df + 0.5))

    def scores(self, query: str) -> list[float]:
        terms = tokenize(query)
        out: list[float] = []
        for tf, dl in zip(self.tfs, self.lengths):
            score = 0.0
            for term in terms:
                freq = tf.get(term, 0)
                if not freq:
                    continue
                denom = freq + self.k1 * (1 - self.b + self.b * (dl / self.avgdl if self.avgdl else 0))
                score += self.idf(term) * (freq * (self.k1 + 1)) / (denom or 1)
            out.append(score)
        return out


@dataclass
class KBIndex:
    chunks: list[Chunk]
    built_at: str = ""

    def __post_init__(self) -> None:
        self._bm25 = BM25([chunk.search_text for chunk in self.chunks])
        if not self.built_at:
            self.built_at = datetime.now(timezone.utc).isoformat()

    @classmethod
    def build(cls, kb_dir: Path) -> "KBIndex":
        if not kb_dir.exists():
            raise FileNotFoundError(f"KB directory not found: {kb_dir}")
        chunks: list[Chunk] = []
        for path in sorted(kb_dir.rglob("*.md")):
            if path.name.lower() == "readme.md":
                continue
            chunks.extend(chunk_document(path))
        if not chunks:
            raise ValueError(f"No markdown chunks found in {kb_dir}")
        return cls(chunks=chunks)

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": INDEX_VERSION,
            "built_at": self.built_at,
            "chunks": [chunk.to_dict() for chunk in self.chunks],
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> "KBIndex":
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("version") != INDEX_VERSION:
            raise ValueError(f"KB index version mismatch: {data.get('version')} != {INDEX_VERSION}")
        return cls(
            chunks=[Chunk.from_dict(item) for item in data["chunks"]],
            built_at=data.get("built_at", ""),
        )

    @classmethod
    def load_or_build(cls, kb_dir: Path, index_path: Path) -> "KBIndex":
        if index_path.exists():
            return cls.load(index_path)
        index = cls.build(kb_dir)
        index.save(index_path)
        return index

    def verified(self) -> list[Chunk]:
        return [chunk for chunk in self.chunks if chunk.status == "verified"]

    def search(
        self,
        query: str,
        top_k: int = 6,
        family: str | None = None,
        category: str | None = None,
        include_drafts: bool = False,
    ) -> list[ScoredChunk]:
        text = str(query or "").strip()
        if not text:
            return []
        base = self._bm25.scores(text)
        lowered = text.lower()
        scored: list[ScoredChunk] = []
        for chunk, score in zip(self.chunks, base):
            if chunk.status != "verified" and not include_drafts:
                continue
            if category and chunk.category != category:
                continue
            boost = 0.0
            title_words = set(tokenize(chunk.title))
            query_words = set(tokenize(text))
            overlap = title_words & query_words
            boost += min(3.0, 1.5 * len(overlap))
            if family and family in chunk.families:
                boost += 1.5 if len(chunk.families) == 1 else 0.5
            if len(lowered) > 8 and lowered in chunk.text.lower():
                boost += 2.0
            if score + boost <= 0:
                continue
            scored.append(ScoredChunk(chunk=chunk, score=score + boost))
        scored.sort(key=lambda item: item.score, reverse=True)

        picked: list[ScoredChunk] = []
        per_doc: Counter[str] = Counter()
        for item in scored:
            if per_doc[item.chunk.doc_id] >= 2:
                continue
            picked.append(item)
            per_doc[item.chunk.doc_id] += 1
            if len(picked) >= top_k:
                break
        return picked

    def stats(self) -> dict:
        docs = {chunk.doc_id for chunk in self.chunks}
        verified = sum(1 for chunk in self.chunks if chunk.status == "verified")
        return {
            "documents": len(docs),
            "chunks": len(self.chunks),
            "verified_chunks": verified,
            "draft_chunks": len(self.chunks) - verified,
            "built_at": self.built_at,
        }


def load_or_build(kb_dir: Path, data_dir: Path) -> KBIndex:
    """Load the site index when it is present, otherwise the smaller notes index.

    ``kb_index_v2.json`` is the 469-page scrape. Building it from ``kb_dir`` would
    replace those pages with the old notes, so a missing v2 file falls back instead.
    """
    site_index = data_dir / "kb_index_v2.json"
    if site_index.is_file():
        return KBIndex.load(site_index)
    return KBIndex.load_or_build(kb_dir, data_dir / "kb_index.json")
