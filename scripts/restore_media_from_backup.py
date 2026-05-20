#!/usr/bin/env python3
"""Disaster recovery: rebuild flexlog-media from flexlog-backups.

Use when the primary media bucket has been destroyed (account error,
manual delete past Railway's 2-day soft-delete window). Lists every
object under `media/` in the backup bucket and copies it to
`uploads/` in the (new) primary bucket.

Usage (run from your local machine with both sets of credentials):

    export BUCKET=<new-primary-bucket>
    export ENDPOINT=https://storage.railway.app
    export REGION=auto
    export ACCESS_KEY_ID=...
    export SECRET_ACCESS_KEY=...
    export BACKUP_BUCKET=<existing-backup-bucket>
    export BACKUP_ENDPOINT=https://storage.railway.app
    export BACKUP_REGION=auto
    export BACKUP_ACCESS_KEY_ID=...
    export BACKUP_SECRET_ACCESS_KEY=...
    python scripts/restore_media_from_backup.py

The script is idempotent: re-running copies only missing keys."""
from __future__ import annotations

import os
import sys

import boto3
from botocore.config import Config as BotoConfig


def make_client(endpoint, region, access, secret):
    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        region_name=region,
        aws_access_key_id=access,
        aws_secret_access_key=secret,
        config=BotoConfig(signature_version="s3v4"),
    )


def main():
    required = (
        "BUCKET", "ENDPOINT", "REGION", "ACCESS_KEY_ID", "SECRET_ACCESS_KEY",
        "BACKUP_BUCKET", "BACKUP_ENDPOINT", "BACKUP_REGION",
        "BACKUP_ACCESS_KEY_ID", "BACKUP_SECRET_ACCESS_KEY",
    )
    missing = [v for v in required if v not in os.environ]
    if missing:
        print(f"missing env vars: {missing}", file=sys.stderr)
        return 1

    primary = make_client(
        os.environ["ENDPOINT"], os.environ["REGION"],
        os.environ["ACCESS_KEY_ID"], os.environ["SECRET_ACCESS_KEY"],
    )
    backup = make_client(
        os.environ["BACKUP_ENDPOINT"], os.environ["BACKUP_REGION"],
        os.environ["BACKUP_ACCESS_KEY_ID"],
        os.environ["BACKUP_SECRET_ACCESS_KEY"],
    )
    primary_bucket = os.environ["BUCKET"]
    backup_bucket = os.environ["BACKUP_BUCKET"]

    copied = 0
    skipped = 0
    paginator = backup.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=backup_bucket, Prefix="media/"):
        for obj in page.get("Contents", []) or []:
            backup_key = obj["Key"]
            # media/<file_key> in backup → uploads/<file_key> in primary
            relative = backup_key[len("media/"):]
            primary_key = f"uploads/{relative}"
            # Skip if primary already has it
            try:
                primary.head_object(Bucket=primary_bucket, Key=primary_key)
                skipped += 1
                continue
            except Exception:
                pass
            data = backup.get_object(
                Bucket=backup_bucket, Key=backup_key,
            )["Body"].read()
            primary.put_object(
                Bucket=primary_bucket, Key=primary_key, Body=data,
            )
            copied += 1
            if copied % 100 == 0:
                print(f"  copied {copied}, skipped {skipped}")

    print(f"done: copied {copied}, skipped {skipped} (already in primary)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
