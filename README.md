# AI Audio Editor

Browser-based audio editor with a deterministic backend. Currently on branch
`v2-stabilization` during the v2.5 migration (Postgres + Redis + object storage
+ auth). See `docs/v2.5-architecture-design.md` for the full design.

---

## Prerequisites

- **Docker Desktop** (for Postgres, Redis, optional MinIO)
- **Python 3.10+** (dev is on 3.10.11)
- **Node 18+** + **npm** (frontend)
- **FFmpeg** on PATH (`ffmpeg -version` should print version info)

## Quickstart

```bash
# 1. Infrastructure (Postgres + Redis; MinIO is optional unless STORAGE_BACKEND=s3)
docker compose up -d postgres redis

# 2. Backend env
cp backend/env.example backend/.env
# (edit backend/.env and set JWT_SECRET; other defaults are fine for local dev)

# 3. Backend deps (first time, or after pyproject.toml changes)
cd backend
python -m venv .venv
.venv/Scripts/python.exe -m pip install -e ".[dev]"

# 4. Create tables
.venv/Scripts/python.exe ../scripts/init_db.py

# 5. Run the API (one terminal)
.venv/Scripts/python.exe -m uvicorn app.main:app --reload --port 8000

# 6. Run the worker (another terminal)
.venv/Scripts/dramatiq.exe app.workers.entrypoint -p 1 -t 1

# 7. Run the frontend (another terminal)
cd ../frontend
npm install
npm run dev
```

Open http://localhost:5173.

## End-to-end smoke

With all three processes running (compose, API, worker):

```bash
cd backend
.venv/Scripts/python.exe ../scripts/smoke.py
```

Expected: one `[OK]` per step, ending with `SMOKE PASSED`. Exercises register →
login → upload → trim → export.

## Running tests

```bash
cd backend
.venv/Scripts/python.exe -m pytest
```

> ⚠ The existing test harness (`tests/conftest.py`) targets the pre-v2.5 SQLite
> stack and will fail against the current auth-gated API. Harness rewrite is
> Stage C of the v2.5 plan; expect fresh auth + async + IDOR + storage tests.

## Known issues / rough edges

- **Schema changes require dropping the dev DB.** v2.5 uses SQLAlchemy
  `create_all` — it creates new tables but does not drop removed columns. After
  a schema edit:
  ```bash
  docker compose down -v postgres
  docker compose up -d postgres
  python scripts/init_db.py
  ```
- **OAuth is hand-rolled** (no Authlib). Google + Apple providers in
  `backend/app/services/oauth_service.py`. Leave client IDs blank to disable.
- **`WORKER_STALE_RUNNING_MIN`** must exceed `WORKER_TIME_LIMIT_SEC/60` or the
  API startup sweep will kill legitimately-running long jobs. Defaults (40 min /
  30 min) already satisfy this — only touch if you raise the job ceiling.
- **Signed-URL TTL = 15 min on S3.** Long-running tabs may hit 403 on media
  load; the frontend's retry-on-error path is planned for Stage E.
- **MinIO bucket init** happens via the `minio-init` one-shot container in
  `docker-compose.yml`. If buckets are missing, re-run:
  `docker compose up --no-deps minio-init`.

## Repo layout

```
backend/                  FastAPI + SQLAlchemy + Dramatiq
├── app/
│   ├── api/              routers (auth, assets, operations, exports)
│   ├── services/         business logic
│   ├── processors/       pure DSP (FFmpeg + librosa, unchanged by v2.5)
│   ├── storage/          Storage protocol (local + s3)
│   ├── workers/          Dramatiq broker + actors + recovery
│   ├── core/             security, deps, errors
│   ├── models/           SQLAlchemy ORM
│   └── schemas/          Pydantic
└── tests/                pytest suite

frontend/                 React 19 + Vite + Tailwind + Zustand
└── src/
    ├── api/              HTTP client wrappers
    ├── auth/             login / register / OAuth / OTP / AuthGate
    ├── audio/            WaveSurfer wrapper
    ├── editor/           operation UI
    ├── store/            Zustand stores (editor + auth)
    └── layout/           Shell, UploadZone, Toolbar, ExportPopover

scripts/
├── init_db.py            one-shot create_all
└── smoke.py              end-to-end smoke

docs/
├── v2.5-architecture-design.md     approved v2.5 design
├── ai-integration-context.md       AI-integration briefing (future)
├── prd.md                          product requirements
├── api-contract.md                 HTTP contract
└── operations.schema.json          operation JSON schema
```

## License

TBD.
