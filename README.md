# flexlog

Local-only, single-user web app for recording recurring 1v1 sessions with people.

Internal codename for the **1v1 Journal** product spec — see
`docs/1v1_Journal_PRD_Engineering_Ready_v3_File_Based_DB.md`.

Latest milestone shipped: **M2 — People + Tags** (see `## What's next`
for the roadmap).

## Requirements

- Python 3.11 or newer
- `make`, `curl` (for the smoke target)
- A directory you control where flexlog can store its database, uploads, and config

## Quick start with make

```bash
git clone <this repo> flexlog
cd flexlog
make install        # creates .venv and installs flexlog with dev extras
make run            # starts the app at http://127.0.0.1:5050/
                    # default data dir: ./flexlog-data
make test           # runs the test suite with the 85% coverage gate
make smoke          # end-to-end startup + dashboard check against a tmp dir
make help           # list all targets
```

Override variables on the command line:

```bash
make run DATA_DIR=/abs/path/of/your/choice PORT=5151
make install PYTHON=python3.11
```

## Configure your data directory

flexlog refuses to start unless `FLEXLOG_DATA_DIR` points at an absolute,
existing, writable directory. `make run` creates `./flexlog-data` for you
and sets the variable for you. To point at somewhere else:

```bash
mkdir -p ~/flexlog-data
make run DATA_DIR=$HOME/flexlog-data
```

On first run, flexlog writes a default `config.json` into that directory if
none exists. Edit it freely and restart to apply changes.

`FLEXLOG_DEBUG=1` enables Flask debug mode (do not do this when serving
real data).

## Manual install + run (without make)

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
export FLEXLOG_DATA_DIR=$HOME/flexlog-data && mkdir -p "$FLEXLOG_DATA_DIR"
flexlog                 # or: python -m flexlog
```

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

## Features (M2)

- Add, edit, delete people (delete requires typing the alias)
- Global tags shared across all people
- Dashboard with search by alias or tag
- Default avatar placeholder (real avatar upload comes in M5)

## Run the test suite

```bash
make test            # gate-enforced
make test-cov        # same, plus a term-missing report
```

(Or, with the venv activated: `pytest`.) The configuration in
`pyproject.toml` enforces a global 85% line-coverage floor. Tests must
cross that threshold or the suite fails.

## What's next

Subsequent milestones:

- **M2 (✓ shipped):** people + tags + dashboard
- M3: sessions + ratings + notes
- M4: media + Media Library + hash dedup
- M5: avatar cropper + sort + polish

See `docs/superpowers/specs/2026-05-07-flexlog-design.md` §12 for the full
roadmap.
