"""Storage protocol contract tests, parametrized over implementations.

LocalStorage always runs. S3Storage (against MinIO) runs only when
`S3_TEST_ENABLED=1`. Both implementations must satisfy the same contract:
put -> exists -> download -> copy -> delete -> signed_url roundtrip.

Set these env vars to run the S3 leg:
    S3_TEST_ENABLED=1
    S3_ENDPOINT_URL=http://localhost:9000
    S3_BUCKET=audio-editor-test
    S3_ACCESS_KEY_ID=minio_dev
    S3_SECRET_ACCESS_KEY=minio_dev_secret
    S3_USE_PATH_STYLE=true
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest


pytestmark = pytest.mark.asyncio


S3_TEST_ENABLED = os.getenv("S3_TEST_ENABLED") == "1"


def _make_storage(kind: str, tmp_path: Path):
    """Construct a Storage implementation. S3 construction is lazy so the
    test skips before attempting a connection on laptops without MinIO."""
    if kind == "local":
        from app.storage.local import LocalStorage

        return LocalStorage(root=tmp_path / "store", url_prefix="/files")

    if kind == "s3":
        if not S3_TEST_ENABLED:
            pytest.skip("S3_TEST_ENABLED!=1; MinIO/S3 test disabled")
        from app.storage.s3 import S3Storage

        return S3Storage.from_settings()

    raise AssertionError(f"unknown kind {kind}")


@pytest.fixture(params=["local", pytest.param("s3", marks=pytest.mark.s3)])
def storage(request, tmp_path):
    return _make_storage(request.param, tmp_path)


# --- Contract tests -------------------------------------------------------

async def test_put_exists_download_roundtrip(storage, tmp_path):
    src = tmp_path / "src.bin"
    src.write_bytes(b"hello-storage-contract")

    key = "contract/roundtrip/file.bin"
    assert await storage.exists(key) is False

    await storage.put_file(key, src, "application/octet-stream")
    assert await storage.exists(key) is True

    dst = tmp_path / "dst.bin"
    await storage.download_to_path(key, dst)
    assert dst.read_bytes() == b"hello-storage-contract"


async def test_put_bytes_roundtrip(storage, tmp_path):
    key = "contract/bytes/file.txt"
    await storage.put_bytes(key, b"raw-bytes-ok", "text/plain")
    assert await storage.exists(key)

    dst = tmp_path / "out.txt"
    await storage.download_to_path(key, dst)
    assert dst.read_bytes() == b"raw-bytes-ok"


async def test_copy_creates_independent_object(storage, tmp_path):
    src_key = "contract/copy/src.bin"
    dst_key = "contract/copy/dst.bin"
    await storage.put_bytes(src_key, b"payload-A", "application/octet-stream")

    await storage.copy(src_key, dst_key)
    assert await storage.exists(src_key)
    assert await storage.exists(dst_key)

    out = tmp_path / "copy.bin"
    await storage.download_to_path(dst_key, out)
    assert out.read_bytes() == b"payload-A"


async def test_delete_removes_object(storage, tmp_path):
    key = "contract/delete/file.bin"
    await storage.put_bytes(key, b"x", "application/octet-stream")
    assert await storage.exists(key)

    await storage.delete(key)
    assert await storage.exists(key) is False


async def test_download_missing_raises_object_not_found(storage, tmp_path):
    from app.storage.base import ObjectNotFound

    dst = tmp_path / "nope.bin"
    with pytest.raises(ObjectNotFound):
        await storage.download_to_path("contract/does-not-exist", dst)


async def test_delete_prefix_removes_tree(storage, tmp_path):
    """delete_prefix wipes a directory / key prefix. Contract holds even if
    the prefix has never been written (no-op)."""
    # No-op on empty prefix
    await storage.delete_prefix("contract/never-existed/")

    await storage.put_bytes("contract/tree/a.bin", b"a", "application/octet-stream")
    await storage.put_bytes("contract/tree/sub/b.bin", b"b", "application/octet-stream")
    assert await storage.exists("contract/tree/a.bin")
    assert await storage.exists("contract/tree/sub/b.bin")

    await storage.delete_prefix("contract/tree")
    assert await storage.exists("contract/tree/a.bin") is False
    assert await storage.exists("contract/tree/sub/b.bin") is False


async def test_signed_url_returns_non_empty_string(storage):
    key = "contract/signed/file.bin"
    await storage.put_bytes(key, b"signed-url-test", "application/octet-stream")
    url = await storage.signed_url(key, expires_in_sec=60)
    assert isinstance(url, str) and len(url) > 0
    # Both impls must encode the key — we don't test fetch-through here because
    # LocalStorage returns a proxy path and S3Storage returns an HTTP URL; the
    # contract only promises a non-empty string. End-to-end fetch is covered
    # by the StaticFiles mount in test_async_exports.py.
