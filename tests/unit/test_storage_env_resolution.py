"""S3 env-var alias resolution.

Railway auto-injects bucket credentials under names that vary across
plans/regions. The factory in flexlog.storage accepts any of the
well-known aliases so a deployer doesn't have to rename Railway's
output."""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _clear_bucket_env(monkeypatch):
    """Strip every bucket-shaped env var so each test starts clean
    and only sets the names it cares about."""
    import os
    for k in list(os.environ):
        if any(tok in k for tok in ("BUCKET", "ENDPOINT", "REGION",
                                    "ACCESS_KEY", "SECRET")):
            monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("FLEXLOG_STORAGE_BACKEND", "s3")


def _set_primary(monkeypatch, bucket_var, key_var, secret_var):
    monkeypatch.setenv(bucket_var, "my-bucket")
    monkeypatch.setenv(key_var, "AKIA")
    monkeypatch.setenv(secret_var, "secret")


def test_resolves_bucket_under_canonical_BUCKET(monkeypatch):
    _set_primary(monkeypatch, "BUCKET", "ACCESS_KEY_ID", "SECRET_ACCESS_KEY")
    from flexlog.storage import get_storage
    storage = get_storage()
    from flexlog.storage.s3 import S3Storage
    assert isinstance(storage, S3Storage)


def test_resolves_bucket_under_BUCKET_NAME_alias(monkeypatch):
    """Railway's newer storage-bucket integration uses BUCKET_NAME."""
    _set_primary(monkeypatch, "BUCKET_NAME", "ACCESS_KEY_ID", "SECRET_ACCESS_KEY")
    from flexlog.storage import get_storage
    storage = get_storage()
    from flexlog.storage.s3 import S3Storage
    assert isinstance(storage, S3Storage)


def test_resolves_full_railway_aws_naming_set(monkeypatch):
    """Real-world Railway env-var set (May 2026): all 5 bucket vars
    use the AWS_-prefixed names. This is the exact shape that broke
    in production."""
    monkeypatch.setenv("AWS_S3_BUCKET_NAME", "my-bucket")
    monkeypatch.setenv("AWS_ENDPOINT_URL", "https://storage.railway.app")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "AKIA")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "secret")
    from flexlog.storage import get_storage
    from flexlog.storage.s3 import S3Storage
    assert isinstance(get_storage(), S3Storage)


def test_resolves_credentials_under_AWS_aliases(monkeypatch):
    """AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY are also accepted."""
    _set_primary(monkeypatch, "BUCKET", "AWS_ACCESS_KEY_ID",
                 "AWS_SECRET_ACCESS_KEY")
    from flexlog.storage import get_storage
    storage = get_storage()
    from flexlog.storage.s3 import S3Storage
    assert isinstance(storage, S3Storage)


def test_missing_bucket_raises_clear_runtime_error(monkeypatch):
    """No bucket env var set → RuntimeError listing the names tried
    and which bucket-shaped vars ARE present."""
    monkeypatch.setenv("ACCESS_KEY_ID", "AKIA")
    monkeypatch.setenv("SECRET_ACCESS_KEY", "secret")
    monkeypatch.setenv("FOO_REGION", "us-east-1")  # red herring
    from flexlog.storage import get_storage
    with pytest.raises(RuntimeError) as exc:
        get_storage()
    msg = str(exc.value)
    # Names that were tried
    assert "BUCKET" in msg
    assert "BUCKET_NAME" in msg
    # Bucket-shaped vars currently set show up in the diagnostic
    assert "ACCESS_KEY_ID" in msg
    assert "SECRET_ACCESS_KEY" in msg
    assert "FOO_REGION" in msg


def test_missing_access_key_raises_clear_runtime_error(monkeypatch):
    monkeypatch.setenv("BUCKET", "my-bucket")
    monkeypatch.setenv("SECRET_ACCESS_KEY", "secret")
    from flexlog.storage import get_storage
    with pytest.raises(RuntimeError) as exc:
        get_storage()
    assert "ACCESS_KEY_ID" in str(exc.value)


def test_backup_bucket_via_BACKUP_BUCKET_NAME_alias(monkeypatch):
    """The BACKUP_ replica also accepts BACKUP_BUCKET_NAME etc."""
    _set_primary(monkeypatch, "BUCKET", "ACCESS_KEY_ID", "SECRET_ACCESS_KEY")
    monkeypatch.setenv("BACKUP_BUCKET_NAME", "my-backup")
    monkeypatch.setenv("BACKUP_ACCESS_KEY_ID", "AKIA2")
    monkeypatch.setenv("BACKUP_SECRET_ACCESS_KEY", "secret2")
    from flexlog.storage import get_storage
    from flexlog.storage.mirrored import MirroredStorage
    storage = get_storage()
    assert isinstance(storage, MirroredStorage)
