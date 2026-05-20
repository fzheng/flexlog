"""S3Storage — boto3-backed StorageBackend for S3-compatible object
stores (AWS S3, Railway Storage Buckets, MinIO, etc.).

`key_prefix` lets the same class point at `uploads/` in one bucket
and `media/` in another (the backup bucket uses `media/` to keep
DB snapshots in a sibling `db/` prefix).

All S3 calls use signature v4 (Railway's docs require it). Path-style
URLs are NOT used — Railway defaults to virtual-hosted-style; boto3
handles this when endpoint_url is set with a hostname like
storage.railway.app."""
from __future__ import annotations

from pathlib import Path

import boto3
from botocore.config import Config as BotoConfig
from botocore.exceptions import ClientError


class S3StorageError(RuntimeError):
    """Raised when an S3 operation fails for any reason other than
    'object not found' (which exists() / delete() handle silently)."""


class S3Storage:
    def __init__(
        self,
        bucket: str,
        endpoint_url: str | None,
        region: str,
        access_key: str,
        secret_key: str,
        key_prefix: str = "",
    ):
        if key_prefix and not key_prefix.endswith("/"):
            key_prefix = key_prefix + "/"
        self._bucket = bucket
        self._prefix = key_prefix
        self._client = boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            region_name=region,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            config=BotoConfig(
                signature_version="s3v4",
                retries={"max_attempts": 3, "mode": "standard"},
            ),
        )

    def _full_key(self, file_key: str) -> str:
        return f"{self._prefix}{file_key}"

    def put(self, file_key: str, src_path: Path) -> None:
        with Path(src_path).open("rb") as f:
            try:
                self._client.put_object(
                    Bucket=self._bucket,
                    Key=self._full_key(file_key),
                    Body=f,
                )
            except ClientError as e:
                raise S3StorageError(
                    f"put {self._full_key(file_key)!r} failed: {e}"
                ) from e

    def get_range(self, file_key: str, start: int, end: int) -> bytes:
        try:
            resp = self._client.get_object(
                Bucket=self._bucket,
                Key=self._full_key(file_key),
                Range=f"bytes={start}-{end}",
            )
        except ClientError as e:
            raise S3StorageError(
                f"get_range {self._full_key(file_key)!r} failed: {e}"
            ) from e
        return resp["Body"].read()

    def get_size(self, file_key: str) -> int:
        try:
            resp = self._client.head_object(
                Bucket=self._bucket,
                Key=self._full_key(file_key),
            )
        except ClientError as e:
            raise S3StorageError(
                f"head {self._full_key(file_key)!r} failed: {e}"
            ) from e
        return int(resp["ContentLength"])

    def exists(self, file_key: str) -> bool:
        try:
            self._client.head_object(
                Bucket=self._bucket,
                Key=self._full_key(file_key),
            )
            return True
        except ClientError as e:
            if e.response["Error"]["Code"] in ("404", "NoSuchKey", "NotFound"):
                return False
            raise S3StorageError(
                f"head {self._full_key(file_key)!r} failed: {e}"
            ) from e

    def delete(self, file_key: str) -> None:
        # S3 delete_object returns success even for missing keys.
        try:
            self._client.delete_object(
                Bucket=self._bucket,
                Key=self._full_key(file_key),
            )
        except ClientError as e:
            # Re-raise only if it's a permission/credential failure;
            # silent on 404-like to match LocalStorage's contract.
            if e.response["Error"]["Code"] not in ("404", "NoSuchKey", "NotFound"):
                raise S3StorageError(
                    f"delete {self._full_key(file_key)!r} failed: {e}"
                ) from e
