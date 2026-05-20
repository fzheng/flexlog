"""On cold boot with empty Volume but populated backup bucket, the
latest backup is downloaded to the Volume before the app starts
serving."""
from __future__ import annotations

from pathlib import Path

import boto3
import pytest
from moto import mock_aws


def test_cold_boot_downloads_latest_backup_when_db_missing(tmp_path, monkeypatch):
    """No DB on Volume + 3 backups in S3 → newest backup downloaded
    to the Volume DB path."""
    with mock_aws():
        client = boto3.client("s3", region_name="us-east-1")
        client.create_bucket(Bucket="test-bucket")

        # Plant 3 backups (newest last lexicographically)
        client.put_object(
            Bucket="test-bucket",
            Key="media/db/db-2026-05-19T10-00-00Z.db",
            Body=b"oldest",
        )
        client.put_object(
            Bucket="test-bucket",
            Key="media/db/db-2026-05-19T12-00-00Z.db",
            Body=b"newest",
        )
        client.put_object(
            Bucket="test-bucket",
            Key="media/db/db-2026-05-19T11-00-00Z.db",
            Body=b"middle",
        )

        from flexlog.storage.s3 import S3Storage
        storage = S3Storage(
            bucket="test-bucket",
            endpoint_url=None,
            region="us-east-1",
            access_key="testing",
            secret_key="testing",
            key_prefix="media/",
        )

        db_path = tmp_path / "encounters.db"
        assert not db_path.exists()

        from flexlog.services.db_backup import restore_latest_if_missing
        restored = restore_latest_if_missing(storage, db_path)
        assert restored is True
        assert db_path.exists()
        assert db_path.read_bytes() == b"newest"


def test_cold_boot_is_noop_when_db_exists(tmp_path):
    """If the Volume already has a DB, don't overwrite it."""
    with mock_aws():
        client = boto3.client("s3", region_name="us-east-1")
        client.create_bucket(Bucket="test-bucket")
        client.put_object(
            Bucket="test-bucket",
            Key="media/db/db-2026-05-19T12-00-00Z.db",
            Body=b"newest",
        )

        from flexlog.storage.s3 import S3Storage
        storage = S3Storage(
            bucket="test-bucket", endpoint_url=None, region="us-east-1",
            access_key="t", secret_key="t", key_prefix="media/",
        )
        db_path = tmp_path / "encounters.db"
        db_path.write_bytes(b"existing")

        from flexlog.services.db_backup import restore_latest_if_missing
        restored = restore_latest_if_missing(storage, db_path)
        assert restored is False
        assert db_path.read_bytes() == b"existing"


def test_cold_boot_is_noop_when_no_backups(tmp_path):
    """No DB AND no backups → fresh install path; return False."""
    with mock_aws():
        client = boto3.client("s3", region_name="us-east-1")
        client.create_bucket(Bucket="test-bucket")

        from flexlog.storage.s3 import S3Storage
        storage = S3Storage(
            bucket="test-bucket", endpoint_url=None, region="us-east-1",
            access_key="t", secret_key="t", key_prefix="media/",
        )
        db_path = tmp_path / "encounters.db"
        from flexlog.services.db_backup import restore_latest_if_missing
        assert restore_latest_if_missing(storage, db_path) is False
        assert not db_path.exists()
