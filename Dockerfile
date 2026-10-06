# syntax=docker/dockerfile:1.7
# ─────────────────────────────────────────────────────────────────────────────
# Vidimus — multi-stage Dockerfile
#
# Stage 1 (builder): install deps and build a wheel
# Stage 2 (runtime): minimal slim image with only the wheel + runtime deps
# Final image: ~150 MB, runs as non-root, no build tooling in production
# ─────────────────────────────────────────────────────────────────────────────

# ───────────────── Stage 1: builder ──────────────────
FROM python:3.12-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy only dependency manifests first (better layer caching)
COPY pyproject.toml README.md LICENSE ./
COPY src/ ./src/

RUN pip install --upgrade pip build && \
    python -m build --wheel --outdir /wheels .

# ───────────────── Stage 2: runtime ──────────────────
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    VIDIMUS_HOME=/home/vidimus/.vidimus

# Non-root user
RUN groupadd --system --gid 1001 vidimus && \
    useradd  --system --uid 1001 --gid vidimus --create-home vidimus

WORKDIR /app

COPY --from=builder /wheels/*.whl /tmp/
RUN pip install /tmp/*.whl && rm /tmp/*.whl

USER vidimus

# Pre-create the keystore directory with correct permissions
RUN mkdir -p "${VIDIMUS_HOME}/keys" && chmod 700 "${VIDIMUS_HOME}/keys"

HEALTHCHECK --interval=30s --timeout=5s --start-period=3s --retries=3 \
    CMD vidimus version || exit 1

ENTRYPOINT ["vidimus"]
CMD ["--help"]

# ─── Build & run ─────────────────────────────────────
# docker build -t vidimus:latest .
# docker run --rm vidimus:latest version
# docker run --rm -v $(pwd)/data:/data vidimus:latest attest --since 24h
# ─────────────────────────────────────────────────────
