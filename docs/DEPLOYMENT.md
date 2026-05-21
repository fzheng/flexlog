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

> **Note on env-var names.** Railway's bucket-link templates use the
> AWS-style names by default (`AWS_S3_BUCKET_NAME`, `AWS_ENDPOINT_URL`,
> `AWS_DEFAULT_REGION`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`).
> The app accepts those, plus a few other historical aliases
> (`BUCKET` / `BUCKET_NAME` / `S3_BUCKET`, `ENDPOINT` / `S3_ENDPOINT` /
> `ENDPOINT_URL`, `REGION` / `AWS_REGION`, etc.). For the replica,
> prefix the same name with `BACKUP_` (e.g. `BACKUP_AWS_S3_BUCKET_NAME`,
> `BACKUP_AWS_SECRET_ACCESS_KEY` — note **all five** are required;
> a partially-configured replica fails at boot with a clear log message
> listing the missing var).

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

## Large file uploads (audio / video)

Single-request POST uploads over Railway are bounded by **three**
independent limits stacked on top of each other:

1. **Your home upload speed.** A 2.7 GB POST at 10 Mbps takes ~36
   min; at 100 Mbps fiber, ~3.5 min. Most cable connections are
   nowhere near 100 Mbps up.
2. **Railway's edge proxy timeout.** Around 5 minutes per HTTP
   request. After that, the edge returns 502 regardless of what
   your gunicorn worker is doing.
3. **Gunicorn `--timeout`.** Now set to 30 min in our Dockerfile,
   so the worker itself won't time out under #2.

**Practical guidance:**

- **< 100 MB:** uploads reliably on most connections.
- **100–500 MB:** works on fast home upload; slow connections will
  hit Railway's edge timeout.
- **\> 500 MB:** unreliable on Railway via the single-POST upload
  path. The right answer depends on what you're storing:
  - Short voice memos / 1080p clips of an interview → keep in flexlog,
    accept occasional retries.
  - Multi-GB raw recordings → store externally (YouTube unlisted,
    Vimeo private, S3 direct) and paste a link instead. The link's
    thumbnail (a screenshot you paste) IS supported and doesn't
    have the size problem.

flexlog accepts up to 3 GB in Flask's `MAX_CONTENT_LENGTH` config —
it's not the gatekeeper here, the edge is.

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
