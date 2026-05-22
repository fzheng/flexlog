# Self-hosting flexlog on macOS

This is the recommended deployment for users with **sensitive content
that cannot be exposed to a cloud operator with runtime access**
(corporate interviews, journalism material, anything where "Railway can
technically read this" is in your threat model). For the cloud-deployment
alternative, see [`DEPLOYMENT.md`](DEPLOYMENT.md).

End state: flexlog runs on your own Mac, reachable from anywhere via
Tailscale Funnel (HTTPS), with encrypted offsite backups going to a
Railway storage bucket every 15 minutes.

For the design rationale and threat-model analysis, see
`docs/superpowers/specs/2026-05-21-self-host-with-railway-backup-design.md`
in your local checkout.

For recovery procedures, see [`RECOVERY.md`](RECOVERY.md).

---

## Architecture at a glance

```
client → Tailscale Funnel (TCP only) → Mac (tailscaled terminates TLS)
                                          → gunicorn 127.0.0.1:5050
                                          → flexlog → encrypted disk
                                                       │
                                       rclone every 15 min
                                                       ↓
                                          Railway bucket (encrypted bytes only)
                                                       ↓
                                                  healthchecks.io ping
```

Three local entities:
1. **flexlog itself** — runs as user-level launchd agent
2. **Tailscale daemon** — provides public HTTPS URL via Funnel
3. **rclone** — runs every 15 min via launchd timer

Everything is per-user (no system daemons, no root). FileVault on the
Mac plus flexlog's own AES-GCM/SQLCipher gives you defense in depth.

---

## Prerequisites (one-time accounts to create)

- **Tailscale account** (free for personal use, up to 100 devices).
  Sign up at https://tailscale.com.
- **Railway account** with a NEW project containing ONLY a Storage
  Bucket (no service, no Volume, no compute). Name the bucket
  something like `flexlog-home-backup`. Generate access credentials
  (key + secret) and save them in your password manager.
- **healthchecks.io account** (free tier). Sign up at
  https://healthchecks.io, create one check named "flexlog backup":
  - Period: 30 minutes
  - Grace period: 24 hours
  - Save the check's unique ping URL — you'll need it during install

---

## Setup steps

### 1. Enable FileVault

System Settings → Privacy & Security → FileVault → Turn On.

Defense in depth: even if a thief extracts the SSD, the file names and
sizes are encrypted (not just contents).

### 2. Install Homebrew + dependencies

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
brew install sqlcipher libheif tailscale rclone git
```

### 3. Clone flexlog + install

```bash
mkdir -p ~/Work
cd ~/Work
git clone https://github.com/<your-username>/flexlog
cd flexlog
make install
```

The `make install` step compiles cryptography + Pillow + pillow-heif
against the libraries from step 2. First run takes ~15–30 min.

### 4. Set up Tailscale

```bash
tailscale up
```

A browser opens. Sign in to your tailnet. The Mac joins as a node with
hostname matching its `LocalHostName` (typically your Mac's name).

If your tailnet doesn't have HTTPS enabled yet:
- Open https://login.tailscale.com/admin/dns
- Enable "HTTPS Certificates" (one-time toggle)
- Returns to your Mac in a moment — provisions ACME

Enable Funnel:
- Open https://login.tailscale.com/admin/acls/file
- Add the Funnel grant (or use the Funnel toggle on the node)

### 5. Configure rclone

```bash
mkdir -p ~/.config/rclone
chmod 700 ~/.config/rclone
cat > ~/.config/rclone/rclone.conf << 'EOF'
[railway-backup]
type = s3
provider = Other
endpoint = <YOUR-BUCKET-ENDPOINT>
access_key_id = <YOUR-ACCESS-KEY>
secret_access_key = <YOUR-SECRET-KEY>
region = auto
EOF
chmod 600 ~/.config/rclone/rclone.conf
```

Verify:

```bash
rclone lsd railway-backup:
```

Expected: shows your bucket (e.g. `flexlog-home-backup`).

### 6. First-run flexlog setup (set the admin password)

Before installing the launch agent, do the one-time first-run setup so
the data dir exists with `kdf_params.json`.

```bash
mkdir -p ~/Library/Application\ Support/flexlog

FLEXLOG_DATA_DIR=~/Library/Application\ Support/flexlog \
    make run &
RUN_PID=$!
sleep 3
```

Open http://127.0.0.1:5050/ in a browser. You'll see the "Set Admin
Password" form. Pick a strong password (12+ chars, mixed case + digits
+ symbols — see Password strength below).

Once set, kill the test instance:

```bash
kill ${RUN_PID}
```

### 7. Install the launch agents

```bash
cd ~/Work/flexlog
python scripts/install_launch_agents.py
```

The installer prompts for:
- **FLEXLOG_DATA_DIR** — accept the default
- **FLEXLOG_LOG_DIR** — accept the default
- **HEALTHCHECK_URL** — paste the URL from your healthchecks.io check
- **RCLONE_REMOTE** — `railway-backup:flexlog-home-backup`

After completion, verify three agents are loaded:

```bash
launchctl list | grep flexlog
```

Expected: three rows. flexlog is now running at http://127.0.0.1:5050.

### 8. Disable sleep + auto-updates

```bash
sudo pmset -a sleep 0 disksleep 0
sudo softwareupdate --schedule off
```

This keeps flexlog reachable + avoids unattended reboots that strand at
the FileVault prompt.

### 9. Bind Tailscale Funnel to flexlog

```bash
tailscale serve --bg https=443 http://localhost:5050
```

Verify:

```bash
tailscale funnel status
```

Should show: `https://<mac>.<tailnet>.ts.net (Funnel on)` → `http://127.0.0.1:5050`.

### 10. Verify end-to-end

Open `https://<mac>.<tailnet>.ts.net/` in any browser (your phone works
too — try it from cell data to confirm Funnel is reaching the Mac via
the public path, not via your local network).

Log in with your admin password. You should land on the dashboard.

### 11. Trigger the first backup

```bash
launchctl kickstart -k gui/$(id -u)/com.flexlog.backup
sleep 5
tail ~/Library/Logs/flexlog/backup.stderr.log
```

Check healthchecks.io — your check should show a recent successful
ping. You're now backed up.

---

## Password strength

With no rate limiting (single-user app; Argon2id KDF cost is the only
brake), the password is the load-bearing security control. Choose:
- **XKCD-style passphrase** (4 random common words): `correct horse
  battery staple` — easy to remember, infeasible to brute-force
- **16+ random characters from a password manager**: best option if
  you'll be copy-pasting anyway

What to avoid:
- Common passwords (`password123`, `qwerty1234`, anything in a leaked
  credentials list)
- Reused passwords from other services
- Short passwords (<12 chars), even if "random-looking"

---

## Operational procedures

### Updating flexlog

```bash
cd ~/Work/flexlog
git pull
make install                                    # rebuild venv if deps changed
launchctl kickstart -k gui/$(id -u)/com.flexlog.app
tail ~/Library/Logs/flexlog/stderr.log
```

### Rotating the Railway bucket credentials

1. In Railway, generate a new set of credentials for the bucket.
2. Save them to your password manager.
3. Edit `~/.config/rclone/rclone.conf` with the new key + secret.
4. Run `~/Work/flexlog/scripts/backup-to-railway.sh` manually to verify.
5. Revoke the old credentials in Railway.

### Changing the flexlog admin password

Use the in-app form at `/settings/security`. Change is constant-time;
re-wraps the master key. No backup change needed — `kdf_params.json`
updates on disk and the next rclone run propagates it.

### Manual backup trigger

```bash
launchctl kickstart -k gui/$(id -u)/com.flexlog.backup
```

Or:

```bash
make self-host-backup
```

### Uninstalling

```bash
python scripts/uninstall_launch_agents.py
```

Removes the three launch agents. Does NOT touch the data dir, log
dir, or rclone state.

To fully tear down:

```bash
rm -rf ~/Library/Application\ Support/flexlog        # data dir
rm -rf ~/Library/Logs/flexlog                         # logs
rm ~/.config/rclone/rclone.conf                       # rclone config
tailscale serve --bg --remove https=443               # unbind Funnel
```

### Adding a second backup target

Defense against single-cloud incident (Railway has an outage that
deletes their storage, you get account-banned, etc.).

1. Sign up for a second cloud (Backblaze B2 is cheap; Cloudflare R2 is
   convenient).
2. Create a bucket, generate keys, add a `[b2-backup]` section to
   `~/.config/rclone/rclone.conf`.
3. Edit `scripts/backup-to-railway.sh` to add a second `rclone sync`
   call targeting the new remote.
4. Add a second prune call in `scripts/prune-old-backups.sh`.

Cost: ~$0.02/GB-month for both clouds combined. Encrypted-bytes
property preserved at both targets.

---

## What you're trusting + what you're not

You're trusting:
- **Your password** to be strong enough to resist Argon2id brute-force
- **Your Mac's physical security** when it's powered on and unlocked
  (auto-lock + strong login password matters)
- **Apple** to ship a non-malicious macOS update
- **Tailscale** to route TCP without TLS-MITM (they don't have the cert)
- **Cloudflare** (Tailscale uses them for the `*.ts.net` cert via Let's
  Encrypt — fine; standard CA trust)

You're NOT trusting:
- **Railway** with anything but encrypted bytes (no runtime, no key)
- **Your ISP** with anything but encrypted TCP
- **Anyone on your local LAN** to reach flexlog (gunicorn binds 127.0.0.1)

---

## Cost summary

- Hardware: $0 (you already own the Mac)
- Power: $2–10/month depending on Mac model
- Railway bucket storage: $0.03–0.10/month for typical journal size
- Tailscale: $0 (personal tier)
- healthchecks.io: $0 (personal tier)
- **Total: $2–10/month** vs. $5–10/month for the Railway-runtime deploy,
  with strictly better threat properties.
