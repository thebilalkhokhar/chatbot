from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from chatbot.bot.config import Config
from chatbot.bot.kb import KBIndex
from chatbot.bot.orchestrator import Orchestrator

KB_DIR = ROOT / "kb"


@pytest.fixture(scope="session")
def kb_index() -> KBIndex:
    return KBIndex.build(KB_DIR)


@pytest.fixture()
def config(tmp_path: Path) -> Config:
    return Config(
        kb_dir=KB_DIR,
        data_dir=tmp_path / "data",
        out_dir=tmp_path / "out",
        mode="fake",
        allow_live=False,
        model="gpt-5-mini",
        base_url="https://api.openai.com/v1",
        api_key="",
        timeout_s=2.0,
        max_turns=12,
        top_k=4,
        salesiq_public_key="",
        allow_unverified=True,
        forward_on_handoff=False,
        handoff_operator="ops@print247.us",
    )


@pytest.fixture()
def orchestrator(config: Config, kb_index: KBIndex, tmp_path: Path) -> Orchestrator:
    engine = Orchestrator(
        config,
        store_path=tmp_path / "state.sqlite3",
        index=kb_index,
        examples=[],
    )
    yield engine
    engine.close()
