"""Vercel ASGI entrypoint exposing FastAPI `app` from the `backend/` root."""

from app.main import app

__all__ = ["app"]
