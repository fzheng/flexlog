PYTHON       ?= python3
VENV         ?= .venv
BIN          := $(VENV)/bin
DATA_DIR     ?= $(CURDIR)/flexlog-data
PORT         ?= 5050
INSTALL_MARK := $(VENV)/.installed

.PHONY: help install lock audit run test test-cov smoke clean

help:
	@echo "flexlog — make targets"
	@echo ""
	@echo "  make install         install flexlog with dev extras into $(VENV)"
	@echo "  make run             run the app at http://127.0.0.1:$(PORT)/"
	@echo "                       (data dir: $(DATA_DIR))"
	@echo "  make test            run the test suite (enforces 85% coverage gate)"
	@echo "  make test-cov  test + term-missing coverage report"
	@echo "  make smoke     end-to-end smoke test against a tmp data dir"
	@echo "  make clean     remove caches, build artifacts, and the venv"
	@echo ""
	@echo "Override variables on the command line, e.g.:"
	@echo "  make run DATA_DIR=/abs/path PORT=5151"
	@echo "  make install PYTHON=python3.11"

$(VENV):
	$(PYTHON) -m venv $(VENV)

$(INSTALL_MARK): pyproject.toml requirements.lock | $(VENV)
	$(BIN)/pip install --upgrade pip
	$(BIN)/pip install --require-hashes -r requirements.lock
	$(BIN)/pip install -e . --no-deps
	@if command -v sha256sum >/dev/null 2>&1; then \
	    cd flexlog/static/vendor && sha256sum -c INTEGRITY.txt; \
	elif command -v shasum >/dev/null 2>&1; then \
	    cd flexlog/static/vendor && shasum -a 256 -c INTEGRITY.txt; \
	else \
	    echo "WARNING: neither sha256sum nor shasum found; vendor integrity NOT verified"; \
	fi
	@touch $@

install: $(INSTALL_MARK)

lock: | $(VENV)
	$(BIN)/pip install --upgrade "pip-tools>=7.4,<8"
	$(BIN)/pip-compile \
	    --generate-hashes \
	    --extra dev \
	    --output-file requirements.lock \
	    pyproject.toml
	@echo ""
	@echo "Lockfile regenerated. Review the diff and commit alongside pyproject.toml."

audit: install
	$(BIN)/pip-audit --strict --requirement requirements.lock

run: install
	@mkdir -p $(DATA_DIR)
	FLEXLOG_DATA_DIR=$(DATA_DIR) FLEXLOG_PORT=$(PORT) $(BIN)/flexlog

test: install
	$(BIN)/pytest

test-cov: install
	$(BIN)/pytest --cov-report=term-missing

smoke: install
	@set -e ; \
	SCRATCH=$$(mktemp -d) ; \
	echo "smoke: data dir = $$SCRATCH" ; \
	FLEXLOG_DATA_DIR=$$SCRATCH FLEXLOG_PORT=$(PORT) $(BIN)/flexlog & \
	APP_PID=$$! ; \
	sleep 2 ; \
	rc=0 ; \
	if curl -fsS http://127.0.0.1:$(PORT)/ > /dev/null ; then \
	    echo "OK: dashboard returns 200" ; \
	else \
	    echo "FAIL: dashboard did not respond" ; rc=1 ; \
	fi ; \
	[ -f "$$SCRATCH/.secret_key" ] && echo "OK: .secret_key created" || { echo "FAIL: .secret_key missing" ; rc=1 ; } ; \
	[ -f "$$SCRATCH/data/encounters.db" ] && echo "OK: encounters.db created" || { echo "FAIL: encounters.db missing" ; rc=1 ; } ; \
	kill $$APP_PID 2>/dev/null || true ; \
	wait $$APP_PID 2>/dev/null || true ; \
	rm -rf "$$SCRATCH" ; \
	exit $$rc

clean:
	rm -rf $(VENV) build dist *.egg-info .coverage .coverage.* htmlcov .pytest_cache
	find . -type d -name __pycache__ -exec rm -rf {} +
