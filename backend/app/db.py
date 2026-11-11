"""
Database configuration and session management.
"""

from __future__ import annotations

from threading import Lock

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker

try:
    from app.config import Settings
    from app.models import Base
except ImportError:
    from config import Settings
    from models import Base

__all__ = [
    "Base",
    "SessionLocal",
    "engine",
    "ensure_schema_columns",
    "ensure_tables_ready",
    "get_db",
    "normalize_database_url",
    "settings",
]

settings = Settings()
_tables_lock = Lock()
_tables_ready = False


def normalize_database_url(raw_url: str) -> str:
    """Normalize PostgreSQL/Neon connection strings for SQLAlchemy and installed drivers."""
    url = raw_url.strip()
    if len(url) >= 2 and url[0] == url[-1] and url[0] in ("'", '"'):
        url = url[1:-1].strip()
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://") :]
    url = url.replace("postgresql+asyncpg://", "postgresql://", 1)
    if url.startswith("postgresql://"):
        try:
            import psycopg2  # noqa: F401
        except ImportError:
            try:
                import psycopg  # noqa: F401

                url = "postgresql+psycopg://" + url[len("postgresql://") :]
            except ImportError:
                pass
    return url


database_url = normalize_database_url(settings.DATABASE_URL)
is_sqlite = database_url.startswith("sqlite")
engine_kwargs: dict = {
    "echo": settings.DEBUG,
    "connect_args": {"check_same_thread": False} if is_sqlite else {},
}
if not is_sqlite:
    # Guard against serverless PostgreSQL (Neon) closing idle SSL connections.
    engine_kwargs["pool_pre_ping"] = True
    engine_kwargs["pool_recycle"] = 300

engine = create_engine(database_url, **engine_kwargs)

# Session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def ensure_schema_columns(bind_engine=engine) -> None:
    """Backfill columns added after 001_initial_schema on pre-existing databases."""
    inspector = inspect(bind_engine)
    if not inspector.has_table("workers"):
        return
    cols = {col["name"] for col in inspector.get_columns("workers")}
    if "is_active" not in cols:
        if bind_engine.dialect.name == "sqlite":
            stmt = "ALTER TABLE workers ADD COLUMN is_active BOOLEAN NOT NULL DEFAULT 1"
        else:
            stmt = (
                "ALTER TABLE workers "
                "ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT TRUE"
            )
        with bind_engine.begin() as conn:
            conn.execute(text(stmt))


def ensure_tables_ready() -> None:
    """Create schema tables once per cold start when ASGI lifespan is bypassed."""
    global _tables_ready
    if _tables_ready:
        return
    with _tables_lock:
        if _tables_ready:
            return
        Base.metadata.create_all(bind=engine)
        ensure_schema_columns(engine)
        _tables_ready = True


def get_db():
    """Get database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
