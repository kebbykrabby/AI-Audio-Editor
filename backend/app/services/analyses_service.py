"""Transcript cache.

A WordLevelTranscript is deterministic for a given (asset, model_version,
language). Persisting it once and reusing across AI calls is the difference
between a 30-second feature and a 30-second × N features.

One DB row per (asset_id, kind, model_version) — enforced by the UNIQUE index
on `analyses`. Transcript JSON lives in storage at
`users/{uid}/assets/{aid}/analyses/transcript_{model}.json` and is consumed
server-side only (no signed URLs).
"""
from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.analysis import Analysis
from app.models.asset import Asset
from app.providers.transcription import (
    TranscriptionProvider,
    WordLevelTranscript,
)
from app.storage import Storage
from app.storage.base import ObjectNotFound


TRANSCRIPT_KIND = "whisper_transcript"


def _transcript_key(user_id: str, asset_id: str, model_version: str) -> str:
    # Replace slashes/colons that some model_version strings might contain so
    # they don't break the key hierarchy.
    safe_model = model_version.replace("/", "_").replace(":", "_")
    return f"users/{user_id}/assets/{asset_id}/analyses/transcript_{safe_model}.json"


def get_cached_transcript(
    db: Session, asset_id: str, model_version: str
) -> Analysis | None:
    res = db.execute(
        select(Analysis).where(
            Analysis.asset_id == asset_id,
            Analysis.kind == TRANSCRIPT_KIND,
            Analysis.model_version == model_version,
        )
    )
    return res.scalar_one_or_none()


async def load_transcript(storage: Storage, row: Analysis, tmp_dir: Path) -> WordLevelTranscript:
    dest = tmp_dir / "transcript.json"
    await storage.download_to_path(row.storage_key, dest)
    payload = json.loads(dest.read_text(encoding="utf-8"))
    return WordLevelTranscript.model_validate(payload)


async def persist_transcript(
    db: Session,
    storage: Storage,
    user_id: str,
    asset_id: str,
    transcript: WordLevelTranscript,
    tmp_dir: Path,
) -> Analysis:
    key = _transcript_key(user_id, asset_id, transcript.model_version)
    local = tmp_dir / "transcript.json"
    local.write_text(transcript.model_dump_json(), encoding="utf-8")
    await storage.put_file(key, local, "application/json")

    row = Analysis(
        user_id=user_id,
        asset_id=asset_id,
        kind=TRANSCRIPT_KIND,
        model_version=transcript.model_version,
        storage_key=key,
        language=transcript.language,
        cost_usd=transcript.cost_usd,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


async def get_or_create_transcript(
    db: Session,
    storage: Storage,
    asset: Asset,
    audio_path: Path,
    provider: TranscriptionProvider,
    language: str,
    tmp_dir: Path,
) -> tuple[Analysis, WordLevelTranscript]:
    """Cache-aside lookup. On hit, returns the stored transcript; on miss,
    calls the provider, persists, and returns the fresh row.
    """
    # Probe the provider for its model_version by running transcription if we
    # can't check otherwise; simpler heuristic: use a small helper that the
    # provider implementations expose. For now we round-trip by doing a
    # pre-check — we don't know model_version without calling the provider,
    # so cache-check happens AFTER transcription. To avoid wasted calls we
    # check by (asset_id, kind) first and reuse if ANY transcript exists.
    #
    # TODO(v1.1): expose model_version as a property on TranscriptionProvider
    # so we can cache-check before calling transcribe(). See
    # project_ai_filler_words.md follow-ups.
    existing_any = db.execute(
        select(Analysis).where(
            Analysis.asset_id == asset.id,
            Analysis.kind == TRANSCRIPT_KIND,
        ).limit(1)
    ).scalar_one_or_none()
    if existing_any is not None:
        try:
            transcript = await load_transcript(storage, existing_any, tmp_dir)
            return existing_any, transcript
        except ObjectNotFound:
            # Storage object vanished (manual cleanup, orphaned row). Re-run.
            db.delete(existing_any)
            db.commit()

    transcript = await provider.transcribe(audio_path, language=language)
    row = await persist_transcript(
        db, storage, user_id=asset.user_id, asset_id=asset.id,
        transcript=transcript, tmp_dir=tmp_dir,
    )
    return row, transcript
