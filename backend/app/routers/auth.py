"""
Authentication router.
"""

from __future__ import annotations

import re
from collections import deque
from datetime import UTC, datetime, timedelta
from math import ceil
from threading import Lock
from time import monotonic
from typing import Annotated, Literal

import jwt
from fastapi import APIRouter, Depends, HTTPException, Request, status
from passlib.hash import bcrypt
from pydantic import BaseModel, Field, SecretStr, field_validator
from sqlalchemy.orm import Session

from app.config import Settings
from app.db import SessionLocal
from app.deps import CurrentWorker
from app.models import Worker


def get_db():
    """Get database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


settings = Settings()
router = APIRouter()


class LoginRateLimiter:
    """Track failed PIN checks per client IP for a short rolling window."""

    def __init__(self, max_attempts: int = 5, window_seconds: int = 60) -> None:
        self.max_attempts = max_attempts
        self.window_seconds = window_seconds
        self._failures: dict[str, deque[float]] = {}
        self._lock = Lock()

    def retry_after(self, client_ip: str) -> int | None:
        now = monotonic()
        with self._lock:
            failures = self._failures.get(client_ip)
            if failures is None:
                return None
            self._discard_expired(failures, now)
            if not failures:
                self._failures.pop(client_ip, None)
                return None
            if len(failures) < self.max_attempts:
                return None
            return max(1, ceil(self.window_seconds - (now - failures[0])))

    def record_failure(self, client_ip: str) -> None:
        now = monotonic()
        with self._lock:
            failures = self._failures.setdefault(client_ip, deque())
            self._discard_expired(failures, now)
            failures.append(now)
            if len(self._failures) > 10_000:
                oldest_ip = next(iter(self._failures))
                if oldest_ip != client_ip:
                    self._failures.pop(oldest_ip, None)

    def reset(self) -> None:
        with self._lock:
            self._failures.clear()

    def _discard_expired(self, failures: deque[float], now: float) -> None:
        while failures and now - failures[0] >= self.window_seconds:
            failures.popleft()


login_rate_limiter = LoginRateLimiter()


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _check_pin_rate_limit(request: Request) -> str:
    client_ip = _client_ip(request)
    retry_after = login_rate_limiter.retry_after(client_ip)
    if retry_after is not None:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many PIN attempts. Try again shortly.",
            headers={"Retry-After": str(retry_after)},
        )
    return client_ip


def _record_pin_failure(client_ip: str) -> None:
    login_rate_limiter.record_failure(client_ip)


# Pydantic models
class WorkerCreate(BaseModel):
    alias: str = Field(..., min_length=3, max_length=50)
    pin: str = Field(..., min_length=4)
    language: str = "hi-IN"
    consent_audio_uri: str | None = None
    consent_text_version: str | None = None
    consent_at: datetime | None = None


class WorkerLogin(BaseModel):
    alias: str = Field(..., min_length=3, max_length=50)
    pin: str = Field(..., min_length=4)


class ChangePinRequest(BaseModel):
    current_pin: SecretStr = Field(..., min_length=4, max_length=72)
    new_pin: SecretStr = Field(..., min_length=4, max_length=4)

    @field_validator("new_pin")
    @classmethod
    def require_four_digits(cls, pin: SecretStr) -> SecretStr:
        if re.fullmatch(r"[0-9]{4}", pin.get_secret_value()) is None:
            raise ValueError("New PIN must contain exactly four digits")
        return pin


class LanguageUpdateRequest(BaseModel):
    language: Literal["hi-IN", "kn-IN", "bn-IN", "en-IN"]


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    worker_id: int
    language: str = "hi-IN"


def create_access_token(data: dict, expires_delta: timedelta | None = None) -> str:
    """Create a JWT access token."""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(UTC) + expires_delta
    else:
        expire = datetime.now(UTC) + timedelta(
            minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES
        )
    to_encode.update({"exp": expire})
    return jwt.encode(
        to_encode,
        settings.SECRET_KEY.get_secret_value(),
        algorithm="HS256",
    )


def verify_pin(alias: str, pin: str, db) -> Worker | None:
    """Verify worker PIN."""
    worker = db.query(Worker).filter(Worker.alias == alias).first()
    if not worker:
        return None
    if getattr(worker, 'is_active', True) is False:
        return None
    if not bcrypt.verify(pin, worker.pin_hash):
        return None
    return worker


@router.post(
    "/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED
)
async def register_worker(
    worker_data: WorkerCreate,
    db: Annotated[Session, Depends(get_db)],
) -> TokenResponse:
    """Register a new worker."""
    # Check if alias already exists
    existing = db.query(Worker).filter(Worker.alias == worker_data.alias).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Alias already registered"
        )

    # Hash the PIN before storing
    pin_hash = bcrypt.hash(worker_data.pin)

    # Create worker with hashed PIN
    worker = Worker(
        alias=worker_data.alias,
        pin_hash=pin_hash,
        language=worker_data.language,
        consent_audio_uri=worker_data.consent_audio_uri,
        consent_text_version=worker_data.consent_text_version,
        consent_at=worker_data.consent_at,
    )
    db.add(worker)
    db.commit()
    db.refresh(worker)

    # Create access token
    access_token = create_access_token(
        data={"worker_id": worker.id},
        expires_delta=timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
    )

    return TokenResponse(
        access_token=access_token,
        token_type="bearer",
        worker_id=worker.id,
        language=worker.language,
    )


@router.post("/login", response_model=TokenResponse)
async def login_worker(
    login_data: WorkerLogin,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
) -> TokenResponse:
    """Login a worker."""
    client_ip = _check_pin_rate_limit(request)
    worker = verify_pin(login_data.alias, login_data.pin, db)
    if not worker:
        _record_pin_failure(client_ip)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid alias or PIN",
            headers={"WWW-Authenticate": "Bearer"},
        )
    access_token = create_access_token(
        data={"worker_id": worker.id},
        expires_delta=timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
    )

    return TokenResponse(
        access_token=access_token,
        token_type="bearer",
        worker_id=worker.id,
        language=worker.language,
    )


@router.post("/verify-pin")
async def verify_worker_pin(
    login_data: WorkerLogin,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    """Verify worker PIN (for PIN lock screen)."""
    client_ip = _check_pin_rate_limit(request)
    worker = verify_pin(login_data.alias, login_data.pin, db)
    if not worker:
        _record_pin_failure(client_ip)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid alias or PIN"
        )
    return {"valid": True, "worker_id": worker.id}


@router.post("/change-pin")
async def change_worker_pin(
    pin_data: ChangePinRequest,
    request: Request,
    worker_id: CurrentWorker,
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, str]:
    """Change the authenticated worker's PIN after verifying the current PIN."""
    client_ip = _check_pin_rate_limit(request)
    worker = db.query(Worker).filter(Worker.id == worker_id).first()
    if worker is None or getattr(worker, 'is_active', True) is False:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Current PIN verification failed or worker account is inactive",
        )
    if not bcrypt.verify(
        pin_data.current_pin.get_secret_value(),
        worker.pin_hash,
    ):
        _record_pin_failure(client_ip)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Current PIN verification failed",
        )

    worker.pin_hash = bcrypt.hash(pin_data.new_pin.get_secret_value())
    db.commit()
    return {"status": "updated"}


@router.patch("/language")
async def update_worker_language(
    payload: LanguageUpdateRequest,
    worker_id: CurrentWorker,
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, str]:
    """Update the authenticated worker's preferred UI/voice language."""
    worker = db.query(Worker).filter(Worker.id == worker_id).first()
    if worker is None or getattr(worker, 'is_active', True) is False:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Worker not found",
        )
    worker.language = payload.language
    db.commit()
    return {"language": worker.language}
