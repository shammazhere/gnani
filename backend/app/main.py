"""
Saakshi Backend - Worker-Held Voice Wage Ledger

Developer B: Product and Data
"""

import logging
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

# Add backend parent directory to path
backend_dir = Path(__file__).resolve().parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))
repository_dir = backend_dir.parent
if str(repository_dir) not in sys.path:
    sys.path.insert(0, str(repository_dir))

try:
    from backend.voice.router import (
        get_audio_store as get_voice_audio_store,
    )
    from backend.voice.router import (
        router as voice_router,
    )
except ModuleNotFoundError:
    from voice.router import (
        get_audio_store as get_voice_audio_store,
    )
    from voice.router import (
        router as voice_router,
    )

from app.config import Settings
from app.db import Base, engine, ensure_tables_ready
from app.routers import auth, contractor, entries, evidence
from app.services.audio_store import AppAudioStore

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

settings = Settings()


def create_application() -> FastAPI:
    """Create and configure the FastAPI application."""

    application = FastAPI(
        title="Saakshi API",
        description="Worker-Held Voice Wage Ledger",
        version="1.0.0",
        lifespan=lifespan,
    )

    # CORS middleware
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @application.middleware("http")
    async def ensure_serverless_schema(request: Request, call_next):
        if os.environ.get("VERCEL"):
            ensure_tables_ready()
        return await call_next(request)

    # Include routers
    application.include_router(auth.router, prefix="/api/auth", tags=["auth"])
    application.include_router(entries.router, prefix="/api/entries", tags=["entries"])
    application.include_router(
        contractor.router, prefix="/api/contractor", tags=["contractor"]
    )
    application.include_router(evidence.router, prefix="/api", tags=["evidence"])
    application.include_router(voice_router)

    audio_store = AppAudioStore(settings.AUDIO_STORAGE_PATH)
    application.dependency_overrides[get_voice_audio_store] = lambda: audio_store

    @application.get("/api/health", tags=["health"])
    async def health_check() -> dict[str, str]:
        return {"status": "ok"}

    dist_dir = (repository_dir / "frontend" / "dist").resolve()
    dist_index = dist_dir / "index.html"
    if dist_index.is_file():

        @application.get("/{full_path:path}", include_in_schema=False)
        async def serve_spa(full_path: str) -> FileResponse:
            clean = full_path.lstrip("/")
            if clean in {
                "api",
                "ws",
                "docs",
                "redoc",
                "openapi.json",
            } or clean.startswith(("api/", "ws/")):
                raise HTTPException(status_code=404, detail="Not Found")
            if clean:
                candidate = (dist_dir / clean).resolve()
                if candidate.is_relative_to(dist_dir) and candidate.is_file():
                    return FileResponse(candidate)
            return FileResponse(dist_index)

    else:

        @application.get("/", include_in_schema=False)
        async def api_root() -> dict[str, str]:
            return {"service": "saakshi-api", "status": "ok"}

    return application


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    # Startup
    logger.info("Starting Saakshi application...")

    # Create database tables
    logger.info("Creating database tables...")
    Base.metadata.create_all(bind=engine)

    logger.info("Database tables created successfully.")

    yield

    # Shutdown
    logger.info("Shutting down Saakshi application...")


app = create_application()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "backend.app.main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG,
    )
