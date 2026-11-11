"""
Evidence pack router.
"""

from __future__ import annotations

import os
import uuid
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.config import Settings
from app.db import SessionLocal
from app.deps import CurrentWorker
from app.models import Entry, EvidencePack, Worker
from app.services.hashchain import HashChainService
from app.services.pdf import EvidencePDFService

settings = Settings()
router = APIRouter()


def get_db():
    """Get database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


class EvidencePackRequest(BaseModel):
    # Extra fields like a client-supplied worker_id are ignored; worker identity always comes from JWT.
    model_config = ConfigDict(extra="ignore")

    period_from: str  # YYYY-MM-DD
    period_to: str  # YYYY-MM-DD


class EvidencePackResponse(BaseModel):
    pack_id: int
    pdf_uri: str
    zip_uri: str
    pdf_download_url: str
    zip_download_url: str
    chain_head_hash: str
    entry_count: int


def _parse_iso_date(value: str, field_name: str) -> datetime:
    try:
        return datetime.strptime(value.strip(), "%Y-%m-%d")
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid {field_name} format. Expected YYYY-MM-DD.",
        ) from exc


def _resolve_entry_audio_path(audio_uri: str | None) -> Path | None:
    """Resolve an entry's audio_uri (filesystem path or local:// URI) to an existing file."""
    if not audio_uri:
        return None
    storage_root = Path(settings.AUDIO_STORAGE_PATH).resolve()
    if audio_uri.startswith("local://"):
        candidate = (
            storage_root / audio_uri.removeprefix("local://").lstrip("/")
        ).resolve()
        if not candidate.is_relative_to(storage_root):
            return None
        return candidate if candidate.is_file() else None
    candidate = Path(audio_uri).resolve()
    return candidate if candidate.is_file() else None


def _resolve_owned_pack_file(
    pack_id: int,
    uri_attr: Literal["pdf_uri", "zip_uri"],
    current_worker_id: int,
    db,
) -> Path:
    """Resolve an evidence pack artifact strictly owned by current_worker_id inside storage root."""
    pack = (
        db.query(EvidencePack)
        .filter(
            EvidencePack.id == pack_id,
            EvidencePack.worker_id == current_worker_id,
        )
        .first()
    )
    if not pack:
        raise HTTPException(status_code=404, detail="Evidence pack not found")

    raw_uri = getattr(pack, uri_attr, None)
    if not raw_uri:
        raise HTTPException(status_code=404, detail="Evidence file not available")

    storage_root = Path(settings.AUDIO_STORAGE_PATH).resolve()
    file_path = Path(raw_uri).resolve()
    if not file_path.is_relative_to(storage_root) or not file_path.is_file():
        raise HTTPException(status_code=404, detail="Evidence file not found")

    return file_path


@router.post("/evidence", response_model=EvidencePackResponse)
async def build_evidence_pack(
    request: EvidencePackRequest,
    current_worker_id: CurrentWorker,
    db: Annotated[Session, Depends(get_db)],
) -> EvidencePackResponse:
    """Build evidence pack strictly for the JWT-authenticated worker."""
    # Validate worker is active
    worker = db.query(Worker).filter(Worker.id == current_worker_id).first()
    if not worker or not worker.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Worker not found or account is inactive",
        )
    start_dt = _parse_iso_date(request.period_from, "period_from")
    end_dt = _parse_iso_date(request.period_to, "period_to")
    if start_dt > end_dt:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="period_from must be on or before period_to.",
        )

    period_from = start_dt.strftime("%Y-%m-%d")
    period_to = end_dt.strftime("%Y-%m-%d")

    entries = (
        db.query(Entry)
        .filter(
            Entry.worker_id == current_worker_id,
            Entry.status != Entry.STATUS_DELETED,
            Entry.work_date >= period_from,
            Entry.work_date <= period_to,
        )
        .order_by(Entry.created_at, Entry.id)
        .all()
    )

    if not entries:
        raise HTTPException(
            status_code=404, detail="No entries found for the specified period"
        )

    storage_dir = Path(settings.AUDIO_STORAGE_PATH)
    storage_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now(UTC).replace(tzinfo=None)
    stamp = now.strftime("%Y%m%d_%H%M%S")
    uid = uuid.uuid4().hex[:8]
    pdf_path = str(storage_dir / f"evidence_{current_worker_id}_{stamp}_{uid}.pdf")
    zip_path = str(storage_dir / f"evidence_{current_worker_id}_{stamp}_{uid}.zip")

    worker = db.query(Worker).filter(Worker.id == current_worker_id).first()
    entry_data = [
        {
            "id": e.id,
            "work_date": e.work_date,
            "site_name": e.site_name,
            "counterparty_name": e.counterparty_name,
            "hours": float(e.hours) if e.hours is not None else None,
            "days": float(e.days) if e.days is not None else None,
            "agreed_inr": float(e.agreed_inr),
            "paid_inr": float(e.paid_inr),
            "due_inr": float(e.due_inr),
            "status": e.status,
        }
        for e in entries
    ]

    pdf_service = EvidencePDFService()
    pdf_service.generate_evidence_pdf(
        worker_alias=worker.alias if worker else "Unknown",
        entries=entry_data,
        output_path=pdf_path,
        period_from=period_from,
        period_to=period_to,
    )

    with zipfile.ZipFile(zip_path, "w") as zf:
        manifest = "Evidence Pack Manifest\n"
        manifest += f"Generated: {now.isoformat()}\n"
        manifest += f"Worker ID: {current_worker_id}\n"
        manifest += f"Period: {period_from} to {period_to}\n\n"
        manifest += "Entries:\n"
        for e in entries:
            manifest += (
                f"  - Entry ID {e.id}: {e.work_date}, {e.site_name}, "
                f"Status: {e.status}, Hash: {e.entry_hash or 'DRAFT'}\n"
            )

        zf.writestr("MANIFEST.txt", manifest)
        zf.write(pdf_path, os.path.basename(pdf_path))

        added_audio: set[str] = set()
        for e in entries:
            audio_path = _resolve_entry_audio_path(e.audio_uri)
            if audio_path is not None:
                arcname = f"audio/{e.id}_{audio_path.name}"
                if arcname not in added_audio:
                    zf.write(str(audio_path), arcname)
                    added_audio.add(arcname)

    hashchain = HashChainService()
    chain_entries = [
        e for e in entries if e.status != Entry.STATUS_DRAFT or e.entry_hash
    ]
    chain_head_hash = hashchain.get_chain_head(chain_entries) or ""

    evidence_pack = EvidencePack(
        worker_id=current_worker_id,
        period_from=period_from,
        period_to=period_to,
        pdf_uri=pdf_path,
        zip_uri=zip_path,
        chain_head_hash=chain_head_hash,
        created_at=now,
    )
    db.add(evidence_pack)
    db.commit()
    db.refresh(evidence_pack)

    return EvidencePackResponse(
        pack_id=evidence_pack.id,
        pdf_uri=pdf_path,
        zip_uri=zip_path,
        pdf_download_url=f"/api/evidence/{evidence_pack.id}/pdf",
        zip_download_url=f"/api/evidence/{evidence_pack.id}/zip",
        chain_head_hash=chain_head_hash,
        entry_count=len(entries),
    )


@router.get("/evidence/{pack_id}/pdf")
async def download_evidence_pdf(
    pack_id: int,
    current_worker_id: CurrentWorker,
    db: Annotated[Session, Depends(get_db)],
) -> FileResponse:
    """Download the generated PDF for an evidence pack owned by the authenticated worker."""
    # Validate worker is active
    worker = db.query(Worker).filter(Worker.id == current_worker_id).first()
    if not worker or not worker.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Worker not found or account is inactive",
        )
    file_path = _resolve_owned_pack_file(pack_id, "pdf_uri", current_worker_id, db)
    return FileResponse(
        path=str(file_path),
        media_type="application/pdf",
        filename=f"evidence_pack_{pack_id}.pdf",
    )


@router.get("/evidence/{pack_id}/zip")
async def download_evidence_zip(
    pack_id: int,
    current_worker_id: CurrentWorker,
    db: Annotated[Session, Depends(get_db)],
) -> FileResponse:
    """Download the generated ZIP archive for an evidence pack owned by the authenticated worker."""
    # Validate worker is active
    worker = db.query(Worker).filter(Worker.id == current_worker_id).first()
    if not worker or not worker.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Worker not found or account is inactive",
        )
    file_path = _resolve_owned_pack_file(pack_id, "zip_uri", current_worker_id, db)
    return FileResponse(
        path=str(file_path),
        media_type="application/zip",
        filename=f"evidence_pack_{pack_id}.zip",
    )


@router.get("/verify", response_model=dict)
async def verify_chain(
    current_worker_id: CurrentWorker,
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    """Verify hash chain integrity for the authenticated worker's ledger entries."""
    # Validate worker is active
    worker = db.query(Worker).filter(Worker.id == current_worker_id).first()
    if not worker or not worker.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Worker not found or account is inactive",
        )
    entries = (
        db.query(Entry)
        .filter(
            Entry.worker_id == current_worker_id,
            Entry.status != Entry.STATUS_DELETED,
        )
        .order_by(Entry.created_at, Entry.id)
        .all()
    )

    chain_entries = [
        e for e in entries if e.status != Entry.STATUS_DRAFT or e.entry_hash
    ]
    if not chain_entries:
        return {
            "valid": True,
            "mismatch_reason": None,
            "checked_entries": 0,
            "chain_head_hash": None,
            "message": "No confirmed entries to verify",
        }

    hashchain = HashChainService()
    is_valid, mismatch_reason = hashchain.verify_chain(chain_entries)

    return {
        "valid": is_valid,
        "mismatch_reason": mismatch_reason,
        "checked_entries": len(chain_entries),
        "chain_head_hash": (
            hashchain.get_chain_head(chain_entries) if is_valid else None
        ),
        "message": None,
    }
