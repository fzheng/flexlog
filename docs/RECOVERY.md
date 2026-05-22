# flexlog recovery runbook

This document covers four recovery scenarios + the quarterly drill that
keeps you confident the backups will actually work when you need them.

The recovery flow assumes the **self-host on macOS + Railway-bucket-only
backup** deployment described in [`docs/SELF_HOSTING.md`](SELF_HOSTING.md).

---

## Prerequisites — what you must have OFF the Mac

For any recovery scenario, you'll need these items from your password
manager (1Password / Bitwarden / Apple Keychain) — NOT from the Mac you
just lost:

- **Railway bucket credentials**
  - Endpoint URL (e.g. `https://...storage.railway.app`)
  - Bucket name (e.g. `flexlog-home-backup`)
  - Access key ID
  - Secret access key
- **Flexlog admin password** (the one you set up at first run)
- **Tailscale account credentials** (to re-join the tailnet)
- **GitHub repo URL** for your flexlog checkout

Store these in your password manager NOW, before you need them. If they
only exist on the Mac you're recovering, recovery is impossible.

---

## Scenario A: Mac is dead / stolen — restore on a new Mac

**Expected time: 60–90 minutes.** Most of it is `make install` compiling
cryptography + Pillow, and rclone copying media.

### Step 1 — Set up the new Mac (~5 min)

1. Sign in to your Apple ID.
2. **Enable FileVault**: System Settings → Privacy & Security → FileVault → Turn On.
3. Optional: connect a UPS if you have one — protects against the next
   power blip causing another reboot+FileVault-prompt cycle.

### Step 2 — Install Homebrew (~5 min)

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

After Homebrew installs, follow its post-install instructions to add it
to your PATH (on Apple Silicon, this adds `/opt/homebrew/bin` to your shell
profile).

### Step 3 — Install system dependencies (~5 min)

```bash
brew install sqlcipher libheif tailscale rclone git
```

Required because:
- `sqlcipher` → so `sqlcipher3` Python wheel can build / link
- `libheif` → so `pillow-heif` can transcode HEIC images
- `tailscale` → public HTTPS reach to the new Mac
- `rclone` → restore + ongoing backup
- `git` → cloning flexlog

### Step 4 — Clone flexlog + install (~15–30 min)

```bash
mkdir -p ~/Work
cd ~/Work
git clone https://github.com/<your-username>/flexlog
cd flexlog
make install
```

`make install` compiles cryptography + Pillow + pillow-heif from source.
The first install takes the longest; subsequent `make install` calls are
cached.

### Step 5 — Configure rclone (~2 min)

```bash
mkdir -p ~/.config/rclone
chmod 700 ~/.config/rclone
cat > ~/.config/rclone/rclone.conf << 'EOF'
[railway-backup]
type = s3
provider = Other
endpoint = <YOUR-BUCKET-ENDPOINT-FROM-PASSWORD-MANAGER>
access_key_id = <YOUR-ACCESS-KEY>
secret_access_key = <YOUR-SECRET-KEY>
region = auto
EOF
chmod 600 ~/.config/rclone/rclone.conf
```

Replace the three `<YOUR-...>` placeholders with the actual values from
your password manager.

Verify the config works:

```bash
rclone lsf railway-backup:flexlog-home-backup/live/
```

Expected output:

```
.secret_key
config.json
data/
kdf_params.json
uploads/
```

If this errors with `AccessDenied` or `NoSuchBucket`, fix the rclone
config before continuing — every following step depends on it.

### Step 6 — Restore the data dir (~5–30 min)

```bash
DATA_DIR="${HOME}/Library/Application Support/flexlog"
mkdir -p "${DATA_DIR}"
rclone copy railway-backup:flexlog-home-backup/live/ "${DATA_DIR}/" --progress
```

The `--progress` flag shows transfer rate + ETA so you know how long
to wait. For 1 GB of media on a typical home connection, expect ~5 min.
For larger libraries, scale linearly.

Verify the dir looks right:

```bash
ls -la "${DATA_DIR}/"
```

Expected: shows `kdf_params.json`, `.secret_key`, `config.json`, `data/`,
`uploads/`.

```bash
ls "${DATA_DIR}/data/"
```

Expected: shows `encounters.db` (and possibly `encounters.db-wal`,
`encounters.db-shm` — SQLite WAL sidecars).

### Step 7 — Install the launch agents (~1 min)

```bash
cd ~/Work/flexlog
python scripts/install_launch_agents.py
```

The installer prompts for:
- **FLEXLOG_DATA_DIR** — accept the default (the path from Step 6)
- **FLEXLOG_LOG_DIR** — accept the default (`~/Library/Logs/flexlog`)
- **HEALTHCHECK_URL** — paste your healthchecks.io ping URL
- **RCLONE_REMOTE** — `railway-backup:flexlog-home-backup`

After it completes, verify three agents loaded:

```bash
launchctl list | grep flexlog
```

Expected: three lines (`com.flexlog.app`, `com.flexlog.backup`,
`com.flexlog.backup-prune`).

Check the flexlog stderr log to confirm gunicorn booted cleanly:

```bash
tail ~/Library/Logs/flexlog/stderr.log
```

You should see lines like `Starting gunicorn`, `Listening at: http://127.0.0.1:5050`,
`Booting worker`.

### Step 8 — Disable system sleep + auto-updates (~1 min)

```bash
sudo pmset -a sleep 0 disksleep 0
sudo softwareupdate --schedule off
```

Without these, the Mac may sleep (flexlog unreachable) or auto-reboot
overnight (FileVault prompt blocks startup until you're physically present).

### Step 9 — Set up Tailscale + Funnel (~3 min)

```bash
tailscale up
# A browser opens; sign in to your tailnet. Confirm this Mac's hostname.
```

Once joined to the tailnet:

```bash
tailscale serve --bg https=443 http://localhost:5050
```

Verify Funnel is bound:

```bash
tailscale funnel status
```

Should show: `https://<your-mac>.<tailnet>.ts.net (Funnel on)` →
`http://127.0.0.1:5050`.

If the Mac's hostname changed from what your original Mac was named,
your public URL changed too. You can rename via:

```bash
sudo scutil --set HostName <desired-hostname>
sudo scutil --set LocalHostName <desired-hostname>
tailscale up --reset
```

### Step 10 — Verify end-to-end (~2 min)

Open `https://<your-mac>.<tailnet>.ts.net/` in a browser.

You should see the fake-Google landing page. Type your flexlog admin
password into the search box. You should land on `/dashboard`.

Spot checks:
- Dashboard shows the correct people
- Click into one session → it loads
- A photo in that session displays
- A video plays back
- The status bar (bottom-right) shows reasonable disk usage

### Step 11 — Test the backup pipeline (~1 min)

Manually trigger a backup to confirm credentials + script + healthcheck
all work end-to-end:

```bash
launchctl kickstart -k gui/$(id -u)/com.flexlog.backup
sleep 5
tail ~/Library/Logs/flexlog/backup.stderr.log
tail ~/Library/Logs/flexlog/rclone.log
```

Check healthchecks.io — your check should show a recent successful ping
in the dashboard.

### You're done.

Total restoration time: 60–90 minutes. Re-pin this Mac as the always-on
home server. Update your password manager with the new bucket creds if
you rotated them during recovery.

---

## Scenario B: Live data dir corrupted on the live Mac

You accidentally `rm`'d the data dir, or a disk error trashed
`encounters.db`, or some other local-only issue. The Mac is fine; only
the data needs to come back from the most recent backup.

### Step 1 — Stop the live flexlog

```bash
launchctl bootout gui/$(id -u) \
    ~/Library/LaunchAgents/com.flexlog.app.plist
```

### Step 2 — Move the corrupted dir aside (don't delete — forensics)

```bash
DATA_DIR="${HOME}/Library/Application Support/flexlog"
mv "${DATA_DIR}" "${DATA_DIR}.broken.$(date +%s)"
```

### Step 3 — Restore from the latest live backup

```bash
mkdir -p "${DATA_DIR}"
rclone copy railway-backup:flexlog-home-backup/live/ "${DATA_DIR}/" --progress
```

### Step 4 — Restart flexlog

```bash
launchctl bootstrap gui/$(id -u) \
    ~/Library/LaunchAgents/com.flexlog.app.plist
```

### Step 5 — Verify in browser

Open `https://<your-mac>.<tailnet>.ts.net/` and confirm the dashboard
loads + your data is back.

### Step 6 — Delete the broken copy (after a week, if no issues)

First list to confirm what you're about to delete:

```bash
ls -d "${DATA_DIR}".broken.*
```

If the glob matches only the directories you intend to remove:

```bash
rm -rf "${DATA_DIR}".broken.*
```

---

## Scenario C: Roll back to a specific point in time

You deleted a session two hours ago and want it back. The latest live
backup also has the deletion. The version BEFORE the deletion lives in
the `archive/` folder.

### Step 1 — List available archive timestamps

```bash
rclone lsf railway-backup:flexlog-home-backup/archive/
```

Output is a list of timestamped directories like
`2026-05-21T03-15-00Z/`. Timestamps are UTC.

### Step 2 — Pick an archive timestamp from BEFORE the deletion

If you deleted the session at ~14:30 local, find an archive from before
that time (account for UTC offset). Each archive folder contains only
the files that were CHANGED OR DELETED at that sync — so an archive
folder will only have `encounters.db` if it changed in that sync cycle.

```bash
ARCHIVE_TS="2026-05-21T03-15-00Z"
rclone lsf "railway-backup:flexlog-home-backup/archive/${ARCHIVE_TS}/" -R
```

If `data/encounters.db` doesn't appear, the DB didn't change at that
sync — pick an earlier timestamp.

### Step 3 — Stop flexlog

```bash
launchctl bootout gui/$(id -u) \
    ~/Library/LaunchAgents/com.flexlog.app.plist
```

### Step 4 — Save the current DB (in case you need to roll forward later)

```bash
DATA_DIR="${HOME}/Library/Application Support/flexlog"
cp "${DATA_DIR}/data/encounters.db" \
   "${DATA_DIR}/data/encounters.db.before-rollback-$(date +%s)"
```

### Step 5 — Restore just the DB from the archive

```bash
rclone copy \
    "railway-backup:flexlog-home-backup/archive/${ARCHIVE_TS}/data/encounters.db" \
    "${DATA_DIR}/data/"
```

### Step 6 — Restart flexlog

```bash
launchctl bootstrap gui/$(id -u) \
    ~/Library/LaunchAgents/com.flexlog.app.plist
```

### Step 7 — Verify in browser

Open `https://<your-mac>.<tailnet>.ts.net/`, log in, confirm the
deleted session is back.

### Step 8 — Clean up the `.before-rollback-*` file (after a week)

```bash
ls "${DATA_DIR}/data/"encounters.db.before-rollback-*  # verify the glob first
rm "${DATA_DIR}/data/"encounters.db.before-rollback-*
```

(Note: the glob expands OUTSIDE the quoted prefix — quoting the wildcard
itself would pass a literal `*` to `rm` and match nothing.)

---

## Scenario D: Catastrophic loss — fire / flood / theft of the Mac

Identical to **Scenario A**. The backup bucket is the source of truth;
the Mac is replaceable.

If the Railway backup bucket is ALSO destroyed (you got hit by a
coordinated incident), the data is unrecoverable — there is no third
copy by design.

If that's in your threat model, add a second backup target. See
[`docs/SELF_HOSTING.md`](SELF_HOSTING.md#adding-a-second-backup-target).

---

## Quarterly recovery drill

The single most important operational habit. **Untested backups are
not backups.**

Calendar reminder for the 1st of every quarter (Jan / Apr / Jul / Oct).
The drill takes ~10 minutes.

### Option 1: Use the drill script (recommended)

From any machine with the flexlog repo + rclone + Python set up
(your laptop is ideal — NOT the home server):

```bash
cd ~/Work/flexlog
RCLONE_REMOTE=railway-backup:flexlog-home-backup \
    ./scripts/recovery-drill.sh
```

The script:
1. Pulls the latest live backup into a temp dir
2. Starts flexlog on port 5151 (so it doesn't conflict with port 5050
   on the home server)
3. Waits for you to verify in the browser
4. On Enter, tears down the test instance + removes the temp dir

In the browser at `http://127.0.0.1:5151/`:
- Log in with your admin password
- Confirm the dashboard shows your people
- Click into a recent session — does it load?
- Click on a media file — does it play / display?
- Check the status bar — does it show recent activity?

### Option 2: Manual drill (if the script isn't available)

```bash
TEST_DIR=$(mktemp -d)
mkdir -p "${TEST_DIR}/data-dir"
rclone copy railway-backup:flexlog-home-backup/live/ \
    "${TEST_DIR}/data-dir/" --progress

cd ~/Work/flexlog
FLEXLOG_DATA_DIR="${TEST_DIR}/data-dir" \
    FLEXLOG_PORT=5151 \
    make run &
TEST_PID=$!

# In another terminal:
open http://127.0.0.1:5151/

# When done verifying:
kill ${TEST_PID}
rm -rf "${TEST_DIR}"
```

### What the drill catches that nothing else does

| Failure mode | Why daily ops miss it | Drill catches it |
|---|---|---|
| Bucket credentials silently rotated | rclone runs from the same Mac with cached config | Fresh rclone-copy fails |
| Bucket access policies changed | Same — runs are idempotent | Fresh copy attempt errors |
| `--exclude` pattern accidentally excludes critical files | Backup runs "successfully" but is incomplete | Test instance is missing data |
| Schema migration corrupted the snapshot | App keeps running on the live DB | Test instance fails to start |
| Bucket is silently empty (e.g., wrong remote) | Sync to wrong place still exits 0 | Fresh copy returns nothing |

Run the drill quarterly. Set a calendar reminder NOW.
