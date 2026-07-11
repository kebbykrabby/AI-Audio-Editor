# AI Audio Editor

A browser-based, DAW-style audio editor for cleaning up spoken-word recordings — with an AI review layer that proposes edits and lets you approve them before any audio changes.

![Editor screenshot placeholder — capture the /editor screen against a real recording and save to docs/screenshot-editor.png](docs/screenshot-editor.png)

---

## Highlights

- **Non-destructive editing** — every edit creates a new derived asset linked to its parent; linear undo/redo with a session-wide version history you can click to jump between. Editing after undo discards the forward history, exactly like a browser's back/forward stack.
- **18 first-class DSP operations** exposed through a keyboard-driven toolbar: trim, delete, fade in/out, gain, gain-over-range, normalize, reverse, reverse-over-range, remove-silence, speed, mono mixdown, swap channels, extract channel, split channels, merge channels, batch remove-segments (with crossfade), and batch censor-segments.
- **AI features, all with review-before-apply** — the AI proposes; the user approves. No AI feature ever mutates audio on its own.
  - **Filler-word removal** — transcribes the audio, flags fillers with confidence scores, lets you toggle each region and confidence-floor them in bulk, then applies a `remove_segments` with a crossfade.
  - **Curse-word censorship** — matches user + built-in word lists (exact / stem-variants / phonetic matchers), previews each detection, and applies one of four modes: **beep, mute, cut, or reverse-and-pitch-shift**.
  - **Natural-language editing** — describe what you want in plain English; an LLM produces a validated multi-step plan of the operations above; you toggle steps off or refine the prompt before applying.
- **Async job model** — every DSP or AI operation is enqueued to a background worker; the frontend polls until complete and pushes the resulting derived asset onto history. No client-side audio processing — the browser plays and displays only.
- **Multi-user auth** — email + password, Google OAuth, Apple Sign In, email verification (gates the first export for password-signup users), and a forgot / reset password flow.
- **Per-user AI rate limits** enforced at admission time using DB-based sliding windows.

## Architecture

Two-tier: a React SPA talks to a FastAPI backend over a JSON HTTP contract. Long-running work runs on separate Dramatiq worker pools so slow AI transcription can never block interactive DSP.

```
┌───────────────┐        HTTPS/JSON        ┌─────────────────────┐
│  React SPA    │ ───────────────────────▶ │  FastAPI            │
│  (Vite build) │                          │  ├─ auth / assets /  │
│               │                          │  │  operations /     │
│  Zustand      │                          │  │  exports / ai     │
│  WaveSurfer   │                          │  └─ signed URLs      │
└───────┬───────┘                          └───────┬──────────────┘
        │  streams audio + waveform peaks          │
        │  from signed URLs (S3 or /files/*)       │
        ▼                                          ▼
┌───────────────┐                          ┌─────────────────────┐
│  Object store │◀──── put/get ────────────│  PostgreSQL         │
│  (S3 / MinIO  │                          │  users, assets,     │
│   or local FS)│                          │  operations, ...    │
└───────────────┘                          └───────┬──────────────┘
                                                   │ enqueue
                                                   ▼
                                          ┌─────────────────────┐
                                          │  Redis  (broker)    │
                                          └───────┬──────────────┘
                                                  │
                             ┌────────────────────┼────────────────────┐
                             ▼                                         ▼
                    ┌────────────────┐                       ┌────────────────┐
                    │  DSP worker    │                       │  AI worker     │
                    │  FFmpeg +      │                       │  Whisper +     │
                    │  librosa       │                       │  LLM provider  │
                    │  (fast queues) │                       │  (slow queue)  │
                    └────────────────┘                       └────────────────┘
```

**How an edit flows:** `POST /assets/:id/operations` returns a 202 with an operation ID. The worker picks the job up, produces a new derived asset (with `parent_asset_id` linking back), and marks the operation `completed`. The client polls `GET /operations/:id` on a 2-second interval until it sees the terminal state, then pushes the returned asset onto its history stack.

**How an AI review flows:** `POST /assets/:id/ai/detect-fillers` (or the equivalent) enqueues an AI job; the client polls until the operation carries a detection result. The result is rendered as a reviewable region list with confidence sliders and per-row toggles. Only when the user approves does the client enqueue a follow-up deterministic operation (`remove_segments` for fillers, `censor_segments` for profanity, or the LLM's step chain for NLE) to actually change the audio.

## Tech stack

**Frontend** — React 19 · TypeScript · Zustand 5 · WaveSurfer.js 7 · Vite 8 · Tailwind CSS v4 · shadcn/Radix primitives · sonner · react-router-dom v7 · lucide-react.

**Backend** — Python 3.10+ · FastAPI · Pydantic v2 · SQLAlchemy (async) · Dramatiq (Redis broker) · PostgreSQL · argon2id password hashing · PyJWT · httpx.

**DSP** — FFmpeg (audio filters, exports) · librosa (silence detection, spectral analysis).

**AI** — faster-whisper (local Whisper, no API keys required) · Google Gemini via `google-genai` (default LLM provider; free-tier friendly) · Anthropic and OpenAI providers behind the same `LLMProvider` protocol.

**Storage** — S3-compatible object store (AWS S3, Cloudflare R2, or MinIO for dev) with signed URLs; a local filesystem backend is available for zero-infra development.

**Infra** — docker-compose orchestrates Postgres, Redis, and MinIO for local dev.

## Key engineering decisions

- **Review-before-apply is a product invariant, not a suggestion.** Every AI feature stops at "here's what I propose". The commit step is a separate, deterministic operation the user explicitly approves. This lets the system use less-than-perfect models without eroding user trust.
- **Non-destructive version chain via `parent_asset_id`.** Every edit produces a new asset row; the parent link forms a chain that both powers undo/redo and lets an interrupted session resume by walking the chain from the persisted tip up to the root. History labels are session-local; the parent chain is authoritative.
- **Two worker pools, not one.** DSP operations are FFmpeg-bound and finish in seconds. AI ops call out to transcription or LLM providers and can block for minutes on the free tier. Running them in the same pool would cause head-of-line blocking of every interactive edit; splitting the pools kept the DSP queue responsive without extra tuning.
- **Provider-abstracted AI.** `TranscriptionProvider` has Fake / local-Whisper / OpenAI implementations; `LLMProvider` has Fake / Gemini / Anthropic / OpenAI. Tests default to the Fakes (zero network, deterministic outputs). Switching providers in dev or prod is one `.env` change.
- **Clean-cut crossfades.** `remove_segments` performs each removal with a short crossfade around the cut point rather than a hard splice, avoiding audible pops when trimming close to speech.
- **Signed URLs rotate.** The backend hands out 10-minute signed URLs; the client pre-emptively re-fetches asset URLs every 8 minutes and also recovers from a media-error event by refreshing on the spot.
- **CSRF + refresh cookie + short-lived access token.** 15-minute JWT access tokens carried in `Authorization`; 30-day rotated refresh tokens stored in a `HttpOnly` cookie; double-submit CSRF on refresh; refresh-token reuse detection triggers family-wide revocation.
- **Email verification gates the first export.** Password-signup users see a 6-digit-code modal the first time they try to export; OAuth users skip it because the provider has already vouched for the email.

## Getting started

**Prerequisites**

- Docker Desktop
- Python 3.10+
- Node 18+ and npm
- FFmpeg on your `PATH`

**One-line dev boot** (once the venv and node_modules are in place; see below for first-time setup):

```bash
python scripts/dev_up.py
```

This starts Docker services (Postgres, Redis, MinIO), the API on `:8000`, DSP and AI workers, and the Vite dev server on `:5173`, with color-tagged logs from each service.

**First-time setup**

```bash
# 1. Environment
cp backend/env.example backend/.env
# Edit backend/.env: set JWT_SECRET; the defaults are fine for everything else.

# 2. Backend deps
cd backend
python -m venv .venv
.venv/Scripts/python.exe -m pip install -e ".[dev]"    # Windows
# .venv/bin/python -m pip install -e ".[dev]"          # macOS/Linux

# 3. Frontend deps
cd ../frontend
npm install
```

Open http://localhost:5173.

**Optional providers** — Google/Apple sign-in and paid LLM providers are wired but disabled by default. See [`docs/OAUTH_SETUP.md`](docs/OAUTH_SETUP.md) for provider setup.

## Testing

**Backend** — `pytest` suite covers auth (register/login/refresh/OAuth callback/email verify/password reset), asset upload + list + delete, all 18 DSP operations end-to-end via the worker, all three AI features (filler detection, profanity detection, NLE plan generation), export flow with the email-verification gate, and cross-user IDOR protection.

```bash
cd backend
.venv/Scripts/python.exe -m pytest -q
# 268 passed, 7 skipped
```

**Frontend** — `tsc -b` type-checks the whole tree; `vite build` produces a production bundle. There is no browser test suite yet — the UI is validated by driving the app against a live backend.

## Status

**On this branch:** the reskin, the version-history panel, the Dashboard, the forgot/reset password flow, and all three AI features are implemented and tested. Backend tests are green (268 pass). Frontend type-checks and builds clean.

**Roadmap**

- Dark mode (design tokens are already keyed on CSS variables so the switch is one `@media (prefers-color-scheme: dark)` block).
- Server-sent events for operation status, replacing the polling loop.
- Bulk operations across the project list.
- Per-user quota display so the UI can warn before an AI rate-limit rejection.
