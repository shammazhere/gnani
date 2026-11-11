"""
Database models for Saakshi.
"""

from __future__ import annotations

from datetime import datetime
from typing import ClassVar

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship

Base = declarative_base()


class Worker(Base):
    """Worker who owns wage entries."""

    __tablename__ = "workers"

    id = Column(Integer, primary_key=True, index=True)
    alias = Column(String, unique=True, nullable=False)
    pin_hash = Column(String, nullable=False)
    language = Column(String, default="hi-IN")
    consent_audio_uri = Column(String, nullable=True)
    consent_text_version = Column(String, nullable=True)
    is_active = Column(Boolean, default=True)
    consent_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    entries = relationship(
        "Entry", back_populates="worker", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Worker(id={self.id}, alias={self.alias})>"


class Counterparty(Base):
    """Contractor or supervisor name."""

    __tablename__ = "counterparties"

    id = Column(Integer, primary_key=True, index=True)
    worker_id = Column(Integer, ForeignKey("workers.id"), nullable=False)
    display_name = Column(String, nullable=False)
    phone_optional = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    entries = relationship("Entry", back_populates="counterparty")

    def __repr__(self) -> str:
        return f"<Counterparty(id={self.id}, display_name={self.display_name})>"


class Entry(Base):
    """Wage entry - the core ledger record."""

    __tablename__ = "entries"

    # Status constants
    STATUS_DRAFT = "DRAFT"
    STATUS_WORKER_CONFIRMED = "WORKER_CONFIRMED"
    STATUS_SHARED = "SHARED"
    STATUS_CONTRACTOR_CONFIRMED = "CONTRACTOR_CONFIRMED"
    STATUS_CONTRACTOR_DISPUTED = "CONTRACTOR_DISPUTED"
    STATUS_UNCONFIRMED = "UNCONFIRMED"
    STATUS_DELETED = "DELETED"

    # Valid state transitions
    VALID_TRANSITIONS: ClassVar[dict[str, set[str]]] = {
        STATUS_DRAFT: {STATUS_WORKER_CONFIRMED},
        STATUS_WORKER_CONFIRMED: {STATUS_SHARED},
        STATUS_SHARED: {
            STATUS_CONTRACTOR_CONFIRMED,
            STATUS_CONTRACTOR_DISPUTED,
            STATUS_UNCONFIRMED,
        },
        STATUS_CONTRACTOR_CONFIRMED: set(),  # No further transitions
        STATUS_CONTRACTOR_DISPUTED: set(),
        STATUS_UNCONFIRMED: set(),
        STATUS_DELETED: set(),
    }

    id = Column(Integer, primary_key=True, index=True)
    worker_id = Column(Integer, ForeignKey("workers.id"), nullable=False)
    counterparty_id = Column(Integer, ForeignKey("counterparties.id"), nullable=True)

    work_date = Column(String, nullable=False)  # YYYY-MM-DD
    site_name = Column(String, nullable=True)
    counterparty_name = Column(String, nullable=True)
    work_type = Column(String, nullable=True)

    hours = Column(Numeric(precision=10, scale=2), nullable=True)
    days = Column(Numeric(precision=10, scale=2), nullable=True)

    agreed_inr = Column(Numeric(precision=15, scale=2), nullable=False)
    paid_inr = Column(Numeric(precision=15, scale=2), nullable=False)
    due_inr = Column(
        Numeric(precision=15, scale=2), nullable=False
    )  # Computed: agreed - paid

    # STT data
    language = Column(String, default="hi-IN")
    transcript = Column(Text, nullable=True)
    transcript_sha256 = Column(String(64), nullable=True)

    # Audio references
    audio_uri = Column(String, nullable=True)
    audio_sha256 = Column(String(64), nullable=True)

    # Hash chain
    prev_hash = Column(String(64), nullable=False)  # SHA256 of previous entry
    entry_hash = Column(String(64), nullable=False)  # SHA256 of this entry
    created_at = Column(DateTime, default=datetime.utcnow)

    # Status
    status = Column(String, default=STATUS_DRAFT, nullable=False)
    corrects_entry_id = Column(Integer, ForeignKey("entries.id"), nullable=True)

    # Relationships
    worker = relationship("Worker", back_populates="entries")
    counterparty = relationship("Counterparty", back_populates="entries")
    status_log = relationship(
        "EntryStatusLog", back_populates="entry", cascade="all, delete-orphan"
    )
    corrections = relationship("Entry", remote_side=[id], uselist=True)

    def __repr__(self) -> str:
        return (
            f"<Entry(id={self.id}, status={self.status}, work_date={self.work_date})>"
        )


class EntryStatusLog(Base):
    """Audit trail for entry status changes."""

    __tablename__ = "entry_status_log"

    id = Column(Integer, primary_key=True, index=True)
    entry_id = Column(Integer, ForeignKey("entries.id"), nullable=False)
    from_status = Column(String, nullable=True)
    to_status = Column(String, nullable=False)
    actor = Column(String, nullable=False)  # "worker" or "contractor"
    at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    entry = relationship("Entry", back_populates="status_log")

    def __repr__(self) -> str:
        return f"<EntryStatusLog(id={self.id}, entry_id={self.entry_id}, from={self.from_status}, to={self.to_status})>"


class ShareToken(Base):
    """One-time share token for contractor confirmation."""

    __tablename__ = "share_tokens"

    id = Column(Integer, primary_key=True, index=True)
    entry_id = Column(Integer, ForeignKey("entries.id"), nullable=False)
    token_hash = Column(String(64), nullable=False)  # Hash of token, not raw token
    expires_at = Column(DateTime, nullable=False)
    used_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    entry = relationship("Entry")

    def __repr__(self) -> str:
        return f"<ShareToken(id={self.id}, entry_id={self.entry_id}, expires={self.expires_at})>"


class Confirmation(Base):
    """Contractor confirmation or dispute."""

    __tablename__ = "confirmations"

    id = Column(Integer, primary_key=True, index=True)
    entry_id = Column(Integer, ForeignKey("entries.id"), nullable=False)
    party = Column(String, nullable=False)  # "worker" or "contractor"
    channel = Column(String, nullable=True)  # "web" or "wa.me"

    # Audio response
    audio_uri = Column(String, nullable=True)
    transcript = Column(Text, nullable=True)

    # Result
    result = Column(String, nullable=False)  # "yes", "no", or "dispute"
    reason_text = Column(Text, nullable=True)  # Optional text reason for dispute
    at = Column(DateTime, default=datetime.utcnow)

    def __repr__(self) -> str:
        return f"<Confirmation(id={self.id}, entry_id={self.entry_id}, result={self.result})>"


class EvidencePack(Base):
    """Generated evidence pack."""

    __tablename__ = "evidence_packs"

    id = Column(Integer, primary_key=True, index=True)
    worker_id = Column(Integer, ForeignKey("workers.id"), nullable=False)
    period_from = Column(String, nullable=False)  # YYYY-MM-DD
    period_to = Column(String, nullable=False)  # YYYY-MM-DD
    pdf_uri = Column(String, nullable=True)
    zip_uri = Column(String, nullable=True)
    chain_head_hash = Column(String(64), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    def __repr__(self) -> str:
        return f"<EvidencePack(id={self.id}, worker_id={self.worker_id}, period={self.period_from} to {self.period_to})>"
