from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent
ROOT_DIR = PACKAGE_DIR.parent
PROJECT_DIR = ROOT_DIR.parent
SEED_DIR = ROOT_DIR / "seed"

MODES = {"fake", "live", "dry_run", "shadow"}
CONTEXTS = {"full", "retrieval", "catalogue"}
ARCHES = {"v1", "v2"}
SEED_FILES = (
    "catalogue_primer.txt",
    "kb_index.json",
    "golden.jsonl",
)


class ConfigError(RuntimeError):
    pass


def on_vercel() -> bool:
    return os.getenv("VERCEL") == "1"


def load_dotenv(path: Path | None = None) -> None:
    env_path = path or ROOT_DIR / ".env"
    if not env_path.exists():
        return
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _flag(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def _float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


def _path(name: str, default: Path) -> Path:
    raw = os.getenv(name)
    path = Path(raw) if raw else default
    if not path.is_absolute():
        path = ROOT_DIR / path
    return path.resolve()


def _default_kb_dir() -> Path:
    bundled = ROOT_DIR / "kb"
    if bundled.is_dir():
        return bundled
    return PROJECT_DIR / "kb"


def _default_data_dir() -> Path:
    if on_vercel():
        return Path("/tmp/chatbot-data")
    return ROOT_DIR / "data"


def _default_out_dir() -> Path:
    if on_vercel():
        return Path("/tmp/chatbot-out")
    return ROOT_DIR / "out"


@dataclass(frozen=True)
class Config:
    kb_dir: Path
    data_dir: Path
    out_dir: Path
    mode: str
    allow_live: bool
    model: str
    base_url: str
    api_key: str
    timeout_s: float
    max_turns: int
    top_k: int
    salesiq_public_key: str
    allow_unverified: bool
    forward_on_handoff: bool
    handoff_operator: str
    ui_enabled: bool = True
    max_llm_calls: int = 0
    context: str = "catalogue"
    arch: str = "v2"
    database_url: str = ""
    vision_model: str = "gpt-4o-mini"
    blob_token: str = ""
    attachment_max_bytes: int = 8 * 1024 * 1024

    def __post_init__(self) -> None:
        if self.context not in CONTEXTS:
            raise ConfigError(f"BOT_CONTEXT must be one of {sorted(CONTEXTS)}, got {self.context!r}")
        if self.arch not in ARCHES:
            raise ConfigError(f"BOT_ARCH must be one of {sorted(ARCHES)}, got {self.arch!r}")

    @property
    def real_llm_enabled(self) -> bool:
        if self.mode == "fake":
            return False
        return self.allow_live and bool(self.api_key)

    def require_live(self) -> None:
        if self.mode == "fake":
            raise ConfigError("BOT_MODE=fake runs the heuristic composer; set BOT_MODE=live and BOT_ALLOW_LIVE=1")
        if not self.allow_live:
            raise ConfigError("BOT_ALLOW_LIVE=1 is required for any real paid LLM call")
        if not self.api_key:
            raise ConfigError("BOT_LLM_API_KEY is empty")

    @classmethod
    def load(cls, dotenv: bool = True) -> "Config":
        if dotenv:
            load_dotenv()
        mode = os.getenv("BOT_MODE", "fake").strip().lower()
        if mode not in MODES:
            raise ConfigError(f"BOT_MODE must be one of {sorted(MODES)}, got {mode!r}")
        # D-12 is locked. Live turns use the catalogue primer. BOT_CONTEXT is not a switch.
        context = "catalogue"
        arch = os.getenv("BOT_ARCH", "v2").strip().lower()
        if arch not in ARCHES:
            raise ConfigError(f"BOT_ARCH must be one of {sorted(ARCHES)}, got {arch!r}")
        return cls(
            kb_dir=_path("BOT_KB_DIR", _default_kb_dir()),
            data_dir=_path("BOT_DATA_DIR", _default_data_dir()),
            out_dir=_path("BOT_OUT_DIR", _default_out_dir()),
            mode=mode,
            allow_live=_flag("BOT_ALLOW_LIVE"),
            model=os.getenv("BOT_LLM_MODEL", "gpt-5-nano").strip(),
            base_url=os.getenv("BOT_LLM_BASE_URL", "https://api.openai.com/v1").rstrip("/"),
            api_key=os.getenv("BOT_LLM_API_KEY", "").strip(),
            timeout_s=_float("BOT_TIMEOUT_S", 6.0),
            max_turns=_int("BOT_MAX_TURNS", 12),
            top_k=_int("BOT_TOP_K", 6),
            salesiq_public_key=os.getenv("BOT_SALESIQ_PUBLIC_KEY", "").strip(),
            allow_unverified=_flag("BOT_ALLOW_UNVERIFIED"),
            forward_on_handoff=_flag("BOT_FORWARD_ON_HANDOFF"),
            handoff_operator=os.getenv("BOT_HANDOFF_OPERATOR", "johnhenry.it@print247.us").strip(),
            ui_enabled=_flag("BOT_UI", True),
            max_llm_calls=_int("BOT_MAX_LLM_CALLS", 0),
            context=context,
            arch=arch,
            database_url=(
                os.getenv("DATABASE_URL")
                or os.getenv("POSTGRES_URL")
                or os.getenv("BOT_DATABASE_URL")
                or ""
            ).strip(),
            vision_model=os.getenv("BOT_VISION_MODEL", "gpt-4o-mini").strip() or "gpt-4o-mini",
            blob_token=(
                os.getenv("BLOB_READ_WRITE_TOKEN")
                or os.getenv("BOT_BLOB_READ_WRITE_TOKEN")
                or ""
            ).strip(),
            attachment_max_bytes=_int("BOT_ATTACHMENT_MAX_BYTES", 8 * 1024 * 1024),
        )

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.out_dir.mkdir(parents=True, exist_ok=True)
        if SEED_DIR.is_dir():
            for name in SEED_FILES:
                src = SEED_DIR / name
                dest = self.data_dir / name
                if src.is_file() and not dest.exists():
                    shutil.copy2(src, dest)
