# Saakshi

**Saakshi** (Hindi and Kannada for *"witness"*) is a worker-held, voice-first wage ledger built for daily-wage and migrant workers to maintain a structured, tamper-evident record of their work and pay directly from their phone.

---

## Problem Statement

Informal daily-wage and migrant workers frequently work without written contracts or employer-independent pay logs. Paper notes are easily lost, damaged, or unavailable when workers move across sites, while employer-managed records are controlled by the same party that may delay or withhold wages. When pay disputes arise, workers often lack a dated, verifiable employment and payment history to present to labour helplines, NGOs, or legal-aid clinics.

---

## Solution

Saakshi gives workers an independent, voice-driven record of daily work, agreed wages, payments received, and unpaid dues:

1. **Quick Onboarding & PIN Lock** — Workers register with an alias, select their preferred language, and secure their ledger with a 4-digit PIN.
2. **Voice Wage Entry** — Workers speak naturally about their workday (for example: site, contractor, hours or days worked, agreed pay, and amount paid).
3. **Structured Extraction & Spoken Read-Back** — Spoken narration is transcribed and structured into clear fields, with any balance due (`agreed - paid`) computed automatically. When critical details are missing, Saakshi asks focused clarification questions and reads the entry back aloud for verification before saving.
4. **Append-Only, Tamper-Evident Ledger** — Once confirmed by the worker, entries are sealed in chronological order using a cryptographic hash chain. Entries are never silently overwritten; corrections are recorded as new linked entries.
5. **Two-Sided Contractor Confirmation** — Workers can generate a one-time link for any confirmed entry so a contractor or supervisor can confirm or dispute it (by voice or buttons, with an optional reason) without signing up or installing an app. Unanswered entries remain explicitly marked rather than treated as accepted.
6. **Integrity Check & Evidence Packs** — Workers can verify that their ledger history is intact and export any date range as a dated **Evidence Pack** consisting of a formatted PDF wage summary and a ZIP archive with the manifest, summary, and recorded voice clips.

---

## Supported Languages

- **Hindi**
- **Kannada**
- **Bengali**
- **English**

Language preferences apply across the interface, speech recognition, and spoken read-back, and can be switched at any time in settings.

---

## Core Design Principles

- **Worker-Owned Privacy** — Wage logs belong to the worker and stay private unless the worker explicitly generates a share link or exports an evidence pack.
- **Read-Back Before Saving** — Entries are presented and read back aloud before confirmation, ensuring workers can verify numbers and details without needing to type or read every script fluently.
- **Unconfirmed Never Means Agreed** — Contractor non-response or dispute is recorded transparently alongside confirmed entries, distinguishing between draft, worker-confirmed, shared, contractor-confirmed, disputed, and unconfirmed records.
- **Dated Record, Not Legal Advice** — Saakshi creates a dated, tamper-evident two-sided record to aid wage-recovery helplines and case workers; formal legal weight depends on local labour authorities and clinics.

---

## Who It Serves

- **Daily-Wage & Migrant Workers** — Keep a portable, verifiable history of work, partial payments, and pending dues across sites and employers.
- **Contractors & Site Supervisors** — Quickly confirm or dispute shared wage entries from a link with zero registration.
- **NGOs, Labour Helplines & Legal-Aid Clinics** — Receive clear date-range PDF summaries, integrity verification status, and original voice recordings when assisting workers.
