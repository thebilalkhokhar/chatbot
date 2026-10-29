from __future__ import annotations

from pathlib import Path

from chatbot.bot.config import Config

ROOT = Path(__file__).resolve().parents[2]


def test_relative_env_paths_are_anchored_to_the_chatbot_folder(monkeypatch):
    monkeypatch.setenv("BOT_KB_DIR", "../kb")
    monkeypatch.setenv("BOT_DATA_DIR", "data")
    monkeypatch.setenv("BOT_OUT_DIR", "out")
    monkeypatch.delenv("BOT_MODE", raising=False)

    config = Config.load(dotenv=False)

    assert config.kb_dir == (ROOT / "kb").resolve()
    assert config.data_dir == (ROOT / "chatbot" / "data").resolve()
    assert config.out_dir == (ROOT / "chatbot" / "out").resolve()
