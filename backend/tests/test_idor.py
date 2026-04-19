"""IDOR protection: user A must never see or touch user B's resources.

Seeds user B with an asset + operation + export. User A (unrelated) hits every
authenticated endpoint that takes a resource id. Every call must return 404 —
never 403 — so the response can't be used to probe for existence.
"""
from __future__ import annotations

import pytest
import pytest_asyncio

from .conftest import drain_jobs_async


pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture()
async def seeded_b(client, stub_broker, auth_user_b, stereo_music_wav):
    """User B uploads, runs a trim, and queues an export. Returns their ids."""
    B = auth_user_b

    # Upload
    with open(stereo_music_wav, "rb") as f:
        up = await client.post(
            "/api/assets/upload",
            headers=B["headers"],
            files={"file": ("b.wav", f, "audio/wav")},
        )
    assert up.status_code == 202
    asset_id = up.json()["assetId"]

    # Drain upload
    await drain_jobs_async(stub_broker)

    # Trim → operation
    op = await client.post(
        f"/api/assets/{asset_id}/operations",
        headers=B["headers"],
        json={"type": "trim", "parameters": {"start_sec": 0.1, "end_sec": 0.5}},
    )
    assert op.status_code == 202
    op_id = op.json()["operationId"]
    await drain_jobs_async(stub_broker)

    # The completed operation has an output asset — used for export target
    op_poll = await client.get(f"/api/operations/{op_id}", headers=B["headers"])
    derived_id = op_poll.json()["asset"]["assetId"]

    # Export
    ex = await client.post(
        f"/api/assets/{derived_id}/export",
        headers=B["headers"],
        json={"format": "wav"},
    )
    assert ex.status_code == 202
    export_id = ex.json()["exportId"]
    await drain_jobs_async(stub_broker)

    return {
        "asset_id": asset_id,
        "derived_asset_id": derived_id,
        "operation_id": op_id,
        "export_id": export_id,
    }


def _cases():
    """(method, url_template, json_body, label) for every id-scoped endpoint."""
    return [
        ("GET", "/api/assets/{asset_id}", None, "get asset by id"),
        (
            "POST",
            "/api/assets/{asset_id}/operations",
            {"type": "trim", "parameters": {"start_sec": 0.1, "end_sec": 0.2}},
            "enqueue operation on asset",
        ),
        ("GET", "/api/operations/{operation_id}", None, "get operation"),
        (
            "POST",
            "/api/assets/{asset_id}/export",
            {"format": "wav"},
            "enqueue export for asset",
        ),
        ("GET", "/api/exports/{export_id}", None, "get export"),
    ]


@pytest.mark.parametrize("method,url_template,body,label", _cases())
async def test_user_a_cannot_access_user_b_resource(
    client, auth_user, seeded_b, method, url_template, body, label,
):
    """User A hits endpoint with B's ids. Must return 404.

    The assertion is strict on 404 — not 'not 200' — because 403 would leak
    the fact that the resource exists and belongs to someone else.
    """
    url = url_template.format(**seeded_b)
    if method == "GET":
        r = await client.get(url, headers=auth_user["headers"])
    elif method == "POST":
        r = await client.post(url, headers=auth_user["headers"], json=body)
    else:
        raise AssertionError(f"unsupported method {method}")

    assert r.status_code == 404, (
        f"IDOR exposed ({label}): status={r.status_code}, body={r.text[:200]}"
    )


async def test_user_b_can_still_access_own_resources(client, auth_user_b, seeded_b):
    """Sanity check: the seeded user's own GETs work. Guards against a bug
    where everyone gets 404 (which would make the IDOR tests vacuously pass)."""
    r1 = await client.get(
        f"/api/assets/{seeded_b['asset_id']}", headers=auth_user_b["headers"]
    )
    assert r1.status_code == 200

    r2 = await client.get(
        f"/api/operations/{seeded_b['operation_id']}", headers=auth_user_b["headers"]
    )
    assert r2.status_code == 200
    assert r2.json()["status"] == "completed"

    r3 = await client.get(
        f"/api/exports/{seeded_b['export_id']}", headers=auth_user_b["headers"]
    )
    assert r3.status_code == 200
    assert r3.json()["status"] == "completed"
