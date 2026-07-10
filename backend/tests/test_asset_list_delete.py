"""GET /api/assets (Dashboard listing) + DELETE /api/assets/:id.

Doesn't upload real audio — it inserts Asset rows directly for test speed and
determinism. The upload path is exercised elsewhere.
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from .conftest import register_user


pytestmark = pytest.mark.asyncio


async def _make_asset(
    db,
    *,
    user_id: str,
    kind: str = "original",
    status: str = "ready",
    filename: str = "song.wav",
    duration: float = 12.5,
    parent_id: str | None = None,
    created_offset_min: int = 0,
):
    from app.models.asset import Asset

    now = datetime.utcnow() - timedelta(minutes=created_offset_min)
    a = Asset(
        user_id=user_id,
        type=kind,
        status=status,
        parent_asset_id=parent_id,
        filename=filename,
        duration_sec=duration,
        sample_rate=44100,
        channels=2,
        file_size_bytes=1024,
        created_at=now,
        updated_at=now,
    )
    db.add(a)
    await db.commit()
    return a


async def test_list_assets_returns_only_owned_originals(client):
    user_a = await register_user(client)
    user_b = await register_user(client, email="other@example.com")

    from app.database import async_session

    async with async_session() as db:
        a1 = await _make_asset(db, user_id=user_a["userId"], filename="mine1.wav", created_offset_min=5)
        a2 = await _make_asset(db, user_id=user_a["userId"], filename="mine2.wav", created_offset_min=0)
        await _make_asset(db, user_id=user_a["userId"], kind="derived", filename="derived.wav", parent_id=a1.id)
        await _make_asset(db, user_id=user_b["userId"], filename="theirs.wav")

    r = await client.get("/api/assets", headers=user_a["headers"])
    assert r.status_code == 200
    data = r.json()
    filenames = [a["filename"] for a in data["assets"]]
    assert filenames == ["mine2.wav", "mine1.wav"], f"expected newest-first, got {filenames}"

    # user_b's asset must not appear.
    r = await client.get("/api/assets", headers=user_b["headers"])
    data = r.json()
    filenames = [a["filename"] for a in data["assets"]]
    assert filenames == ["theirs.wav"]


async def test_list_assets_excludes_soft_deleted(client):
    user = await register_user(client)

    from app.database import async_session

    async with async_session() as db:
        keep = await _make_asset(db, user_id=user["userId"], filename="keep.wav")
        remove = await _make_asset(db, user_id=user["userId"], filename="remove.wav")

    r = await client.delete(f"/api/assets/{remove.id}", headers=user["headers"])
    assert r.status_code == 204

    r = await client.get("/api/assets", headers=user["headers"])
    filenames = [a["filename"] for a in r.json()["assets"]]
    assert "keep.wav" in filenames
    assert "remove.wav" not in filenames


async def test_delete_assets_is_idempotent(client):
    user = await register_user(client)

    from app.database import async_session

    async with async_session() as db:
        a = await _make_asset(db, user_id=user["userId"])

    r1 = await client.delete(f"/api/assets/{a.id}", headers=user["headers"])
    r2 = await client.delete(f"/api/assets/{a.id}", headers=user["headers"])
    r3 = await client.delete("/api/assets/unknown-id", headers=user["headers"])
    # All three must return 204 — Dashboard trash button can't tell it's dead.
    assert r1.status_code == r2.status_code == r3.status_code == 204


async def test_delete_asset_across_users_denied(client):
    user_a = await register_user(client)
    user_b = await register_user(client, email="two@example.com")

    from app.database import async_session

    async with async_session() as db:
        a = await _make_asset(db, user_id=user_a["userId"])

    # user_b tries to delete user_a's asset — service returns None → 204
    # (silent, since anti-enumeration; the delete didn't actually happen).
    r = await client.delete(f"/api/assets/{a.id}", headers=user_b["headers"])
    assert r.status_code == 204

    # Confirm the asset is still visible to user_a.
    r = await client.get("/api/assets", headers=user_a["headers"])
    ids = [x["assetId"] for x in r.json()["assets"]]
    assert a.id in ids


async def test_get_asset_after_delete_still_works(client):
    """Design decision: get_asset_for_user does NOT filter by deleted_at so an
    in-progress editor session on the same asset keeps working."""
    user = await register_user(client)

    from app.database import async_session

    async with async_session() as db:
        a = await _make_asset(db, user_id=user["userId"])

    await client.delete(f"/api/assets/{a.id}", headers=user["headers"])

    r = await client.get(f"/api/assets/{a.id}", headers=user["headers"])
    assert r.status_code == 200
    assert r.json()["assetId"] == a.id
