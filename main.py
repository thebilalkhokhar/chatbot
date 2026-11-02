"""Vercel FastAPI entrypoint — exports `app` at a supported root filename."""

from bot.service import app

__all__ = ["app"]
