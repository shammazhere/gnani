# Saakshi — Worker-Held Voice Wage Ledger

**Saakshi** (Hindi/Kannada for "witness") is a voice-first diary that allows daily-wage and migrant workers to own a structured, hash-chained ledger of their work entries. A worker records spoken descriptions of their day's work; the system transcribes it, extracts structured fields, reads the entry back aloud for confirmation, and stores it in a tamper-evident ledger. Records can later be exported as evidence packs for legal-aid clinics or NGO case workers.

The project is architected so that Developer A (voice/STT/TTS integrations) and Developer B (backend/API/data) can work independently on separate chunks, with clearly owned folders and shared contracts.

---

## Table of Contents

[Project Overview](#a-project-overview) | [Key Features](#b-key-features) | [Technology Stack](#c-technology-stack) | [System Architecture](#d-system-architecture) | [Project Directory Structure](#e-project-directory-structure) | [Application Workflow](#f-application-workflow) | [Authentication and Security](#g-authentication-and-security) | [Database Design](#h-database-design) | [API Documentation](#i-api-documentation) | [Prerequisites](#j-prerequisites) | [Local Installation and Setup](#k-local-installation-and-setup) | [Environment Variables](#l-environment-variables) | [Running Tests](#m-running-tests) | [Deployment](#n-deployment) | [Troubleshooting](#o-troubleshooting) | [Current Implementation Status and Limitations](#p-current-implementation-status-and-limitations) | [Future Improvements](#q-future-improvements) | [Contribution Guidelines](#r-contribution-guidelines) | [License](#s-license)

---

## A. Project Overview

### What Saakshi Does

Saakshi is a full-stack application that replaces paper-based wage records with a voice-driven digital ledger. Key capabilities:

- **Voice entry**: Workers hold the phone to speak about their work; the system transcribes, structures, and stores the record.
- **Hash-chained ledger**: Each entry is cryptographically linked to the previous one, providing tamper-evidence (not tamper-proofness).
- **PIN-protected authentication**: Workers register with a 4-digit PIN; access is guarded via JWT bearer tokens.
- **Evidence packs**: Confirmed entries can be exported as PDF + ZIP audio summaries for legal-aid or NGO use.
- **Contractor confirmation**: One-time share links allow contractors to confirm or dispute entries.
- **Multilingual**: Supports Hindi (hi-IN), Kannada (kn-IN), Bengali (bn-IN), and English (en-IN).

### Problem Addressed

Daily-wage and migrant workers often lack reliable, portable wage records. Missing or falsified documentation undermines legal claims, unpaid-wage disputes, and social protection. Saakshi gives workers a voice-owned, cryptographically secured record they can export and share on their own terms.

### Target Users

- Daily-wage workers in construction, agriculture, or informal sectors
- Migrant workers who move between sites and need portable records
- Legal-aid clinics and NGO case workers who need verified entry records
- Supervisors and contractors who need to confirm or dispute entries

### Main Objectives

1. Enable workers to record wage entries via simple voice dictation.
2. Transcribe and structure free-form speech into standardized fields (date, site, contractor, hours, amounts).
3. Maintain a hash-chained, append-only ledger that provides tamper-evidence.
4. Export confirmed entries as evidence packs (PDF summary + audio ZIP) for external use.
5. Allow contractors to confirm or dispute entries via one-time links.
6. Provide multilingual TTS read-back for worker confirmation.
7. Support both a fake voice implementation (for development) and Gnani/real STT/TTS (for production).

### Key Capabilities

| Capability | Status |
|---|---|
| Worker registration with 4-digit PIN | Fully implemented |
| Hold-to-talk voice entry | Fully implemented (FakeVoice default) |
| Real-time speech-to-text via Gnani | Partially implemented (fake fallback) |
| Structured extraction (date, site, contractor, hours, agreed/paid/due) | Fully implemented |
| TTS read-back of extracted entry | Fully implemented (FakeVoice) |
| Spoken yes/no confirmation | Fully implemented |
| Contractor confirmation via one-time link | Fully implemented |
| Append-only hash-chained ledger | Fully implemented |
| Evidence pack: PDF summary + audio ZIP + manifest | Fully implemented |
| Entry history with status badges | Fully implemented |
| Worker activation/deactivation | Implemented via `is_active` column; safe fallback with `getattr()` |
| PIN change and language update | Fully implemented |

---

## B. Key Features

Features are categorized by implementation status.

### Fully Implemented

- **Worker registration**: Register with alias, 4-digit PIN, and language preference. PIN is bcrypt-hashed.
- **PIN-based authentication**: Login with alias + PIN; returns JWT access token valid 30 minutes.
- **PIN change**: Authenticated workers can change their PIN after verifying the current one.
- **Language update**: Authenticated workers can update their preferred UI/voice language.
- **Entry draft creation**: Stream audio or submit JSON to create a voice draft; Gnani STT or FakeVoice transcription.
- **Entry confirmation**: Worker reviews transcript and confirms the drafted entry; audio is stored; hash chain is computed.
- **Entry listing**: Authenticated worker sees their own entries; each entry shows status, amounts, and transcript.
- **Single-entry retrieval**: GET `/api/entries/{entry_id}` for a specific entry.
- **Entry correction**: Create a correcting entry that references the original.
- **Evidence pack generation**: Build PDF + ZIP audio manifest for a date range; strictly owned by the authenticated worker.
- **Evidence pack download**: Download PDF or ZIP of a previously generated pack.
- **Hash chain verification**: Verify the integrity of the worker's entire ledger.
- **Contractor confirmation**: One-time share token; contractor responds yes/no/dispute; entry status updates accordingly.
- **Worker deactivation**: `is_active` column; access guarded with `getattr(worker, 'is_active', True)` for backward compatibility.

### Partially Implemented

- **Real Gnani STT/TTS integration**: Default implementation uses `FakeVoice` (simulated transcript starting with `"DEMO SAMPLE:"`). Production requires a Gnani account with API keys configured via `GNANI_STT_API_KEY`, `GNANI_TTS_API_KEY`, and `VOICE_IMPL=gnani`.
- **LLM-based extraction**: Reserved for a free hosted tier or local Ollama; not currently wired into the extraction pipeline.
- **Offline queue and sync**: Not implemented; audio and draft data must be sent in a single request.
- **IVR/phone-call channel**: Not implemented; requires a telephony backend.

### Planned or Not Yet Implemented

- **Legal-advice automation**: Explicitly out of scope; Saakshi presents records as "a dated record" not "legal proof."
- **Payments integration**: Out of scope.
- **Payments benchmarks by region**: Out of scope.
- **Multiple sites/contractors dashboards**: Out of scope for the MVP.
- **Additional languages beyond Gnani supported set**: Odia, Assamese, Urdu, Tulu, Konkani are not supported.

---

## C. Technology Stack

### Frontend

- **React**: 18.3.1
- **TypeScript**: Type-safe component and API usage
- **Vite**: Build dev server and production build
- **Tailwind CSS**: Utility-first styling
- **React Router DOM**: Client-side routing (version 6.28.0)
- **React i18next**: Internationalization (version 15.1.3)
- **Zustand**: State management (version 5.0.0)
- **Axios**: HTTP client with interceptors for auth token injection

### Backend

- **FastAPI**: Python 3.11+/3.12+ web framework
- **Uvicorn**: ASGI server
- **SQLAlchemy 2.0**: ORM and core
- **Alembic**: Database migrations
- **Pydantic v2**: Data validation and settings management
- **Passlib[bcrypt]**: Password hashing for PINs
- **PyJWT (jwt)**: JWT access tokens (HS256, 30-minute expiry)
- **WebSockets**: Raw Gnani VAD client connection (`websockets` lib)

### Database

- **SQLite**: Default for local development (zero setup)
- **PostgreSQL / Neon**: Supported for production; connection URL normalized via `normalize_database_url()`
- **Alembic**: Migration-based schema evolution (currently at revision `002_add_worker_is_active`)

### Authentication and Security

- **PIN verification**: 4-digit PIN; bcrypt hashing (`passlib[bcrypt]`)
- **JWT tokens**: HS256 algorithm; signed with `SECRET_KEY` (≥32 chars, validated)
- **Rate limiting**: Per-client IP, 5 attempts per 60-second window; 429 with `Retry-After`
- **Worker activation**: `is_active` column; safe fallback with `getattr()` for databases missing the column

### Voice/Audio Processing

- **FakeVoice** (default): Simulated STT returning `"DEMO SAMPLE:"` transcript; TTS generates short audio.
- **Gnani integration**: Production STT/TTS via WebSocket; requires API keys and `VOICE_IMPL=gnani`.
- **Audio storage**: Local `data/audio/` folder (git-ignored); paths stored in DB; swap for object storage later.

### Deployment and Hosting

- **Vercel**: Backend entrypoint is `backend.app.main:app`; `vercel.json` configures the root entrypoint.
- **Docker**: `Dockerfile` and `docker-compose.yml` provided.
- **Database hosting**: Neon Postgres (serverless) supported; SQLite for local dev.
- **CORS**: Configurable origins; defaults to `http://localhost:5173` and `http://localhost:3000`.

### Testing and Development Tools

- **pytest**: Backend unit and integration tests
- **httpx**: Test client for FastAPI
- **Playwright**: Browser E2E tests
- **Ruff**: Linter
- **Black**: Code formatter (target Python 3.11)
- **Prettier**: Frontend formatter
- **Mypy**: Type checking (implied by TypeScript frontend)

---

## D. System Architecture

### High-Level Communication Flow

```
Frontend (React + Vite)                          Backend (FastAPI + Uvicorn)              Database (SQLite / PostgreSQL)
   |                                                      |
   | 1. POST /api/auth/register {alias, pin}              |
   | ─────────────────────────────────────────────────▶|
   |                                                      | 2. bcrypt.hash(pin) → pin_hash
   |                                                      | 3. Worker(rows) + create_access_token()
   |                                                      | ────────────────────────────────────────▶
   |                                                      | 4. JWT token returned
   | 5. Store token + profile in localStorage          |
   | ─────────────────────────────────────────────────▶|
   |                                                      |
   | 6. POST /api/entries/draft (audio or JSON)         |
   | ─────────────────────────────────────────────────▶| 7. Validate worker active (getattr is_active, True)
   |                                                      | 8. transcribe_audio() → Gnani or FakeVoice
   | 9. Voice service returns transcript + extracted fields
   | ─────────────────────────────────────────────────▶|
   | 10. Create Entry(DRAFT) with transcript, audio_hash
   | 11. JWT draft_token returned
   | 12. Return VoiceDraftReview to frontend
   |                                                      |
   | 13. Worker reviews transcript in UI                |
   | 14. POST /api/entries/draft/confirm {draft_token,  |
   |     audio_base64, confirmation fields}            |
   | ─────────────────────────────────────────────────▶| 15. Verify JWT draft_token, expiry, voice_mode
   | 16. Decode audio, compute SHA256, match claim
   | 17. Compute entry_hash via HashChainService
   | 18. Entry(STATUS_WORKER_CONFIRMED) + log + commit
   | ─────────────────────────────────────────────────▶|
   | 19. Return EntryResponse (id, status, amounts...)
   |                                                      |
   | 20. GET /api/entries/ (list) or /api/entries/{id}   |
   | ─────────────────────────────────────────────────▶| 21. Validate worker active
   | 22. Query entries WHERE worker_id == current_id
   | 23. Return EntryResponse[] or single EntryResponse
   | ─────────────────────────────────────────────────▶|
   | 24. POST /api/evidence {period_from, period_to}    |
   | ─────────────────────────────────────────────────▶| 25. Validate worker active
   | 26. Query entries IN period, status != DELETED
   | 27. Generate PDF (ReportLab) + ZIP (audio files)
   | 28. Store EvidencePack row + artifact paths
   | ─────────────────────────────────────────────────▶|
   | 29. Return EvidencePackResponse (pdf_uri, zip_uri)
   | 30. Worker downloads PDF or ZIP                    |
   |                                                      |
   | 31. POST /api/contractor/{token}                  |
   | ─────────────────────────────────────────────────▶| 32. Validate share token (hash, expiry, unused)
   | 33. Return entry transcript + language
   | 34. Contractor views entry, responds yes/no/dispute
   | 35. POST /api/contractor/{token}/respond {result}
   | ─────────────────────────────────────────────────▶| 36. Update entry status (CONTRACTOR_CONFIRMED /
   |     CONTRACTOR_DISPUTED / UNCONFIRMED)
   | 37. Record Confirmation row
   | ─────────────────────────────────────────────────▶|

### Mermaid Architecture Diagram

```mermaid
graph TD
    subgraph FE["Frontend (React + Vite)"]
        UI[User Interface] -->|HTTP, WS| API[api.ts Axios]
        UI -->|WebSocket| WS[/ws/stt endpoint]
        UI -->|Bearer token| Auth[Auth interceptors]
    end

    subgraph BE["Backend (FastAPI + Uvicorn)"]
        API -->|Route handlers| ROUTES[auth, entries, contractor, evidence, voice]
        ROUTES -->|SQLAlchemy| DB[(Database<br/>SQLite / Neon Postgres)]
        ROUTES -->|bcrypt| PASSWORD[PIN hashing]
        ROUTES -->|PyJWT| TOKENS[JWT create/verify]
        ROUTES -->|HashChain| CHAIN[Hash chain service]
        ROUTES -->|ReportLab| PDF[PDF generation]
        ROUTES -->|zipfile| ARCHIVE[ZIP archive]
        ROUTES -->|Voice service| VOICE[STT/TTS (Gnani / FakeVoice)]
    end

    DB -->| Workers, Entries, Evidence packs| ROUTES
    VOICE -->|STT transcript, TTS audio| API

    style FE fill:#e3f2fd,stroke:#1976d2,stroke-width:2px
    style BE fill:#e8f5e9,stroke:#388e3c,stroke-width:2px
    style DB fill:#fff3e0,stroke:#fb8c00,stroke-width:2px
```

### Request Flow Summary

1. **Worker registers** → POST `/api/auth/register` → bcrypt hash → JWT issued → token stored in localStorage
2. **Worker logs in** → POST `/api/auth/login` → verify PIN → JWT issued → token stored
3. **Worker records voice** → Hold-to-talk → WebSocket `/ws/stt` → Gnani/FakeVoice → transcript
4. **Entry draft created** → POST `/api/entries/draft` → validate worker active → transcribe → extract fields → draft_token + VoiceDraftReview returned
5. **Worker confirms** → POST `/api/entries/draft/confirm` → verify draft_token → decode audio → compute entry_hash → Entry(STATUS_WORKER_CONFIRMED) → hash chain append → commit
6. **Entries listed** → GET `/api/entries/` → validate worker active → query by worker_id → EntryResponse[]
7. **Evidence pack** → POST `/api/evidence` → validate worker active → query entries in period → PDF + ZIP → EvidencePack row → download URLs
8. **Contractor confirms** → GET `/api/contractor/{token}` → validate share token → entry transcript + language → POST `/api/contractor/{token}/respond` → update entry status + record Confirmation

---

## E. Project Directory Structure

```
saakshi/
├── contracts/                    # Shared, frozen after Day 2 (joint PR only)
│   ├── api.openapi.yaml          # OpenAPI contract (shared)
│   ├── schemas/                  # JSON Schema contracts
│   ├── voice_interface.py        # Voice service contract (STT/TTS)
│   ├── fake_voice.py             # FakeVoice implementation (Developer A)
│   └── fixtures/                 # Audio + JSON fixtures (Developer A)
├── backend/                      # Backend (Developer B)
│   ├── voice/                    # Voice router & services (DEVELOPER A only)
│   └── app/                      # Core Saakshi application
│       ├── alembic.ini           # Alembic migration config
│       ├── api.py                # FastAPI app factory (create_application)
│       ├── auth.py               # Auth router (login, register, PIN, language)
│       ├── config.py             # Pydantic Settings (env vars)
│       ├── db.py                 # Engine, session, normalize_database_url, ensure_tables_ready
│       ├── main.py               # App entrypoint (uvicorn runner)
│       ├── models.py             # SQLAlchemy 2.0 models (Worker, Entry, etc.)
│       ├── migrations/           # Alembic versions (001_initial_schema, 002_add_worker_is_active)
│       ├── pyproject.toml        # Project deps + vercel.entrypoint
│       ├── routers/              # API route modules
│       │   ├── auth.py           # Auth (login, register, change-pin, language)
│       │   ├── entries.py        # Entry CRUD, draft/confirm, hash chain, evidence
│       │   ├── contractor.py     # Contractor confirmation flow
│       │   └── evidence.py       # Evidence pack PDF + ZIP
│       ├── requirements.txt      # Pinned dependencies
│       ├── saakshi.db            # Default SQLite DB (development)
│       ├── services/             # Audio store, PDF, hashchain services
│       └── voice/                # Voice service dependency (may be DEV A)
├── frontend/                     # Frontend (Developer B)
│   ├── src/
│   │   ├── api.ts                # Axios client + resolveApiUrl, auth session
│   │   ├── App.tsx               # Root component with AuthGuard
│   │   ├── main.tsx              # React entry point
│   │   ├── useEntries.ts         # Entry hook
│   │   ├── pages/                # Home, Onboarding (Login), Settings, History
│   │   │   └── onboarding/       └── Login.tsx
│   │   ├── components/           # Button, StatusBadge, AuthBackdrop, etc.
│   │   ├── lib/                  # useTranslation, i18n, supported languages
│   │   └── voice/                # VoiceDraftReview, VoiceDraftConfirmation types
│   ├── package.json              # React/Vite dependencies + scripts
│   ├── tailwind.config.js        # Tailwind configuration
│   ├── tsconfig.json             # TypeScript config
│   └── vite.config.ts            # Vite dev server config
├── docs/                         # Project docs ( Developer A / Developer B )
│   ├── voice/                    # Developer A voice docs
│   ├── app/                      # Developer B app docs
│   └── CHANGELOG.md              # Append-only change log (both)
├── .github/                      # CI and tooling (Developer B)
│   └── workflows/                # CI workflows (black, ruff, tests)
├── docker-compose.yml            # Multi-service compose (if needed)
├── Dockerfile                    # Docker image definition
├── Makefile                      # Convenience commands
├── .env.example                  # Environment variable template (never commit actual values)
├── .env                          # Local overrides (gitignored; never committed)
└── pyproject.toml                # Root project metadata + vercel config
```

### Important Folders and Files

| Folder/File | Purpose |
|---|---|
| `backend/app/` | Core backend application (FastAPI factory, models, config, routers) |
| `backend/app/routers/` | API route modules (auth, entries, contractor, evidence, voice) |
| `backend/app/models.py` | SQLAlchemy 2.0 ORM models (Worker, Entry, EntryStatusLog, etc.) |
| `backend/app/config.py` | Pydantic Settings; validates SECRET_KEY ≥ 32 chars, non-placeholder |
| `backend/app/db.py` | Engine creation, session factory, `normalize_database_url()`, `ensure_tables_ready()` |
| `backend/app/migrations/` | Alembic migration scripts |
| `frontend/src/api.ts` | Axios client; `resolveApiUrl()`, auth session management (`storeAuthSession`, `restoreAuthSession`) |
| `frontend/src/App.tsx` | Root component with `AuthGuard` for route protection |
| `frontend/src/pages/onboarding/Login.tsx` | Login / register screen |
| `contracts/voice_interface.py` | Voice service contract (`transcribe_audio`, `extract_entry`, `classify_confirmation`, `tts`) |
| `contracts/fake_voice.py` | Default FakeVoice implementation (for development) |
| `contracts/api.openapi.yaml` | Shared OpenAPI contract (frozen after Day 2) |
| `.env.example` | Template; never commit actual secrets |
| `vercel.json` | Vercel deployment config; entrypoint `backend.app.main:app` |
| `Dockerfile` | Docker image for backend + frontend |
| `docker-compose.yml` | Optional multi-service orchestration |

---

## F. Application Workflow

### Login and Authentication

1. **Open onboarding screen** → Worker sees "Welcome back" form with alias and 4-digit PIN fields.
2. **Enter alias + PIN** → Press "Login" → POST `/api/auth/login` {alias, pin}.
3. **Backend verifies**:
   - Query `Worker` by alias → `verify_pin()` → `getattr(worker, 'is_active', True)` → if False, return None
   - `bcrypt.verify(pin, worker.pin_hash)` → if mismatch, record failure → 401 "Invalid alias or PIN"
   - If valid → `create_access_token({"worker_id": worker.id})` → JWT HS256 → return TokenResponse
4. **Frontend stores** token + profile in localStorage via `storeAuthSession()`.
5. **All subsequent API calls** include `Authorization: Bearer <token>` header (axios interceptor).
6. **Token expiry**: 30 minutes; expired tokens cause `clearAuthSession()` and dispatch `AUTH_EXPIRED_EVENT`.

### Worker Management

- **Register**: POST `/api/auth/register` {alias, pin, language} → 201 → JWT returned.
- **Change PIN**: PUT `/api/auth/change-pin` {current_pin, new_pin} → verify current PIN via bcrypt → replace hash → 200 {"status": "updated"}.
- **Update language**: PATCH `/api/auth/language` {language} → validate `is_active` via `getattr()` → update `Worker.language` → 200 {"language": "kn-IN"}.
- **Relogin preserves language**: Login returns stored language; subsequent language changes persist across logins.

### Entry Creation and Management

1. **Record audio** → Press and hold microphone button → release → audio sent to `/ws/stt?lang=hi-IN&mode=narration&kind=narration` → transcript + audio_saved (WAV path + SHA256).
2. **Create draft** → POST `/api/entries/draft` with transcript + extracted fields (or JSON) → `VoiceDraftReview` returned (draft_token, transcript, extracted fields, needs_clarification list).
3. **Review transcript** → UI shows highlights for missing fields (work_date, agreed_amount_inr, paid_amount_inr).
4. **Confirm entry** → POST `/api/entries/draft/confirm` {draft_token, audio_base64, work_date, site_name, counterparty_name, hours, days, agreed_amount_inr, paid_amount_inr, language} → verify JWT → decode audio → compute entry_hash → Entry(STATUS_WORKER_CONFIRMED) → hash chain append → commit → EntryResponse returned.
5. **View entries** → GET `/api/entries/` → list worker's entries with status badges, amounts, and truncated transcript.
6. **Single entry** → GET `/api/entries/{entry_id}` → detail view.
7. **Correct entry** → POST `/api/entries/{entry_id}/correct` → creates correcting Entry(DRAFT) with `corrects_entry_id` link.
8. **Share entry** → POST `/api/entries/{entry_id}/share` → generate one-time token → share URL `https://<frontend>/c/{token}` → contractor views and responds.

### Evidence Handling

1. **Build pack** → POST `/api/evidence` {period_from, period_to} → validate worker active → query entries in period → ReportLab PDF + ZIP (audio files + MANIFEST.txt) → EvidencePack row → return pdf_uri, zip_uri, download URLs.
2. **Download PDF** → GET `/api/evidence/{pack_id}/pdf` → FileResponse → worker's own pack only.
3. **Download ZIP** → GET `/api/evidence/{pack_id}/zip` → FileResponse → worker's own pack only.
4. **Verify chain** → GET `/api/verify` → validate worker active → hash chain integrity check → return valid/checked_entries/chain_head_hash.

### Voice/Audio Workflow (Default FakeVoice)

1. **Start STT session** → WebSocket `/ws/stt?lang=hi-IN&mode=narration&kind=narration` → send PCM chunks → receive `{type: "transcript", text}` + `{type: "audio_saved", audio_ref, sha256}`.
2. **Extract entry** → POST `/api/voice/extract` {transcript, lang, context} → extracted fields (work_date, site_name, counterparty_name, hours, days, agreed_amount_inr, paid_amount_inr, language, detected_language_code, needs_clarification, clarification_question).
3. **TTS** → POST `/api/voice/tts` {text, lang} → audio response (MP3/OGG).
4. **Classify confirmation** → POST `/api/voice/classify-confirmation` {transcript, lang} → "yes" / "no" / "unclear".

---

## G. Authentication and Security

### Login Process

1. POST `/api/auth/login` with `{alias, pin}`.
2. Backend queries `Worker` by alias.
3. `verify_pin()` executes:
   - `if not worker: return None` → 401
   - `if not getattr(worker, 'is_active', True): return None` → 401 (inactive worker; defaults to True if column missing)
   - `if not bcrypt.verify(pin, worker.pin_hash): return None` → 401 "Invalid alias or PIN"
   - If all pass → `create_access_token({"worker_id": worker.id})` → 200 JWT token.
4. Frontend stores token; all future requests include `Authorization: Bearer <token>`.

### PIN Verification and Hashing

- PIN is a 4-digit string.
- Stored as bcrypt hash in `Worker.pin_hash`.
- `passlib[bcrypt]` handles hashing (`bcrypt.hash()`) and verification (`bcrypt.verify()`).
- PIN change flow: verify current PIN → bcrypt.hash(new_pin) → replace pin_hash → commit.

### JWT Handling

- Algorithm: HS256
- Signing key: `SECRET_KEY` (validated ≥ 32 chars, non-placeholder, ≥ 16 unique characters)
- Access token expiry: 30 minutes (configurable via `ACCESS_TOKEN_EXPIRE_MINUTES`)
- Token format: `{ "worker_id": <int>, "exp": <epoch_ms>, "iat": <epoch_ms> }`
- Used in: `/api/auth/change-pin`, `/api/auth/language`, `/api/entries/draft/confirm`, `/api/evidence`, `/api/verify`, and all protected entry routes.

### Worker Activation/Deactivation

- `Worker.is_active` column defaults to `True`.
- Access to PIN-change, language update, entry operations, and evidence pack generation checks `is_active` via `getattr(worker, 'is_active', True)`.
- If the column exists in the DB, the actual value is used (inactive workers are rejected).
- If the column is missing (e.g., production Neon DB without migration 002), the default `True` is used, preserving backward compatibility.

### Protected API Endpoints

Endpoints that require a valid, non-expired JWT with a registered worker:

| Path | Purpose |
|---|---|
| `/api/auth/register` | Public (no auth required) |
| `/api/auth/login` | Public (no auth required) |
| `/api/auth/change-pin` | POST; current PIN + new PIN |
| `/api/auth/language` | PATCH; language update |
| `/api/entries/` | GET; list entries |
| `/api/entries/{id}` | GET; single entry |
| `/api/entries/draft` | POST; create draft |
| `/api/entries/draft/confirm` | POST; confirm draft |
| `/api/entries/{id}/confirm` | POST; confirm entry |
| `/api/entries/{id}/correct` | POST; create correction |
| `/api/entries/{id}/share` | POST; generate share token |
| `/api/evidence` | POST; build evidence pack |
| `/api/evidence/{id}/pdf` | GET; download PDF |
| `/api/evidence/{id}/zip` | GET; download ZIP |
| `/api/verify` | GET; hash chain verification |
| `/api/contractor/{token}` | GET; view entry for contractor |
| `/api/contractor/{token}/respond` | POST; contractor response |

### Environment-Based Secret Management

- `SECRET_KEY` is validated in `config.py` field validator: must be ≥ 32 chars, no surrounding whitespace, ≥ 16 unique characters.
- Generate with: `python3 -c "import secrets; print(secrets.token_urlsafe(32))"`
- `.env.example` provides the template; never commit actual `.env` values.
- Production deployment must set `SECRET_KEY` via the hosting environment (Vercel, Railway, etc.).
- `CORS_ORIGINS` is resolved from environment; Vercel `VERCEL_PROJECT_PRODUCTION_URL` or `VERCEL_URL` automatically appended.

---

## H. Database Design

### Database Engine

- **Development**: SQLite (`sqlite:///./saakshi.db`) — zero setup, embedded.
- **Production**: PostgreSQL / Neon serverless — connection URL via `DATABASE_URL` env var; normalized by `normalize_database_url()`.

### Main Tables and Purposes

| Table | Purpose |
|---|---|
| `workers` | Worker accounts: alias (unique), pin_hash, language, is_active, consent info, timestamps |
| `entries` | Wage ledger entries: hash-chained, status flow, audio/transcript references, financial fields |
| `entry_status_log` | Audit trail: who changed status and when (worker or contractor) |
| `counterparties` | Contractor/supervisor names (linked to worker via `worker_id`) |
| `share_tokens` | One-time tokens for contractor confirmation entries |
| `confirmations` | Contractor confirmation or dispute records |
| `evidence_packs` | Generated packs: PDF path, ZIP path, period, chain head hash, worker ownership |
| `` (implicit) | SQLite internal metadata |

### Important Relationships

- **Worker 1:N Entries**: A worker has many entries; `entries.worker_id → workers.id`
- **Counterparty 1:N Entries**: A counterparty (contractor) has many entries; `entries.counterparty_id → counterparties.id`
- **Entry 1:1 ShareToken**: An entry can have one share token; `share_tokens.entry_id → entries.id`
- **Entry 1:1 Confirmation**: An entry may have one confirmation; `confirmations.entry_id → entries.id`
- **Worker 1:N EvidencePacks**: A worker has many evidence packs; `evidence_packs.worker_id → workers.id`
- **Entry 1:N StatusLogs**: An entry has many status change logs; `entry_status_log.entry_id → entries.id` (but typically one active log per entry due to cascade)

### ER Diagram (generated from SQLAlchemy models)

```mermaid
erDiagram
    WORKERS ||--o{ ENTRIES : "owns"
    WORKERS ||--o{ EVIDENCE_PACKS : "owns"
    WORKERS ||--o{ CONFIRMATIONS : "is party to"
    COUNTERPARTIES ||--o{ ENTRIES : "has entries"
    ENTRIES ||--o{ ENTRY_STATUS_LOG : "logs status changes"
    ENTRIES ||--o{ SHARE_TOKENS : "generates token"
    ENTRIES ||--o{ CONFIRMATIONS : "receives confirmation"
    ENTRY_STATUS_LOG }o--o{ ENTRIES : "per entry"
    SHARE_TOKENS }o--o{ ENTRIES : "per entry"
    CONFIRMATIONS }o--o{ ENTRIES : "per entry"
    
    WORKERS {
        int id PK
        str alias UK
        str pin_hash
        str language
        bool is_active
        str consent_audio_uri
        str consent_text_version
        datetime consent_at
        datetime created_at
        datetime updated_at
    }
    
    ENTRIES {
        int id PK
        int worker_id FK
        int counterparty_id FK
        str work_date
        str site_name
        str counterparty_name
        numeric hours
        numeric days
        numeric agreed_inr
        numeric paid_inr
        numeric due_inr
        str language
        text transcript
        str audio_uri
        str audio_sha256
        str prev_hash
        str entry_hash
        str status
        int corrects_entry_id FK
        datetime created_at
    }
    
    EVIDENCE_PACKS {
        int id PK
        int worker_id FK
        str period_from
        str period_to
        str pdf_uri
        str zip_uri
        str chain_head_hash
        datetime created_at
    }
```

### Migration Workflow

1. **Create migration**: `alembic revision --head <head_revision> -m "description"`
2. **Edit upgrade/downgrade** in the generated file under `backend/app/migrations/versions/`.
3. **Apply migration**: `alembic upgrade head` from `backend/app/` directory.
4. **Current revision**: `002_add_worker_is_active` (adds `is_active` column with `server_default=TRUE`).
5. **Seed database**: `alembic upgrade head` creates tables; `Base.metadata.create_all(bind=engine)` in main.py lifespan also creates tables if missing.

### Initial Database Setup

- **SQLite dev**: No pre-start setup needed. Alembic migration creates the schema on first run.
- **PostgreSQL/Neon**: Set `DATABASE_URL=postgresql://USER:PASSWORD@EP-HOST.neon.tech/neondb?sslmode=require`. The `ensure_tables_ready()` middleware runs `Base.metadata.create_all(bind=engine)` once per cold start (Vercel serverless). Migration `002_add_worker_is_active` must be applied separately if the `is_active` column is needed.

---

## I. API Documentation

### API Base URL

- **Development**: `http://localhost:8000/api`
- **Production**: Deployed Vercel URL + `/api` prefix

### Authentication Requirements

- **Public endpoints**: `/api/auth/register`, `/api/auth/login`, `/api/health`
- **Protected endpoints**: All other routes require a valid JWT bearer token in the `Authorization` header.
- **Token source**: Frontend stores JWT in localStorage; axios interceptor auto-injects `Authorization: Bearer <token>` for non-contractor requests.
- **Contractor requests**: `Authorization` header deleted; token passed as URL path parameter (`/contractor/{token}`).

### Request and Response Conventions

- **JSON request bodies** for all POST/PATCH operations.
- **Response bodies** are JSON objects or arrays as documented per endpoint.
- **Error responses**: `{ "detail": "human-readable error message" }` with appropriate HTTP status code.
- **401**: Missing/expired/invalid token; frontend clears auth session.
- **403**: Authenticated but insufficient permission (e.g., wrong worker trying another's data).
- **422**: Validation error (missing required fields, invalid format, business rule violation).
- **429**: Rate limit exceeded; `Retry-After` header indicates seconds to wait.

### Error Handling

| Status | Meaning | Frontend Action |
|---|---|---|
| 401 | Unauthorized / Invalid token | `clearAuthSession()`, dispatch `AUTH_EXPIRED_EVENT` |
| 403 | Forbidden / Inactive worker | Show error detail; may indicate `is_active` check |
| 422 | Validation error | Display field-level errors from `error.response.data.detail` |
| 429 | Rate limited | Show retry message with `Retry-After` seconds |
| 500 | Server error | Log; show generic error; do not expose stack traces |

### API Endpoint Table

| Method | Endpoint | Auth Required | Description |
|---|---|---|---|
| POST | `/api/auth/register` | No | Register new worker {alias, pin, language} |
| POST | `/api/auth/login` | No | Authenticate worker {alias, pin} → JWT token |
| POST | `/api/auth/change-pin` | Yes | Change PIN after verifying current |
| PATCH | `/api/auth/language` | Yes | Update worker language preference |
| GET | `/api/health` | No | `{ "status": "ok" }` |
| GET | `/api/entries/` | Yes | List all entries for authenticated worker |
| GET | `/api/entries/{id}` | Yes | Get single entry by ID |
| POST | `/api/entries/draft` | Yes | Create voice entry draft (audio or JSON) |
| POST | `/api/entries/draft/confirm` | Yes | Confirm and persist draft entry |
| POST | `/api/entries/{id}/confirm` | Yes | Confirm entry (alternative flow) |
| POST | `/api/entries/{id}/correct` | Yes | Create correcting entry |
| POST | `/api/entries/{id}/share` | Yes | Generate one-time share token |
| GET | `/api/evidence` | Yes | Build evidence pack for period |
| GET | `/api/evidence/{id}/pdf` | Yes | Download evidence PDF |
| GET | `/api/evidence/{id}/zip` | Yes | Download evidence ZIP |
| GET | `/api/verify` | Yes | Verify hash chain integrity |
| GET | `/api/contractor/{token}` | No (token in URL) | View entry data for contractor |
| POST | `/api/contractor/{token}/respond` | No (token in URL) | Contractor responds yes/no/dispute |
| POST | `/api/voice/extract` | Yes | Extract structured fields from transcript |
| POST | `/api/voice/tts` | Yes | Text-to-speech synthesis |
| POST | `/api/voice/classify-confirmation` | Yes | Classify spoken yes/no/unclear |

### Swagger/OpenAPI Documentation

- The FastAPI app generates Swagger UI at `GET /api/docs` (or `GET /openapi.json` for the raw spec).
- Production Vercel deployment: docs may be disabled; check `/api/openapi.json` if needed.
- The `contracts/api.openapi.yaml` file is the shared, frozen contract (Day 2 joint PR only).

---

## J. Prerequisites

### Software

| Requirement | Minimum Version | Notes |
|---|---|---|
| Python | 3.12+ | `requires-python = ">=3.12"` in pyproject.toml |
| Node.js | 18+ | For frontend build (Vite) |
| Python packages | See `pyproject.toml` / `backend/requirements.txt` | `fastapi`, `uvicorn`, `sqlalchemy`, `alembic`, `passlib[bcrypt]`, `pyjwt`, `bcrypt`, `websockets`, `reportlab` |
| Git | Any recent version | For cloning and branch management |

### Accounts and Services

- **Gnani account** (optional, for production STT/TTS): API keys via `GNANI_STT_API_KEY` and `GNANI_TTS_API_KEY` environment variables.
- **Ollama** (optional, for LLM extraction): Local model setup; not currently wired into the extraction pipeline.

### Local Development Environment

- Python 3.12+ with virtual environment
- Node.js 18+ with npm
- Git cloned repository
- `SECRET_KEY` set in `.env` (generated via `python3 -c "import secrets; print(secrets.token_urlsafe(32))"`)
- `DATABASE_URL` set (defaults to `sqlite:///./saakshi.db` for local dev)

---

## K. Local Installation and Setup

### Windows PowerShell

```powershell
# 1. Clone the repository
git clone https://github.com/your-org/saakshi-github-work.git
cd saakshi-github-work

# 2. Backend virtual environment
cd backend/app
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt

# 3. Frontend dependencies
cd ..\..\frontend
npm install

# 4. Environment variable configuration
# Copy .env.example to .env and fill values
Copy-Item .env.example .env
notepad .env
# Required at minimum:
#   SECRET_KEY=   # generated with: python3 -c "import secrets; print(secrets.token_urlsafe(32))"
#   DATABASE_URL=sqlite:///./saakshi.db  # use Neon Postgres for production

# 5. Database setup (development)
# SQLite requires no prior setup; alembic creates tables on first run
cd ..\backend\app
alembic upgrade head

# 6. Starting the backend
cd ..\..\backend\app
uvicorn main:app --reload --port 8000

# 7. Starting the frontend
# From the frontend directory
cd ..\..\frontend
npm run dev
# Typically available at http://localhost:5173

# 8. Accessing the application
# Open http://localhost:5173 in a browser
# The onboarding screen shows Login; register a new worker or use credentials from tests
```

### Linux/macOS

```bash
# 1. Clone the repository
git clone https://github.com/your-org/saakshi-github-work.git
cd saakshi-github-work

# 2. Backend virtual environment
cd backend/app
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 3. Frontend dependencies
cd ../../frontend
npm install

# 4. Environment variable configuration
cp .env.example .env
# Edit .env as needed (see section L)

# 5. Database setup (development)
cd ../backend/app
alembic upgrade head

# 6. Starting the backend
cd ../..
uvicorn backend.app.main:app --reload --port 8000

# 7. Starting the frontend
cd frontend
npm run dev
# Typically available at http://localhost:5173

# 8. Accessing the application
open http://localhost:5173
```

### Verifying the Setup

- Backend: `curl http://localhost:8000/api/health` → `{"status":"ok"}`
- Frontend: navigate to `http://localhost:5173`, see onboarding screen
- Register a test worker: POST `/api/auth/register` {alias: "testworker", pin: "1234", language: "en-IN"} → 201
- Login: POST `/api/auth/login` {alias: "testworker", pin: "1234"} → 200 with JWT token

---

## L. Environment Variables

| Variable | Purpose | Required? | Example/Format |
|---|---|---|---|
| `DATABASE_URL` | Database connection string | Recommended | `sqlite:///./saakshi.db` (dev) or `postgresql://USER:PASSWORD@EP-HOST.neon.tech/neondb?sslmode=require` (prod) |
| `SECRET_KEY` | JWT signing key (≥32 chars) | **Yes** | `python3 -c "import secrets; print(secrets.token_urlsafe(32))"` → `a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2` |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | JWT expiry in minutes | No | `30` (default) |
| `SHARE_TOKEN_EXPIRY_DAYS` | Share token expiry days | No | `3` (default) |
| `SECRET_KEY` continued... | | | |
| `VOICE_IMPL` | Voice implementation: "fake" or "gnani" | No | `fake` (default) |
| `GNANI_STT_API_KEY` | Gnani STT API key ID | Required if `VOICE_IMPL=gnani` | Your Gnani-issued key |
| `GNANI_TTS_API_KEY` | Gnani TTS API key | Required if `VOICE_IMPL=gnani` | Your Gnani-issued key |
| `GNANI_STT_WSS_URL` | Gnani STT WebSocket URL | No | `wss://api.vachana.ai/stt/v3/stream` (default) |
| `GNANI_TTS_WSS_URL` | Gnani TTS WebSocket URL | No | `wss://api.vachana.ai/api/v1/tts` (default) |
| `LLM_PROVIDER` | LLM provider for extraction | No | `ollama` (default) |
| `LLM_MODEL` | LLM model name | No | Model name if using local Ollama |
| `CORS_ORIGINS` | Allowed CORS origins (comma/list) | No | `["http://localhost:5173","http://localhost:3000"]` |
| `FRONTEND_URL` | Frontend URL for share links and CORS | No | `http://localhost:5173` (dev) or `https://your-vercel-url.vercel.app` (prod) |
| `SHARE_TOKEN_LENGTH` | Length of share token bytes | No | `32` (default) |
| `AUDIO_STORAGE_PATH` | Local path for audio files | No | `./data/audio` (default) |
| `HOST` | Backend bind host | No | `0.0.0.0` (default) |
| `PORT` | Backend bind port | No | `8000` (default) |
| `DEBUG` | FastAPI debug mode | No | `False` (default) |

### Frontend Environment Variables (in `frontend/.env` or Vite env)

| Variable | Purpose | Example |
|---|---|---|
| `VITE_API_URL` | Backend API base URL (overrides `api.ts` resolveApiUrl default) | `http://localhost:8000` |
| `VITE_WS_URL` | WebSocket STT URL (overrides default) | `ws://localhost:8000/ws/stt` |

### Backend vs Frontend Variable Distinction

- **Backend** (`.env`, read by `config.py` via `pydantic-settings`): `DATABASE_URL`, `SECRET_KEY`, `VOICE_IMPL`, `GNANI_STT_API_KEY`, `GNANI_TTS_API_KEY`, `CORS_ORIGINS`, `FRONTEND_URL`, `HOST`, `PORT`, `DEBUG`, `SHARE_TOKEN_EXPIRY_DAYS`, `AUDIO_STORAGE_PATH`.
- **Frontend** (Vite automatically provides `import.meta.env.VITE_*`; or `frontend/.env`): `VITE_API_URL`, `VITE_WS_URL`.
- **No overlap**: Frontend variables are purely client-side; backend variables are server-side only.

---

## M. Running Tests

### Backend Tests

```bash
# From the repository root, enter the backend directory
cd backend

# Run all backend unit and integration tests
pytest

# Run auth-specific tests
pytest tests/test_worker_auth.py --tb=short -v

# Run voice integration tests (uses fake voice by default)
pytest tests/test_voice_integration.py --tb=short -v

# Run with a specific marker or filter
pytest -k "login" --tb=short -v
```

**Test fixtures** are in `backend/tests/test_worker_auth.py` and use an in-memory SQLite database per test. The `api_client` fixture sets up a full test client with dependency overrides, a fresh test DB, and rate-limiter reset.

### Frontend Tests

```bash
# From the frontend directory
cd frontend

# Run vitest or jest if configured
npm test

# Or run specific test files
npx vitest run src/components/*.test.tsx
```

### Ruff (Linter)

```bash
# From the project root or backend directory
ruff check .

# Fix auto-fixable issues
ruff check . --fix
```

### Black (Formatter)

```bash
# Check formatting (will fail if files are not formatted)
black --check .

# Format all files
black .
```

### TypeScript Checks

```bash
# From the frontend directory
cd frontend
npx tsc --noEmit
```

### Other Configured Validations

The CI workflow (`.github/workflows/ci.yml`) runs:
- `black --check --target-version py311 .` (Python 3.11 target)
- `ruff check .`
-pytest
- Any other configured checks

### What Each Test Suite Checks

| Test Suite | Checks |
|---|---|
| `test_worker_auth.py` | Auth flow: register, login, PIN change, language update, rate limiting, worker ownership, entry/share/evidence workflow, PIN activation, language persistence, URL normalization |
| `test_voice_integration.py` | Full voice workflow: register → STT → extract → draft → confirm → verify → evidence pack → TTS → classification; Vercel entrypoint and DATABASE_URL normalization check |
| `test_vercel_entrypoint_and_quoted_database_url` | Verifies `vercel_app.app` references `main.app`; checks route paths include `/api/health` and `/api/voice/stt`; validates `normalize_database_url()` for Neon URLs |

---

## N. Deployment

### Deployment Architecture

Saakshi is designed for deployment on **Vercel** with the following architecture:

- **Frontend**: Served as static assets from Vercel (Vite build → `dist/`).
- **Backend**: FastAPI app served as a Vercel Serverless Function; entrypoint `backend.app.main:app` (configured in `vercel.json`).
- **Database**: Neon Postgres (serverless) via `DATABASE_URL` environment variable; SQLite for local dev.
- **CORS**: Configured via `CORS_ORIGINS` env var; Vercel domain automatically appended.
- **Audio storage**: Local `/tmp/saakshi/` in serverless (read-only outside `/tmp`); swap for R2/S3 for production audio persistence.

### Frontend Deployment

1. **Build**: `cd frontend && npm run build` → produces `dist/` with static assets.
2. **Vercel deploy**: `vercel` or connect the GitHub repo to Vercel for auto-deploys.
3. **Environment variables** in Vercel dashboard:
   - `DATABASE_URL`
   - `SECRET_KEY` (≥32 chars)
   - `VOICE_IMPL=gnani` (if using real Gnani)
   - `GNANI_STT_API_KEY`
   - `GNANI_TTS_API_KEY`
   - `FRONTEND_URL` (your production URL)
   - `CORS_ORIGINS` (your production URL)
   - `SHARE_TOKEN_EXPIRY_DAYS=3`
   - `AUDIO_STORAGE_PATH=/tmp/saakshi` (Vercel serverless path)
4. **Root domain**: Deployed URL, e.g., `https://saakshi.vercel.app`.

### Backend Deployment

1. **Vercel**: The `vercel.json` at root sets `entrypoint = "backend.app.main:app"`. On deploy, Vercel builds and serves the FastAPI app as a serverless function.
2. **Other platforms** (Railway, Render, etc.): Use `uvicorn backend.app.main:app` as the startup command; set env vars identical to `.env.example`.
3. **Database migrations**: On first deploy, run `alembic upgrade head` against the production DB, or ensure `ensure_tables_ready()` creates tables via `Base.metadata.create_all(bind=engine)` on cold start.

### Database Configuration for Production

- **Neon Postgres**: Set `DATABASE_URL=postgresql://USER:PASSWORD@EP-HOST.neon.tech/neondb?sslmode=require`.
- **Connection pooling**: `normalize_database_url()` may add `+psycopg` if `psycopg2` is not installed but `psycopg` is.
- **Idle connection guard**: `pool_pre_ping=True` and `pool_recycle=300` are set for non-SQLite engines.
- **Migration application**: After initial deployment, apply migrations: `alembic upgrade head` from the backend directory.

### Environment Variables in Production

All `.env.example` variables should be set in the hosting environment. Critical ones:

| Variable | Priority |
|---|---|
| `SECRET_KEY` | Must be set; validated ≥ 32 chars |
| `DATABASE_URL` | Must be set for production (Neon or other Postgres) |
| `FRONTEND_URL` | Used for share links and CORS auto-appending |
| `VOICE_IMPL` | Set to `gnani` and provide Gnani keys for production STT/TTS |
| `GNANI_STT_API_KEY` / `GNANI_TTS_API_KEY` | Required if `VOICE_IMPL=gnani` |

### Common Deployment Problems

| Problem | Solution |
|---|---|
| 401 on all authenticated endpoints after deploy | Ensure `SECRET_KEY` is set in production env (validated in `config.py`). Check `DATABASE_URL` connects. |
| CORS errors in production | Set `FRONTEND_URL` to your production URL; `CORS_ORIGINS` will auto-append the Vercel domain. |
| Voice transcription fails in production | Set `VOICE_IMPL=gnani` and provide `GNANI_STT_API_KEY` + `GNANI_TTS_API_KEY`. |
| 500 on evidence pack generation | Ensure `AUDIO_STORAGE_PATH` points to a writable directory; on Vercel, use `/tmp/saakshi`. |
| `alembic upgrade head` fails on Neon | Ensure `psycopg[binary]` is installed; check `DATABASE_URL` format. |
| Worker login returns 401 after migration change | Run `alembic upgrade head` to apply `002_add_worker_is_active` if the `is_active` column is expected. |

---

## O. Troubleshooting

### Backend Startup Failures

| Symptom | Cause | Fix |
|---|---|---|
| `ModuleNotFoundError: No module named 'fastapi'` | Virtual environment not activated | Activate venv: `.\.venv\Scripts\activate` (Win) or `source .venv/bin/activate` (Linux/macOS) |
| `sqlite3.OperationalError: unable to open database file` | Missing `data/` directory or wrong `DATABASE_URL` | Ensure `data/` exists or set `DATABASE_URL` to valid path |
| `ValidationError: SECRET_KEY must be a strong, non-placeholder value` | `.env` has placeholder `SECRET_KEY` | Generate a real one: `python3 -c "import secrets; print(secrets.token_urlsafe(32))"` |
| `psycopg2` import error on Neon deploy | `psycopg2` not installed but `DATABASE_URL` is Postgres | Install: `pip install psycopg[binary]`; or use `normalize_database_url()` which may switch to `+psycopg` |
| `ImportError: cannot import name 'Settings' from 'app.config'` | Wrong working directory or missing `__init__.py` | Run from `backend/app/` or ensure `PYTHONPATH` includes the repo root |

### Frontend API Connection Errors

| Symptom | Cause | Fix |
|---|---|---|
| `ECONNREFUSED` or timeout on port 8000 | Backend not running or wrong port | Start backend: `uvicorn main:app --reload --port 8000`; verify port matches |
| `404 (Not Found)` on `/api/auth/login` | Wrong API base URL | Check `VITE_API_URL` in frontend `.env`; default resolves to `localhost:5173` + `/api` |
| `Authorization` header not sent | Token expired or not in localStorage | Re-login; or run `clearAuthSession()` then `loginWorker()` |
| Voice WebSocket connection fails | Wrong WS URL or Gnani not configured | Check `VITE_WS_URL`; for development, `FakeVoice` does not use WebSocket |

### Database Connection Failures

| Symptom | Cause | Fix |
|---|---|---|
| `OperationalError: could not connect to server` | `DATABASE_URL` wrong or Neon paused | Verify `DATABASE_URL`; ensure Neon project is active and not paused |
| `feat(vercel): configure multi-service vercel.json` errors | Missing env vars in Vercel dashboard | Add all required env vars from `.env.example` to Vercel project Settings |
| `ProgrammingError: no such table: workers` | Tables not created | Run `alembic upgrade head` from `backend/app/`; or check `ensure_tables_ready()` runs on startup |

### Authentication and Login Errors

| Symptom | Cause | Fix |
|---|---|---|
| `401 Invalid alias or PIN` after correct credentials | `is_active` check failing (column missing from DB) | This is the known issue: `getattr(worker, 'is_active', True)` provides backward compatibility. Apply migration `002_add_worker_is_active` if the column should exist. |
| `401` on login but register works | PIN hash mismatch or wrong credentials | Verify the 4-digit PIN; check `bcrypt.hash()` was used during registration |
| `403 Current PIN verification failed or worker account is inactive` | Worker marked inactive (`is_active=False`) | Check DB; or the `getattr()` fallback will treat as active if column missing |
| Language update returns 401 | Worker not authenticated or session expired | Re-login; ensure token is fresh and included in `Authorization` header |

### Missing Database Migrations

| Symptom | Cause | Fix |
|---|---|---|
| `ProgrammingError: column workers.is_active does not exist` | Migration `002_add_worker_is_active` not applied | Run `alembic upgrade head` from `backend/app/`. The `getattr()` fallback handles missing columns gracefully. |
| `alembic` not found | Alembic not installed | `pip install alembic` from the backend virtual environment |

### CORS Problems

| Symptom | Cause | Fix |
|---|---|---|
| `Redirect` or `Blocked by CORS` in browser | Frontend origin not in `CORS_ORIGINS` | Add frontend URL to `.env` `CORS_ORIGINS` list, or set `FRONTEND_URL` for auto-appending in production. |
| Production deployment shows CORS error | `FRONTEND_URL` not set in Vercel env | Set `FRONTEND_URL` to your production URL in Vercel Dashboard → Settings → Environment Variables. |

### Vercel Deployment Errors

| Symptom | Cause | Fix |
|---|---|---|
| Deployment fails or site shows 500 | `SECRET_KEY` missing or placeholder | Set `SECRET_KEY` to a valid ≥32-char value in Vercel Environment Variables. |
| `/api/health` returns 404 | Entrypoint misconfigured | Verify `vercel.json` has `entrypoint = "backend.app.main:app"` and the repo structure matches. |
| Voice STT WebSocket never connects | `GNANI_STT_API_KEY` not set or `VOICE_IMPL` not `gnani` | Set `VOICE_IMPL=gnani` and provide valid Gnani API keys. |
| `normalize_database_url` not working | `DATABASE_URL` format issue | Ensure URL starts with `postgresql://` or `postgres://`; the function normalizes `postgres://` to `postgresql://`. |

### Voice/Audio Processing Failures

| Symptom | Cause | Fix |
|---|---|---|
| Transcript always "DEMO SAMPLE:" | Using `FakeVoice` default; not Gnani | Set `VOICE_IMPL=gnani` and provide `GNANI_STT_API_KEY` + `GNANI_TTS_API_KEY`. |
| WebSocket connection closes immediately | Network or Gnani server issue | Check `GNANI_STT_WSS_URL`; ensure API key is valid and account has credits. |
| TTS returns empty audio | Language not supported by Gnani | Supported languages: `hi-IN`, `kn-IN`, `bn-IN`, `en-IN`. Set worker language to one of these. |
| Audio not saved in evidence pack | `AUDIO_STORAGE_PATH` not writable | On Vercel, set `AUDIO_STORAGE_PATH=/tmp/saakshi`; ensure `/tmp/` is writable per serverless constraints. |

---

## P. Current Implementation Status and Limitations

### Working Functionality

- Worker registration and PIN-based login
- PIN change and language update for authenticated workers
- Voice entry draft creation with `FakeVoice` (simulated STT)
- Entry confirmation and hash chain append
- Entry listing and single-entry retrieval
- Evidence pack generation (PDF + ZIP + manifest) for authenticated worker
- Evidence pack download (PDF and ZIP)
- Hash chain verification endpoint
- Contractor one-time share and response (yes/no/dispute)
- Worker ownership isolation (each worker only sees their own entries)
- Rate limiting on login and PIN change attempts
- JWT token management (30-min expiry, auto-session clearing on expiry)
- `getattr(worker, 'is_active', True)` safe backward compatibility for missing `is_active` column

### Incomplete Functionality

- **Real Gnani STT/TTS**: Default is `FakeVoice`; production requires Gnani account and API keys.
- **LLM-based extraction**: Not currently wired; reserved for future Ollama or hosted LLM integration.
- **Offline queue and sync**: Not implemented; all data must be sent in a single request.
- **IVR/phone-call channel**: Not implemented.
- **Additional languages beyond Gnani set**: Only `hi-IN`, `kn-IN`, `bn-IN`, `en-IN` supported.

### Known Issues

1. **Production auth failure when `is_active` column missing from Neon DB**: The partner commits in `753b1c8` added `is_active` checks, but migration `002_add_worker_is_active` was never applied to production Neon PostgreSQL. The `getattr(worker, 'is_active', True)` fix (already applied in `auth.py`) provides backward compatibility — auth works whether or not the column exists. To enable full inactive-worker rejection, apply the migration to the production database.

2. **1 pre-existing Vercel env test failure**: `test_vercel_entrypoint_and_quoted_database_url` fails in the CI suite but is unrelated to the auth/is_active changes; it tests Vercel entrypoint and DATABASE_URL normalization.

3. **FakeVoice transcript always starts with "DEMO SAMPLE:"**: This is expected behavior of the development fallback; replace with `VOICE_IMPL=gnani` and valid Gnani keys for production.

### External Service Dependencies

- **Gnani account** (optional): `GNANI_STT_API_KEY`, `GNANI_TTS_API_KEY`, and `VOICE_IMPL=gnani` for production STT/TTS.
- **Ollama** (optional): Local LLM for extraction; not currently wired.
- **PostgreSQL/Neon**: Required for production; SQLite for local development.

### Outstanding Configuration Requirements

- `SECRET_KEY` must be set in any non-development environment (validated in `config.py`).
- `DATABASE_URL` must be set for production deployments (Neon Postgres recommended).
- `FRONTEND_URL` should be set for correct share links and CORS in production.
- `VOICE_IMPL` and Gnani keys should be set if real voice processing is needed.
- `CORS_ORIGINS` should include the production frontend URL.

---

## Q. Future Improvements

- Integrate real Gnani STT/TTS with proper API key configuration.
- Add LLM-based extraction (Ollama or hosted) for improved field extraction from transcripts.
- Implement offline queue and sync for intermittent connectivity.
- Add IVR/phone-call channel for feature phones without smartphone access.
- Expand supported languages beyond Gnani's current set.
- Add wage-rate benchmarks by region.
- Build NGO/web dashboard for contractors and legal-aid clinics.
- Implement payments integration (out of scope for MVP).
- Add legal-administration documentation clarifying that records are "a dated record" not "legal proof."
- Write automated accuracy tests for extraction (currently manual/visual verification).

---

## R. Contribution Guidelines

### Branch Creation

```bash
# From the repository root
git checkout main
git pull origin main
git checkout -b feature/short-description
# Or for bug fixes:
git checkout -b fix/short-description
```

### Making Changes

1. **Follow folder ownership**: Developer A owns voice/ and contracts/; Developer B owns backend/app/ and frontend/src/.
2. **Run existing tests** before submitting: `cd backend && pytest` and `cd frontend && npm test`.
3. **Format code** with Black: `black .`; lint with Ruff: `ruff check .`.
4. **Do not modify `.env` or commit secrets**: Add new env-var names to `.env.example` if needed, but never commit actual values.
5. **Keep API contracts consistent**: If adding new endpoints, update `contracts/api.openapi.yaml` and `contracts/voice_interface.py` as appropriate.
6. **Write tests** for new functionality; ensure existing tests still pass.
7. **Commit messages**: Use clear, descriptive present-tense verb phrases (e.g., "Add worker language persistence endpoint", "Fix Ruff import ordering in migration").

### Pull Request Process

1. Ensure all tests pass (`pytest` in backend, `npm test` in frontend).
2. Run `black .` and `ruff check . --fix` to format/lint.
3. Update `README.md` if user-facing behavior changes.
4. Submit PR against `main`; at least one maintainer review required.
5. Address review feedback; keep history clean (squash commits if requested).

### Coding Conventions

- **Python**: Follow PEP 8; use type annotations (Pydantic v2 / SQLAlchemy 2.0); black format (py311 target); ruff lint.
- **TypeScript/React**: Use functional components + hooks; `const` over `let`/`var`; Tailwind for styling; PropTypes not used (strict TypeScript).
- **Git**: Conventional commit style recommended; feature branches; PR description should summarize what and why.

---

## S. License

**No license file is currently present** in the repository. The project is a college-level technical project and no formal license declaration has been made. If you intend to use or redistribute this code, please contact the repository maintainers or check with the original project supervisors for permission.

--- 

*Generated for the Saakshi project on November 11, 2026.*