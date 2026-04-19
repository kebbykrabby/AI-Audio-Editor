"""Create (or re-create) all tables against the configured Postgres.

Run once after `docker compose up -d postgres`, or any time the schema
changes. Safe to re-run: create_all is a no-op for existing tables.

    cd backend && .venv/Scripts/python.exe ../scripts/init_db.py

To wipe the dev DB and start fresh:

    docker compose down -v postgres && docker compose up -d postgres
    # wait a few seconds for Postgres to become healthy, then:
    python scripts/init_db.py

Alembic is explicitly out of scope for v2.5 (see docs/v2.5-architecture-design.md
§5). create_all does NOT drop removed columns — schema changes require the wipe
above.
"""
from __future__ import annotations

import asyncio
import sys

# Ensure the backend package is importable when run from repo root.
from pathlib import Path
_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "backend"))

# Import order matters: registering all models before create_all.
from app.database import Base, engine  # noqa: E402
from app.models import asset, operation, export, user  # noqa: E402,F401


async def main() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    tables = sorted(Base.metadata.tables.keys())
    print(f"Created/verified {len(tables)} tables:")
    for t in tables:
        print(f"  {t}")


if __name__ == "__main__":
    asyncio.run(main())
