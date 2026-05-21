# Deploying flexlog to Railway

This guide walks through deploying flexlog as a single-user cloud
journal on Railway. End state: HTTPS URL you can hit from any
browser, encrypted DB + media on a Railway Volume + two S3 buckets
for redundancy, ~$5/month total.

## Prerequisites

- [Railway account](https://railway.com) with at least the Hobby plan ($5/mo).
- This repo cloned + pushed to a GitHub repo Railway can read.

## One-time setup

### 1. Create the Railway project

In the Railway dashboard:

1. New Project → Deploy from GitHub repo → select your fork of flexlog.
2. Railway detects the Dockerfile and builds. First build takes ~5-10
   minutes (cryptography + Pillow compile against libheif/libsqlcipher).

### 2. Create the Volume

In the project canvas:

1. Right-click → New → Volume.
2. Attach to the flexlog service.
3. Mount path: `/app/data`.
4. Size: 5 GB (Hobby default; trivially enough).
5. Click the service → Restart to pick up the mount.

### 3. Create the two Storage Buckets

In the project canvas:

1. Right-click → New → Storage Bucket. Name: `flexlog-media`.
   Region: pick one close to you.
2. Link to the flexlog service. Leave the env var prefix blank (the
   default `BUCKET`, `ENDPOINT`, etc. names).
3. Right-click → New → Storage Bucket. Name: `flexlog-backups`.
   Same region.
4. Link to the flexlog service. **Change the env var prefix to
   `BACKUP_`** so the names become `BACKUP_BUCKET`, `BACKUP_ENDPOINT`,
   `BACKUP_REGION`, `BACKUP_ACCESS_KEY_ID`, `BACKUP_SECRET_ACCESS_KEY`.

> **Note on env-var names.** Railway's bucket linking has used several
> naming schemes over time. The app accepts any of these for the
> primary bucket: `BUCKET` / `BUCKET_NAME` / `S3_BUCKET`, plus the
> matching `ACCESS_KEY_ID` / `AWS_ACCESS_KEY_ID`,
> `SECRET_ACCESS_KEY` / `AWS_SECRET_ACCESS_KEY`,
> `ENDPOINT` / `S3_ENDPOINT` / `ENDPOINT_URL`,
> `REGION` / `AWS_DEFAULT_REGION` / `AWS_REGION`. Same names with a
> `BACKUP_` prefix for the replica. If Railway's auto-injected name
> for your bucket is something else entirely, the app's first media
> upload will fail with a clear error in the logs listing what was
> tried — rename one of the env vars in the Variables tab to match.

### 4. Set the app-controlled env vars

On the flexlog service → Variables:

| Variable | Value |
|----------|-------|
| `FLEXLOG_DATA_DIR` | `/app/data` |
| `FLEXLOG_STORAGE_BACKEND` | `s3` |
| `FLEXLOG_BEHIND_TLS` | `1` |
| `FLEXLOG_RATE_LIMIT` | `1` |

Railway auto-injects `PORT`. The bucket credentials are already
present from the linking in step 3.

### 5. Generate a public domain

Service → Settings → Networking → Generate Domain. You get a
`your-project.up.railway.app` URL. HTTPS is automatic (Let's Encrypt,
auto-renewed).

### 6. First-run setup

Visit the URL. flexlog detects no `kdf_params.json` on the Volume and
shows the **Set Admin Password** form. Pick a strong password (≥8
chars; longer is better — Argon2id makes each guess take ~500ms server-
side, so 12+ chars of mixed case/digits/symbols is effectively
brute-force-proof against the 5/hour rate limit).

After setup, every subsequent visit shows the fake-Google landing.
Type your password into the search box to log in.

## Verifying the deployment

Once authed:

- Check the status bar (bottom-right corner). You should see
  `<size> used • No sessions yet • Backup: Xs ago` — the Backup chip
  proves the worker is running and uploading to flexlog-backups.
- Create a person + a session + upload a photo. The photo upload takes
  slightly longer than local (sync replication to both buckets).
- In the Railway dashboard, check both buckets. `flexlog-media` should
  contain `uploads/<aa>/<bb>/<sha>.jpg`. `flexlog-backups` should
  contain `media/<aa>/<bb>/<sha>.jpg` AND `db/db-<iso>.db`.

## Backup retention

DB backups rotate automatically — last 30 are kept. Media files are
permanent (deletes via Library → hard-delete remove from both buckets).

## Disaster recovery

**Lost the Volume DB:** Restart the container. Cold-boot logic
detects the missing DB and downloads the newest backup from
`flexlog-backups/db/`. Brief unavailability while download completes.

**Lost the `flexlog-media` bucket:**

1. Create a new bucket of the same name in the Railway UI.
2. Link to the service (same env var names; the new credentials
   override the old).
3. From your local machine with both bucket credentials in env:

   ```bash
   python scripts/restore_media_from_backup.py
   ```
4. Redeploy the Railway service. Media reads now hit the new primary
   bucket; replication continues against the existing backup bucket.

**Lost everything (account compromise / total account loss):**
The encrypted backup files in `flexlog-backups` are useless without
your password. If you've also lost the password, the data is
unrecoverable by design (flexlog has no password recovery; the master
key is wrapped under a KEK derived from the password).

For ultimate DR, periodically download `flexlog-backups` to a local
disk or another cloud (the backup files are AES-GCM-encrypted; safe
to store anywhere).

## Cost expectations

Hobby plan ($5/mo) typically covers:
- The flexlog service compute (~512 MB RAM idle)
- 5 GB Volume
- ~5 GB outbound bandwidth
- Bucket storage scales linearly: $0.015/GB-month per bucket

For a single-user journal: expect $5-6/month total in the first year.
A long-running install (5 years, ~25 GB media mirrored = 50 GB across
both buckets) adds ~$0.75/month.

## Updating the deployment

Push to your GitHub repo. Railway auto-builds + deploys on every push
to the default branch (configurable in service → Settings).
