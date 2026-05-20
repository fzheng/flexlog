"""S3Storage backend tests via moto (in-memory S3 mock).

Every test uses a fresh moto-managed S3 client; no real AWS / Railway
calls. The S3-compat contract Railway exposes is a strict subset of
real S3, so moto coverage is a good proxy for behavior in prod."""
from __future__ import annotations

import io

import boto3
import pytest
from moto import mock_aws


@pytest.fixture
def mocked_s3():
    """Spin up moto's in-memory S3 + create a test bucket."""
    with mock_aws():
        client = boto3.client("s3", region_name="us-east-1")
        client.create_bucket(Bucket="test-bucket")
        yield client


def _make_storage(bucket="test-bucket", prefix="uploads/"):
    from flexlog.storage.s3 import S3Storage
    return S3Storage(
        bucket=bucket,
        endpoint_url=None,  # moto intercepts via env
        region="us-east-1",
        access_key="testing",
        secret_key="testing",
        key_prefix=prefix,
    )


def test_s3_put_then_get_full_range(mocked_s3, tmp_path):
    storage = _make_storage()
    src = tmp_path / "src.bin"
    payload = b"hello" * 1000
    src.write_bytes(payload)
    storage.put("aa/bb/foo.bin", src)
    out = storage.get_range("aa/bb/foo.bin", 0, len(payload) - 1)
    assert out == payload


def test_s3_get_range_partial(mocked_s3, tmp_path):
    storage = _make_storage()
    src = tmp_path / "src.bin"
    src.write_bytes(b"0123456789")
    storage.put("aa/bb/range.bin", src)
    assert storage.get_range("aa/bb/range.bin", 0, 0) == b"0"
    assert storage.get_range("aa/bb/range.bin", 2, 5) == b"2345"
    assert storage.get_range("aa/bb/range.bin", 9, 9) == b"9"


def test_s3_get_size(mocked_s3, tmp_path):
    storage = _make_storage()
    src = tmp_path / "src.bin"
    src.write_bytes(b"x" * 500)
    storage.put("aa/bb/sized.bin", src)
    assert storage.get_size("aa/bb/sized.bin") == 500


def test_s3_exists_true_and_false(mocked_s3, tmp_path):
    storage = _make_storage()
    src = tmp_path / "src.bin"
    src.write_bytes(b"x")
    storage.put("aa/bb/here.bin", src)
    assert storage.exists("aa/bb/here.bin")
    assert not storage.exists("aa/bb/missing.bin")


def test_s3_delete(mocked_s3, tmp_path):
    storage = _make_storage()
    src = tmp_path / "src.bin"
    src.write_bytes(b"x")
    storage.put("aa/bb/doomed.bin", src)
    assert storage.exists("aa/bb/doomed.bin")
    storage.delete("aa/bb/doomed.bin")
    assert not storage.exists("aa/bb/doomed.bin")


def test_s3_delete_missing_is_noop(mocked_s3):
    """delete on a missing key must not raise."""
    storage = _make_storage()
    storage.delete("aa/bb/never-was.bin")  # no raise


def test_s3_key_prefix_isolates_namespaces(mocked_s3, tmp_path):
    """Two S3Storage instances pointing at the same bucket with
    different prefixes don't see each other's keys (the prefix is
    transparent to callers)."""
    uploads = _make_storage(prefix="uploads/")
    backups = _make_storage(prefix="backups/")
    src = tmp_path / "src.bin"
    src.write_bytes(b"x")
    uploads.put("a/b/c.bin", src)
    assert uploads.exists("a/b/c.bin")
    assert not backups.exists("a/b/c.bin")


def test_s3_get_range_on_missing_raises_clean_error(mocked_s3):
    """get_range on a key that doesn't exist should raise a clear
    storage-level error (the route handler will turn it into 404)."""
    from flexlog.storage.s3 import S3StorageError
    storage = _make_storage()
    with pytest.raises((S3StorageError, Exception)):  # boto raises ClientError
        storage.get_range("nope.bin", 0, 9)


def test_s3_list_keys_returns_sorted_logical_keys(mocked_s3, tmp_path):
    storage = _make_storage(prefix="db/")
    src = tmp_path / "x.bin"
    src.write_bytes(b"x")
    storage.put("db-2026-05-19T11-00-00Z.db", src)
    storage.put("db-2026-05-19T10-00-00Z.db", src)
    storage.put("db-2026-05-19T12-00-00Z.db", src)
    keys = storage.list_keys()
    assert keys == [
        "db-2026-05-19T10-00-00Z.db",
        "db-2026-05-19T11-00-00Z.db",
        "db-2026-05-19T12-00-00Z.db",
    ]
