# Saakshi — Worker-Held Voice Wage Ledger

**Saakshi** (Hindi and Kannada for *"witness"*) is a voice-first wage ledger product built for daily-wage and migrant workers. Instead of relying on paper slips or employer-controlled logs, workers can document daily work, agreed wages, payments received, and pending dues simply by speaking from their phone.

Built as part of the **So Bharat Internship Program by Gnani AI**.

---

## Why Saakshi

What if a worker could create a reliable daily wage record just by speaking?

In informal construction, agricultural, and contract work, workers often operate without written agreements. Paper notes get lost across job sites, and employer-kept logs sit with the party controlling pay. **Saakshi puts the record in the worker's hands** — turning brief spoken updates into structured, two-sided, tamper-evident records they can verify and export whenever support is needed.

---

## What It Does

- **🎙️ Voice-First Wage Recording** — Workers record a natural spoken summary of their workday (site, contractor or supervisor, hours or days worked, agreed amount, and amount paid), supporting code-mixed everyday speech.
- **🧠 Structured Extraction & Clarification** — Spoken audio is transcribed into structured wage fields, while pending dues (`agreed - paid`) are computed deterministically. When essential details are missing, Saakshi asks a focused follow-up question and allows quick manual edits before saving.
- **🔊 Spoken Read-Back Verification** — Before sealing an entry, Saakshi reads the structured summary aloud in the worker's preferred language so they can confirm accuracy without needing to type or read every script fluently.
- **🔐 Append-Only, Tamper-Evident Ledger** — Confirmed entries are sealed chronologically using SHA-256 hash chaining alongside audio and transcript digests. Records cannot be silently rewritten; corrections are added as new linked entries, and full chain integrity can be checked at any time.
- **🤝 Two-Sided Contractor Confirmation** — Workers can generate a one-time share link for any confirmed entry. Contractors or supervisors open the link with zero sign-up or app install to confirm or dispute the entry (by voice or buttons, with an optional dispute reason). Unanswered links remain explicitly recorded as unconfirmed — silence is never treated as agreement.
- **📄 Evidence Pack Exports** — Workers can select any date range and download a dated PDF wage summary plus a ZIP archive containing the manifest, PDF summary, and original recorded voice clips to share with NGOs, labour helplines, or legal-aid clinics.
- **🔒 Private PIN-Locked Access** — Two-step onboarding with alias, preferred language, and a 4-digit PIN keeps each worker's ledger private until they explicitly choose to share or export.

---

## Supported Languages

Saakshi works across **Hindi**, **Kannada**, **Bengali**, and **English** for interface navigation, voice recognition, and spoken read-back, and users can switch languages anytime in settings.

---

## Product Workflow

1. **Onboard or Sign In** — Pick a language, set an alias, and lock the ledger with a 4-digit PIN.
2. **Record Daily Work** — Hold to speak about the day's site, contractor, hours/days, agreed wage, and amount paid.
3. **Listen & Confirm** — Review extracted fields, listen to spoken read-back, and confirm to seal the entry onto the hash chain.
4. **Request Contractor Confirmation** — Share a one-time link from ledger history for two-sided confirmation or dispute capture.
5. **Verify & Export** — Run a ledger integrity check and generate a PDF + audio ZIP Evidence Pack for any date range.

---

## What It Uses

- **Voice AI (STT & TTS):** Gnani AI Speech-to-Text (`prisma-v3.0`) and Text-to-Speech (`timbre-v3.0`), plus a simulated voice mode for local evaluation.
- **Extraction & Guardrails:** Deterministic arithmetic/rule extraction paired with configurable LLM parsing (Gemini or Ollama) and automatic clarification prompts.
- **Cryptography & Exports:** SHA-256 hash chaining across ledger entries, transcript/audio hashing, and generated PDF summaries bundled with audio archives.
- **Web Application & Data:** React, TypeScript, and Tailwind CSS frontend backed by a FastAPI service and PostgreSQL (Neon) / SQLite storage.

---

## Scope Note

Saakshi is designed to make everyday work and payment documentation accessible, private, and verifiable for workers. It creates a dated, two-sided record to assist labour helplines and case workers — it does not replace legal counsel or guarantee automatic legal admissibility.
