# flexlog

Local-only, single-user web app for recording recurring 1v1 sessions with people.

Internal codename for the **1v1 Journal** product spec — see
`docs/1v1_Journal_PRD_Engineering_Ready_v3_File_Based_DB.md`.

This is the **M1 Foundation** milestone: the app starts, validates its data
directory, loads (or bootstraps) `config.json`, and serves a placeholder
dashboard. Domain models and CRUD come in subsequent milestones.

## Requirements

- Python 3.11 or newer
- A directory you control where flexlog can store its database, uploads, and config

## Install

```bash
git clone <this repo> flexlog
cd flexlog
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Configure your data directory

flexlog refuses to start unless `FLEXLOG_DATA_DIR` points at an absolute,
existing, writable directory. The directory is **not** created for you —
this is deliberate so flexlog never writes data into a place you didn't pick.

```bash
mkdir -p ~/flexlog-data
export FLEXLOG_DATA_DIR=~/flexlog-data   # use an absolute path; ~ is fine in shell
```

On first run, flexlog writes a default `config.json` into that directory if
none exists. Edit it freely and restart to apply changes.

## Run

```bash
flexlog
# or equivalently:
python -m flexlog
```

Then open http://127.0.0.1:5050/ in a browser. The bind host is always
loopback. Set `FLEXLOG_PORT=...` to choose a different port.

Set `FLEXLOG_DEBUG=1` to enable Flask debug mode (do not do this when
serving real data).

## Customizing labels

The `app`, `ui_strings`, and `ratings` sections of `config.json` rethread
every user-facing label. The same codebase covers interview logs, coaching
journals, language exchange logs, etc. without code changes. See
`docs/1v1_Journal_PRD_Engineering_Ready_v3_File_Based_DB.md` §6.1 for the
schema and `flexlog/config_loader.py` for the validator.

## Backup / restore

Stop the app, then copy the entire `$FLEXLOG_DATA_DIR` directory. To
restore: place the directory on the new machine, set `FLEXLOG_DATA_DIR`
to its absolute path, and run `flexlog`. Both the SQLite database (M2+)
and uploaded media (M4+) are inside that directory.

## Run the test suite

```bash
pytest
```

The configuration in `pyproject.toml` enforces a global 85% line-coverage
floor. Tests must include enough coverage to cross that threshold or the
suite fails.

## What's next

Subsequent milestones:

- M2: people + tags
- M3: sessions + ratings + notes
- M4: media + Media Library + hash dedup
- M5: avatar cropper + sort + polish

See `docs/superpowers/specs/2026-05-07-flexlog-design.md` §12 for the full
roadmap.
