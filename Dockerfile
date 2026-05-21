# Python 3.11 slim — small base, modern Python. Build deps for
# sqlcipher3 + Pillow are installed in a separate layer.
FROM python:3.11-slim-bookworm

# System deps required for sqlcipher3 (libsqlcipher) + pillow-heif
# (libheif) + image transcoding (libjpeg, zlib).
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libsqlcipher-dev \
    libheif-dev \
    libjpeg-dev \
    zlib1g-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Hash-pinned install — copy lock first so Docker layer cache
# survives source-only changes.
COPY pyproject.toml requirements.lock ./
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir --require-hashes -r requirements.lock

# Copy source tree
COPY flexlog/ ./flexlog/
COPY scripts/ ./scripts/

# Editable install of flexlog itself (no deps re-resolve)
RUN pip install --no-cache-dir -e . --no-deps

# Vendor integrity check (in-image files, no Volume needed)
RUN cd flexlog/static/vendor && sha256sum -c INTEGRITY.txt

EXPOSE 5050

# HEALTHCHECK — Railway also uses railway.json's healthcheckPath
# but Docker-native HEALTHCHECK helps local Docker runs too.
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD curl -fs http://localhost:${PORT:-5050}/ || exit 1

# Shell form (NOT JSON array) so $PORT expands at runtime.
# `exec` so SIGTERM reaches gunicorn directly (graceful shutdown).
# 1 worker because SQLCipher + SQLite + multi-process don't mix;
# 4 gthread threads handles concurrent media reads for a single user.
# --timeout 1800: default 30s kills any request that takes longer,
#   which means multi-hundred-MB uploads return 502. Bumped to 30 min
#   so large media uploads (audio/video) complete. Note: Railway's
#   edge proxy has its OWN request timeout (~few minutes) — uploads
#   over ~500 MB may still 502 at the edge regardless of this setting.
#   See docs/DEPLOYMENT.md for the "large file" guidance.
CMD exec gunicorn \
    --bind "0.0.0.0:${PORT:-5050}" \
    --workers 1 \
    --threads 4 \
    --worker-class gthread \
    --timeout 1800 \
    --graceful-timeout 30 \
    --access-logfile - \
    --error-logfile - \
    "flexlog.app:create_app()"
