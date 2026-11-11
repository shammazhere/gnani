"""
Entries router - CRUD for wage entries.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import secrets
import uuid
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Annotated

import jwt
from contracts.voice_interface import ExtractContext
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.config import Settings
from app.db import SessionLocal
from app.deps import CurrentWorker, VoiceServiceDep
from app.models import Counterparty, Entry, EntryStatusLog, ShareToken, Worker
from app.services.hashchain import HashChainService

settings = Settings()
router = APIRouter()


def get_db():
    """Get database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_hashchain_service() -> HashChainService:
    """Get hash chain service instance"""
    return HashChainService()


HashChainServiceDep = Annotated[HashChainService, Depends(get_hashchain_service)]


class EntryCreate(BaseModel):
    audio_ref: str
    transcript: str
    lang: str
    audio_sha256: str | None = None
    work_date: str | None = None
    site_name: str | None = None
    counterparty_name: str | None = None
    work_type: str | None = None
    hours: float | None = None
    days: float | None = None
    agreed_inr: float | None = None
    paid_inr: float | None = None


class VoiceDraftReview(BaseModel):
    draft_token: str
    transcript: str
    work_date: str | None
    site_name: str | None
    counterparty_name: str | None
    work_type: str | None
    hours: float | None
    days: float | None
    agreed_amount_inr: int | None
    paid_amount_inr: int | None
    due_amount_inr: int | None
    language: str
    detected_language_code: str | None
    field_confidence: dict[str, float]
    needs_clarification: list[str]
    clarification_question: str | None
    voice_mode: str


class ConfirmVoiceDraft(BaseModel):
    draft_token: str
    audio_base64: str = Field(..., max_length=12_000_000)
    work_date: date
    site_name: str | None = Field(default=None, max_length=200)
    counterparty_name: str | None = Field(default=None, max_length=200)
    work_type: str | None = Field(default=None, max_length=200)
    hours: float | None = Field(default=None, ge=0)
    days: float | None = Field(default=None, ge=0)
    agreed_amount_inr: int = Field(..., ge=0)
    paid_amount_inr: int = Field(..., ge=0)
    language: str = Field(..., min_length=2, max_length=16)


class EntryCorrect(BaseModel):
    audio_ref: str
    transcript: str
    lang: str


class EntryResponse(BaseModel):
    id: int
    work_date: str
    site_name: str | None
    counterparty_name: str | None
    work_type: str | None = None
    hours: float | None
    days: float | None
    agreed_inr: float
    paid_inr: float
    due_inr: float
    language: str
    transcript: str | None
    status: str
    created_at: datetime


class _WorkerExtractContext(ExtractContext):
    def __init__(
        self,
        worker_id: int,
        known_counterparties: list[str],
        known_sites: list[str],
    ) -> None:
        self._worker_id = str(worker_id)
        self._known_counterparties = known_counterparties
        self._known_sites = known_sites

    @property
    def worker_id(self) -> str:
        return self._worker_id

    @property
    def known_counterparties(self) -> list[str]:
        return self._known_counterparties

    @property
    def known_sites(self) -> list[str]:
        return self._known_sites


def _entry_response(entry: Entry) -> EntryResponse:
    return EntryResponse(
        id=entry.id,
        work_date=entry.work_date,
        site_name=entry.site_name,
        counterparty_name=entry.counterparty_name,
        work_type=entry.work_type,
        hours=float(entry.hours) if entry.hours is not None else None,
        days=float(entry.days) if entry.days is not None else None,
        agreed_inr=float(entry.agreed_inr),
        paid_inr=float(entry.paid_inr),
        due_inr=float(entry.due_inr),
        language=entry.language,
        transcript=entry.transcript,
        status=entry.status,
        created_at=entry.created_at,
    )


_AUDIO_TYPES = {
    "audio/webm": ".webm",
    "audio/ogg": ".ogg",
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
    "audio/wave": ".wav",
    "audio/mp4": ".m4a",
    "audio/mpeg": ".mp3",
}
_MAX_AUDIO_BYTES = 8 * 1024 * 1024


def _create_json_entry_draft(
    entry_data: EntryCreate,
    current_worker_id: int,
    hashchain_service: HashChainService,
    db,
) -> EntryResponse:
    last_entry = (
        db.query(Entry)
        .filter(
            Entry.worker_id == current_worker_id,
            Entry.entry_hash.isnot(None),
            Entry.entry_hash != "",
        )
        .order_by(Entry.created_at.desc(), Entry.id.desc())
        .first()
    )
    prev_hash = last_entry.entry_hash if last_entry else hashchain_service.GENESIS_HASH

    # Always compute due amount in code (never trust client-supplied due_inr).
    agreed_amount = max(0.0, float(entry_data.agreed_inr or 0.0))
    paid_amount = max(0.0, float(entry_data.paid_inr or 0.0))
    due_amount = max(0.0, round(agreed_amount - paid_amount, 2))
    transcript_sha256 = (
        hashlib.sha256(entry_data.transcript.encode("utf-8")).hexdigest()
        if entry_data.transcript
        else ""
    )

    entry = Entry(
        worker_id=current_worker_id,
        counterparty_id=None,
        work_date=(entry_data.work_date or datetime.now(UTC).strftime("%Y-%m-%d")),
        site_name=entry_data.site_name or "",
        counterparty_name=entry_data.counterparty_name or "",
        work_type=entry_data.work_type,
        hours=entry_data.hours if entry_data.hours is not None else 0,
        days=entry_data.days if entry_data.days is not None else 0,
        agreed_inr=agreed_amount,
        paid_inr=paid_amount,
        due_inr=due_amount,
        language=entry_data.lang,
        transcript=entry_data.transcript,
        transcript_sha256=transcript_sha256,
        audio_uri=entry_data.audio_ref,
        audio_sha256=entry_data.audio_sha256 or "",
        prev_hash=prev_hash,
        entry_hash="",
        status=Entry.STATUS_DRAFT,
        corrects_entry_id=None,
    )

    db.add(entry)
    db.commit()
    db.refresh(entry)
    return _entry_response(entry)


@router.post("/draft", response_model=VoiceDraftReview | EntryResponse)
async def create_entry_draft(
    request: Request,
    current_worker_id: CurrentWorker,
    voice_service: VoiceServiceDep,
    hashchain_service: HashChainServiceDep,
    db: Annotated[Session, Depends(get_db)],
) -> VoiceDraftReview | JSONResponse:
    """Handle either streaming-session JSON draft persistence or raw audio draft review."""
    # Validate worker is active
    worker = db.query(Worker).filter(Worker.id == current_worker_id).first()
    if not worker or not worker.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Worker not found or account is inactive",
        )
    content_type = (
        request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    )
    if content_type == "application/json":
        raw_body = await request.body()
        try:
            payload = json.loads(raw_body)
        except json.JSONDecodeError as error:
            raise HTTPException(
                status_code=415, detail="Unsupported audio format"
            ) from error
        if not isinstance(payload, dict):
            raise HTTPException(status_code=415, detail="Unsupported audio format")
        try:
            entry_data = EntryCreate.model_validate(payload)
        except ValidationError as error:
            raise HTTPException(status_code=422, detail=error.errors()) from error
        created = _create_json_entry_draft(
            entry_data, current_worker_id, hashchain_service, db
        )
        return JSONResponse(status_code=201, content=created.model_dump(mode="json"))

    if content_type not in _AUDIO_TYPES:
        raise HTTPException(status_code=415, detail="Unsupported audio format")

    if not hasattr(voice_service, "transcribe_audio"):
        raise HTTPException(
            status_code=503,
            detail="Configured voice implementation does not support batch audio transcription",
        )

    audio_chunks: list[bytes] = []
    audio_size = 0
    async for chunk in request.stream():
        audio_size += len(chunk)
        if audio_size > _MAX_AUDIO_BYTES:
            raise HTTPException(status_code=413, detail="Audio exceeds the 8 MB limit")
        audio_chunks.append(chunk)
    audio = b"".join(audio_chunks)
    if not audio:
        raise HTTPException(status_code=400, detail="Audio is empty")

    worker = db.query(Worker).filter(Worker.id == current_worker_id).first()
    if worker is None:
        raise HTTPException(status_code=401, detail="Worker session is unavailable")

    try:
        transcription = await voice_service.transcribe_audio(
            audio=audio,
            content_type=content_type,
            lang=worker.language or "hi-IN",
        )
        transcript = transcription.transcript.strip()
        if not transcript:
            raise ValueError("Transcription returned no text")

        known_counterparties = [
            row[0]
            for row in db.query(Counterparty.display_name)
            .filter(Counterparty.worker_id == current_worker_id)
            .order_by(Counterparty.display_name)
            .all()
        ]
        known_sites = [
            row[0]
            for row in db.query(Entry.site_name)
            .filter(
                Entry.worker_id == current_worker_id,
                Entry.site_name.isnot(None),
                Entry.site_name != "",
            )
            .distinct()
            .all()
        ]
        extracted = await voice_service.extract_entry(
            transcript=transcript,
            lang=transcription.detected_language_code or worker.language or "hi-IN",
            ctx=_WorkerExtractContext(
                current_worker_id,
                known_counterparties,
                known_sites,
            ),
        )
    except ValueError as error:
        raise HTTPException(
            status_code=422,
            detail="Audio could not be transcribed or understood; please record again",
        ) from error

    needs_clarification = list(extracted.needs_clarification)
    if extracted.work_date is not None:
        try:
            date.fromisoformat(extracted.work_date)
        except ValueError:
            if "work_date" not in needs_clarification:
                needs_clarification.append("work_date")
    for required_field, value in (
        ("work_date", extracted.work_date),
        ("agreed_amount_inr", extracted.agreed_amount_inr),
        ("paid_amount_inr", extracted.paid_amount_inr),
    ):
        if value is None and required_field not in needs_clarification:
            needs_clarification.append(required_field)

    for field_name, value in (
        ("agreed_amount_inr", extracted.agreed_amount_inr),
        ("paid_amount_inr", extracted.paid_amount_inr),
    ):
        if value is not None and value < 0 and field_name not in needs_clarification:
            needs_clarification.append(field_name)

    due_amount = None
    if (
        extracted.agreed_amount_inr is not None
        and extracted.paid_amount_inr is not None
    ):
        candidate_due = extracted.agreed_amount_inr - extracted.paid_amount_inr
        if candidate_due >= 0:
            due_amount = candidate_due
        elif "paid_amount_inr" not in needs_clarification:
            needs_clarification.append("paid_amount_inr")

    question = extracted.clarification_question
    if needs_clarification and not question:
        question = "Please review the highlighted details before confirming."

    draft_token = jwt.encode(
        {
            "draft": True,
            "worker_id": current_worker_id,
            "transcript": transcript,
            "audio_sha256": hashlib.sha256(audio).hexdigest(),
            "content_type": content_type,
            "voice_mode": settings.VOICE_IMPL.lower(),
            "exp": datetime.now(UTC) + timedelta(minutes=15),
        },
        settings.SECRET_KEY.get_secret_value(),
        algorithm="HS256",
    )
    return VoiceDraftReview(
        draft_token=draft_token,
        transcript=transcript,
        work_date=extracted.work_date,
        site_name=extracted.site_name,
        counterparty_name=extracted.counterparty_name,
        work_type=extracted.work_type,
        hours=extracted.hours,
        days=extracted.days,
        agreed_amount_inr=extracted.agreed_amount_inr,
        paid_amount_inr=extracted.paid_amount_inr,
        due_amount_inr=due_amount,
        language=extracted.language,
        detected_language_code=(
            transcription.detected_language_code or extracted.detected_language_code
        ),
        field_confidence=extracted.field_confidence,
        needs_clarification=needs_clarification,
        clarification_question=question,
        voice_mode=settings.VOICE_IMPL.lower(),
    )


@router.post(
    "/draft/confirm", response_model=EntryResponse, status_code=status.HTTP_201_CREATED
)
async def confirm_voice_draft(
    confirmation: ConfirmVoiceDraft,
    current_worker_id: CurrentWorker,
    hashchain_service: HashChainServiceDep,
    db: Annotated[Session, Depends(get_db)],
) -> EntryResponse:
    """Persist the reviewed entry only after the worker explicitly confirms it."""
    # Validate worker is active
    worker = db.query(Worker).filter(Worker.id == current_worker_id).first()
    if not worker or not worker.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Worker not found or account is inactive",
        )
    try:
        claims = jwt.decode(
            confirmation.draft_token,
            settings.SECRET_KEY.get_secret_value(),
            algorithms=["HS256"],
        )
    except jwt.ExpiredSignatureError as error:
        raise HTTPException(
            status_code=400, detail="Draft expired; record again"
        ) from error
    except jwt.InvalidTokenError as error:
        raise HTTPException(
            status_code=400, detail="Invalid draft; record again"
        ) from error

    if claims.get("draft") is not True:
        raise HTTPException(status_code=400, detail="Invalid draft; record again")
    if claims.get("worker_id") != current_worker_id:
        raise HTTPException(status_code=404, detail="Draft not found")
    if claims.get("voice_mode") != settings.VOICE_IMPL.lower():
        raise HTTPException(
            status_code=400, detail="Voice configuration changed; record again"
        )
    if confirmation.paid_amount_inr > confirmation.agreed_amount_inr:
        raise HTTPException(
            status_code=422,
            detail="Paid amount cannot exceed the agreed amount",
        )

    try:
        audio = base64.b64decode(confirmation.audio_base64, validate=True)
    except (binascii.Error, ValueError) as error:
        raise HTTPException(status_code=400, detail="Invalid audio data") from error
    if not audio or len(audio) > _MAX_AUDIO_BYTES:
        raise HTTPException(status_code=400, detail="Invalid audio data")
    if hashlib.sha256(audio).hexdigest() != claims.get("audio_sha256"):
        raise HTTPException(
            status_code=400, detail="Audio does not match the reviewed draft"
        )

    content_type = claims.get("content_type")
    extension = _AUDIO_TYPES.get(content_type)
    if extension is None:
        raise HTTPException(status_code=400, detail="Invalid audio format")

    audio_hash = hashlib.sha256(audio).hexdigest()
    existing_entry = (
        db.query(Entry)
        .filter(
            Entry.worker_id == current_worker_id,
            Entry.audio_sha256 == audio_hash,
        )
        .first()
    )
    if existing_entry is not None:
        return _entry_response(existing_entry)

    audio_path = Path(settings.AUDIO_STORAGE_PATH) / f"{uuid.uuid4().hex}{extension}"
    try:
        audio_path.parent.mkdir(parents=True, exist_ok=True)
        audio_path.write_bytes(audio)
    except OSError as error:
        raise HTTPException(
            status_code=500, detail="Unable to store entry audio"
        ) from error

    created_at = datetime.now(UTC).replace(tzinfo=None)
    previous_entry = (
        db.query(Entry)
        .filter(
            Entry.worker_id == current_worker_id,
            Entry.entry_hash.isnot(None),
            Entry.entry_hash != "",
        )
        .order_by(Entry.created_at.desc())
        .first()
    )
    previous_hash = (
        previous_entry.entry_hash if previous_entry else hashchain_service.GENESIS_HASH
    )
    transcript = claims["transcript"]
    transcript_hash = hashlib.sha256(transcript.encode("utf-8")).hexdigest()
    due_amount = confirmation.agreed_amount_inr - confirmation.paid_amount_inr
    entry = Entry(
        worker_id=current_worker_id,
        counterparty_id=None,
        work_date=confirmation.work_date.isoformat(),
        site_name=confirmation.site_name,
        counterparty_name=confirmation.counterparty_name,
        work_type=confirmation.work_type,
        hours=confirmation.hours,
        days=confirmation.days,
        agreed_inr=confirmation.agreed_amount_inr,
        paid_inr=confirmation.paid_amount_inr,
        due_inr=due_amount,
        language=confirmation.language,
        transcript=transcript,
        transcript_sha256=transcript_hash,
        audio_uri=str(audio_path),
        audio_sha256=audio_hash,
        prev_hash=previous_hash,
        entry_hash="",
        status=Entry.STATUS_WORKER_CONFIRMED,
        corrects_entry_id=None,
        created_at=created_at,
    )
    entry.entry_hash = hashchain_service.compute_entry_hash(
        {
            "worker_id": current_worker_id,
            "work_date": entry.work_date,
            "site_name": entry.site_name,
            "counterparty_name": entry.counterparty_name,
            "hours": entry.hours,
            "days": entry.days,
            "agreed_inr": entry.agreed_inr,
            "paid_inr": entry.paid_inr,
            "transcript_sha256": transcript_hash,
            "audio_sha256": audio_hash,
            "created_at": created_at.isoformat(),
        },
        previous_hash,
    )
    db.add(entry)
    db.add(
        EntryStatusLog(
            entry=entry,
            from_status=None,
            to_status=Entry.STATUS_WORKER_CONFIRMED,
            actor="worker",
        )
    )
    try:
        db.commit()
        db.refresh(entry)
    except SQLAlchemyError as error:
        db.rollback()
        try:
            audio_path.unlink(missing_ok=True)
        except OSError as cleanup_error:
            raise HTTPException(
                status_code=500,
                detail="Entry save failed and temporary audio cleanup failed",
            ) from cleanup_error
        raise HTTPException(
            status_code=500, detail="Unable to save confirmed entry"
        ) from error

    return _entry_response(entry)

    # Validate worker is active
    worker = db.query(Worker).filter(Worker.id == current_worker_id).first()
    if not worker or not worker.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Worker not found or account is inactive",
        )

@router.get("/", response_model=list[EntryResponse])
async def get_entries(
    current_worker_id: CurrentWorker,
    db: Annotated[Session, Depends(get_db)],
) -> list[EntryResponse]:
    """Get all entries for the current worker."""
    # Validate worker is active
    worker = db.query(Worker).filter(Worker.id == current_worker_id).first()
    if not worker or not worker.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Worker not found or account is inactive",
        )
    entries = (
        db.query(Entry)
        .filter(Entry.worker_id == current_worker_id)
        .order_by(Entry.created_at.desc())
        .all()
    )

    return [
        EntryResponse(
            id=e.id,
            work_date=e.work_date,
            site_name=e.site_name,
            counterparty_name=e.counterparty_name,
            work_type=e.work_type,
            hours=float(e.hours) if e.hours is not None else None,
            days=float(e.days) if e.days is not None else None,
            agreed_inr=float(e.agreed_inr),
            paid_inr=float(e.paid_inr),
            due_inr=float(e.due_inr),
            language=e.language,
            transcript=e.transcript,
            status=e.status,
            created_at=e.created_at,
        )
        for e in entries
    ]


@router.get("/{entry_id}", response_model=EntryResponse)
async def get_entry(
    entry_id: int,
    current_worker_id: CurrentWorker,
    db: Annotated[Session, Depends(get_db)],
) -> EntryResponse:
    """Get a single entry by ID."""
    # Validate worker is active
    worker = db.query(Worker).filter(Worker.id == current_worker_id).first()
    if not worker or not worker.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Worker not found or account is inactive",
        )
    entry = (
        db.query(Entry)
        .filter(Entry.id == entry_id, Entry.worker_id == current_worker_id)
        .first()
    )

    if not entry:
        raise HTTPException(status_code=404, detail="Entry not found")

    return EntryResponse(
        id=entry.id,
        work_date=entry.work_date,
        site_name=entry.site_name,
        counterparty_name=entry.counterparty_name,
        work_type=entry.work_type,
        hours=float(entry.hours) if entry.hours is not None else None,
        days=float(entry.days) if entry.days is not None else None,
        agreed_inr=float(entry.agreed_inr),
        paid_inr=float(entry.paid_inr),
        due_inr=float(entry.due_inr),
        language=entry.language,
        transcript=entry.transcript,
        status=entry.status,
        created_at=entry.created_at,
    )


@router.post("/{entry_id}/confirm", response_model=EntryResponse)
async def confirm_entry(
    entry_id: int,
    current_worker_id: CurrentWorker,
    hashchain_service: HashChainServiceDep,
    db: Annotated[Session, Depends(get_db)],
) -> EntryResponse:
    """Confirm entry with worker's spoken yes."""
    # Validate worker is active
    worker = db.query(Worker).filter(Worker.id == current_worker_id).first()
    if not worker or not worker.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Worker not found or account is inactive",
        )
    # Get entry
    entry = (
        db.query(Entry)
        .filter(Entry.id == entry_id, Entry.worker_id == current_worker_id)
        .first()
    )

    if not entry:
        raise HTTPException(status_code=404, detail="Entry not found")

    if entry.status != Entry.STATUS_DRAFT:
        raise HTTPException(status_code=400, detail="Entry already confirmed")

    # Verify state transition
    if Entry.STATUS_WORKER_CONFIRMED not in Entry.VALID_TRANSITIONS.get(
        entry.status, set()
    ):
        raise HTTPException(status_code=400, detail="Invalid state transition")

    previous_confirmed = (
        db.query(Entry)
        .filter(
            Entry.worker_id == current_worker_id,
            Entry.id != entry.id,
            Entry.entry_hash.isnot(None),
            Entry.entry_hash != "",
        )
        .order_by(Entry.created_at.desc(), Entry.id.desc())
        .first()
    )
    entry.prev_hash = (
        previous_confirmed.entry_hash
        if previous_confirmed
        else hashchain_service.GENESIS_HASH
    )

    # Compute entry hash
    entry_dict = {
        "worker_id": entry.worker_id,
        "work_date": entry.work_date,
        "site_name": entry.site_name,
        "counterparty_name": entry.counterparty_name,
        "hours": entry.hours,
        "days": entry.days,
        "agreed_inr": entry.agreed_inr,
        "paid_inr": entry.paid_inr,
        "transcript_sha256": entry.transcript_sha256,
        "audio_sha256": entry.audio_sha256,
        "created_at": (
            entry.created_at.isoformat()
            if entry.created_at
            else datetime.now(UTC).replace(tzinfo=None).isoformat()
        ),
    }

    entry.entry_hash = hashchain_service.compute_entry_hash(entry_dict, entry.prev_hash)

    # Log status change
    status_log = EntryStatusLog(
        entry_id=entry.id,
        from_status=entry.status,
        to_status=Entry.STATUS_WORKER_CONFIRMED,
        actor="worker",
    )
    db.add(status_log)

    # Update entry status
    entry.status = Entry.STATUS_WORKER_CONFIRMED

    db.commit()
    db.refresh(entry)

    return EntryResponse(
        id=entry.id,
        work_date=entry.work_date,
        site_name=entry.site_name,
        counterparty_name=entry.counterparty_name,
        work_type=entry.work_type,
        hours=float(entry.hours) if entry.hours is not None else None,
        days=float(entry.days) if entry.days is not None else None,
        agreed_inr=float(entry.agreed_inr),
        paid_inr=float(entry.paid_inr),
        due_inr=float(entry.due_inr),
        language=entry.language,
        transcript=entry.transcript,
        status=entry.status,
        created_at=entry.created_at,
    )


@router.post("/{entry_id}/correct", response_model=EntryResponse)
async def create_correction(
    entry_id: int,
    correction_data: EntryCorrect,
    current_worker_id: CurrentWorker,
    hashchain_service: HashChainServiceDep,
    db: Annotated[Session, Depends(get_db)],
) -> EntryResponse:
    """Create a correcting entry."""
    # Validate worker is active
    worker = db.query(Worker).filter(Worker.id == current_worker_id).first()
    if not worker or not worker.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Worker not found or account is inactive",
        )
    # Get original entry
    original_entry = (
        db.query(Entry)
        .filter(Entry.id == entry_id, Entry.worker_id == current_worker_id)
        .first()
    )

    if not original_entry:
        raise HTTPException(status_code=404, detail="Original entry not found")

    # Create new entry that corrects the original
    new_entry = Entry(
        worker_id=current_worker_id,
        counterparty_id=original_entry.counterparty_id,
        work_date=original_entry.work_date,
        site_name=original_entry.site_name,
        counterparty_name=original_entry.counterparty_name,
        hours=original_entry.hours,
        days=original_entry.days,
        agreed_inr=original_entry.agreed_inr,
        paid_inr=original_entry.paid_inr,
        due_inr=original_entry.due_inr,
        language=correction_data.lang,
        transcript=correction_data.transcript,
        transcript_sha256="",
        audio_uri=correction_data.audio_ref,
        audio_sha256="",
        prev_hash=original_entry.entry_hash,
        entry_hash="",  # Will be computed after worker confirmation
        status=Entry.STATUS_DRAFT,
        corrects_entry_id=entry_id,
    )

    db.add(new_entry)
    db.commit()
    db.refresh(new_entry)

    return EntryResponse(
        id=new_entry.id,
        work_date=new_entry.work_date,
        site_name=new_entry.site_name,
        counterparty_name=new_entry.counterparty_name,
        work_type=new_entry.work_type,
        hours=float(new_entry.hours) if new_entry.hours is not None else None,
        days=float(new_entry.days) if new_entry.days is not None else None,
        agreed_inr=float(new_entry.agreed_inr),
        paid_inr=float(new_entry.paid_inr),
        due_inr=float(new_entry.due_inr),
        language=new_entry.language,
        transcript=new_entry.transcript,
        status=new_entry.status,
        created_at=new_entry.created_at,
    )


@router.post("/{entry_id}/share", response_model=dict)
async def share_entry(
    entry_id: int,
    current_worker_id: CurrentWorker,
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    """Create share token for contractor."""
    # Validate worker is active
    worker = db.query(Worker).filter(Worker.id == current_worker_id).first()
    if not worker or not worker.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Worker not found or account is inactive",
        )
    # Get entry
    entry = (
        db.query(Entry)
        .filter(Entry.id == entry_id, Entry.worker_id == current_worker_id)
        .first()
    )

    if not entry:
        raise HTTPException(status_code=404, detail="Entry not found")

    if entry.status != Entry.STATUS_WORKER_CONFIRMED:
        raise HTTPException(
            status_code=400, detail="Entry must be confirmed before sharing"
        )

    # Generate share token
    token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(token.encode()).hexdigest()

    expires_at = datetime.now(UTC).replace(tzinfo=None) + timedelta(
        days=settings.SHARE_TOKEN_EXPIRY_DAYS
    )

    share_token = ShareToken(
        entry_id=entry_id,
        token_hash=token_hash,
        expires_at=expires_at,
        used_at=None,
    )

    db.add(share_token)
    db.commit()

    # Build share URL
    share_url = f"{settings.FRONTEND_URL.rstrip('/')}/c/{token}"

    return {"share_url": share_url}
