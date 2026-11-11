# Saakshi

**Saakshi** (Hindi/Kannada for "witness") — a voice-first wage ledger that gives daily-wage and migrant workers a structured, cryptographically secured record of their work, owned and controlled from their phone.

---

## About the Project

Saakshi replaces paper-based wage records with a voice-driven digital ledger. Workers record spoken descriptions of their day; the system transcribes, structures, and stores the entry in a hash-chained ledger. Confirmed entries can be exported as evidence packs — PDF summaries with audio ZIP files — for use with legal-aid clinics, NGOs, or contractors.

The project is designed so Developer A can focus on voice/STT/TTS integrations and Developer B on backend/API/data, working independently on separate chunks with shared contracts.

---

## Problem Statement

Daily-wage and migrant workers often lack reliable, portable wage records. Paper logs are easily lost, falsified, or inaccessible when workers move between sites. Missing or inadequate documentation undermines legal claims, unpaid-wage disputes, and social protection. Without a trusted record, workers have little recourse when wages are withheld or conditions are misrepresented.

The result: wage theft goes unchallenged, legal-aid providers lack verified evidence, and workers lose the ability to prove their employment history across job changes.

---

## Our Solution

Saakshi gives workers a voice-owned, cryptographically secured record they can export and share on their own terms. A worker holds their phone and speaks about their work; the system transcribes the recording, extracts structured fields (date, site, contractor, hours, amounts), reads the entry back aloud for confirmation, and stores it in a tamper-evident ledger. Later, entries can be exported as evidence packs for external use.

The overall approach is: voice entry → transcription + structuring → worker confirmation → hash-chained storage → exportable evidence packs. No paper, no intermediaries, no reliance on employer-held records.

---

## Key Features

- **Voice entry**: Workers dictate their day; the system transcribes and structures the recording.
- **Hash-chained ledger**: Each entry is cryptographically linked to the previous one, providing tamper-evidence.
- **PIN-protected authentication**: Workers register with a 4-digit PIN; access is guarded via JWT bearer tokens.
- **Evidence packs**: Confirmed entries can be exported as PDF + ZIP audio summaries for legal-aid or NGO use.
- **Contractor confirmation**: One-time share links allow contractors to confirm or dispute entries.
- **Multilingual support**: Hindi, Kannada, Bengali, and English language support for transcription, UI, and TTS read-back.

---

## How It Works

A worker records a voice memo via the phone. The system transcribes it, extracts structured fields (work date, site name, contractor name, hours, agreed and paid amounts), and presents the transcript back for the worker to confirm. Upon confirmation, the entry is stored in a hash-chained ledger. Later, the worker can export some or all of their entries as an evidence pack — a PDF summary plus an audio ZIP file — that can be shared with legal-aid providers, NGOs, or contractors.

```mermaid
graph LR
    subgraph FE["Frontend\n(React + Vite)"]
        UI[User Interface]
        UI -->|HTTP, WS| API[api.ts Axios]
        UI -->|Bearer token| Auth[Auth interceptors]
    end

    subgraph BE["Backend\n(FastAPI + Uvicorn)"]
        API -->|Route handlers| ROUTES[auth, entries, contractor, evidence, voice]
        ROUTES -->|SQLAlchemy| DB[(Database<br/>SQLite / Neon Postgres)]
        ROUTES -->|bcrypt| PASSWORD[PIN hashing]
        ROUTES -->|PyJWT| TOKENS[JWT create/verify]
        ROUTES -->|HashChain| CHAIN[Hash chain service]
        ROUTES -->|ReportLab| PDF[PDF generation]
        ROUTES -->|zipfile| ARCHIVE[ZIP archive]
        ROUTES -->|Voice service| VOICE[STT/TTS (Gnani / FakeVoice)]
    end

    DB -->|Workers, Entries, Evidence packs| ROUTES
    VOICE -->|STT transcript, TTS audio| API

    style FE fill:#e3f2fd,stroke:#1976d2,stroke-width:2px
    style BE fill:#e8f5e9,stroke:#388e3c,stroke-width:2px
    style DB fill:#fff3e0,stroke:#fb8c00,stroke-width:2px
```

**User journey**: Register → Login → Record voice → Review transcript → Confirm entry → View entries → Export evidence pack → Share with contractor.

---

## Who Can Benefit

- **Daily-wage workers** in construction, agriculture, or informal sectors who need portable, trusted wage records
- **Migrant workers** who move between sites and need a record that travels with them
- **Legal-aid clinics and NGO case workers** who need verified entry records to support claims
- **Supervisors and contractors** who need to confirm or dispute entries via one-time share links

---

## Technology Stack

- **Frontend**: React 18, TypeScript, Vite, Tailwind CSS, React Router, React i18next, Zustand, Axios
- **Backend**: FastAPI, Python 3.11+/3.12+, SQLAlchemy 2.0, Alembic, Pydantic v2, Passlib[bcrypt], PyJWT
- **Database**: SQLite for local development; PostgreSQL/Neon for production
- **Voice/Audio**: FakeVoice (default, simulated STT/TTS) or Gnani integration (production STT/TTS via WebSocket)
- **Linting/Format**: Ruff, Black (target Python 3.11), Prettier (frontend)
- **Testing**: pytest, httpx, Playwright

---

## Project Vision

Saakshi imagines a world where every worker owns a portable, cryptographically secured record of their labor. By replacing paper with voice-driven digital records, the project aims to reduce wage theft, simplify evidence collection for legal-aid providers, and give migrant workers a record that moves with them across sites and seasons. The long-term goal is to make verified work history as portable as a phone number — enabling fairer labor practices and stronger social protection for those who need it most.

---

*Saakshi is an open-source project. Contributions, feedback, and collaborations are welcome.*
