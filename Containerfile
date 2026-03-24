# syntax=docker/dockerfile:1.4
# Python poker examples - standalone repo build
# Build: docker build -t poker-python-player --target agg-player .

ARG PYTHON_VERSION=3.11
ARG UV_VERSION=0.5.14

# ============================================================================
# Base - Python with uv and buf
# ============================================================================
FROM docker.io/library/python:${PYTHON_VERSION}-slim AS base

ARG UV_VERSION

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install uv
RUN curl -LsSf https://astral.sh/uv/${UV_VERSION}/install.sh | sh
ENV PATH=/root/.local/bin:$PATH

# Install buf
RUN ARCH=$(dpkg --print-architecture) && \
    case "$ARCH" in \
        amd64) BUF_ARCH="x86_64" ;; \
        arm64) BUF_ARCH="aarch64" ;; \
        *) echo "Unsupported architecture: $ARCH" && exit 1 ;; \
    esac && \
    curl -fLo /usr/local/bin/buf \
        "https://github.com/bufbuild/buf/releases/download/v1.47.2/buf-Linux-${BUF_ARCH}" && \
    chmod +x /usr/local/bin/buf

WORKDIR /app

# ============================================================================
# Dependencies - install angzarr-client and generate protos
# ============================================================================
FROM base AS deps

# Copy project files
COPY pyproject.toml uv.lock ./
COPY buf.gen.yaml ./

# Generate protos from buf registry
RUN mkdir -p angzarr/proto && buf generate

# Install dependencies (including angzarr-client from git)
RUN --mount=type=cache,id=uv-cache,target=/root/.cache/uv \
    uv sync --no-dev --no-install-project

# ============================================================================
# Source - copy application code
# ============================================================================
FROM deps AS source

COPY player ./player
COPY table ./table
COPY hand ./hand
COPY hand-flow ./hand-flow
COPY prj-output ./prj-output
COPY prj_training ./prj_training
COPY poker ./poker
COPY sagas ./sagas
COPY tournament ./tournament
COPY buy_in ./buy_in
COPY registration ./registration
COPY rebuy ./rebuy

# ============================================================================
# Runtime base
# ============================================================================
FROM docker.io/library/python:${PYTHON_VERSION}-slim AS runtime-base

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && useradd -m -u 1000 angzarr

WORKDIR /app
USER angzarr

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

# ============================================================================
# Aggregates
# ============================================================================
FROM runtime-base AS agg-player
COPY --from=deps --chown=angzarr:angzarr /app/.venv /app/.venv
COPY --from=deps --chown=angzarr:angzarr /app/angzarr /app/angzarr
COPY --from=source --chown=angzarr:angzarr /app/player /app/player
COPY --from=source --chown=angzarr:angzarr /app/poker /app/poker
ENV PATH=/app/.venv/bin:$PATH \
    PORT=50301
EXPOSE 50301
CMD ["python", "-m", "player.agg.main"]

FROM runtime-base AS agg-table
COPY --from=deps --chown=angzarr:angzarr /app/.venv /app/.venv
COPY --from=deps --chown=angzarr:angzarr /app/angzarr /app/angzarr
COPY --from=source --chown=angzarr:angzarr /app/table /app/table
COPY --from=source --chown=angzarr:angzarr /app/poker /app/poker
ENV PATH=/app/.venv/bin:$PATH \
    PORT=50302
EXPOSE 50302
CMD ["python", "-m", "table.agg.main"]

FROM runtime-base AS agg-hand
COPY --from=deps --chown=angzarr:angzarr /app/.venv /app/.venv
COPY --from=deps --chown=angzarr:angzarr /app/angzarr /app/angzarr
COPY --from=source --chown=angzarr:angzarr /app/hand /app/hand
COPY --from=source --chown=angzarr:angzarr /app/poker /app/poker
ENV PATH=/app/.venv/bin:$PATH \
    PORT=50303
EXPOSE 50303
CMD ["python", "-m", "hand.agg.main"]

# ============================================================================
# Projectors
# ============================================================================
FROM runtime-base AS prj-training
COPY --from=deps --chown=angzarr:angzarr /app/.venv /app/.venv
COPY --from=deps --chown=angzarr:angzarr /app/angzarr /app/angzarr
COPY --from=source --chown=angzarr:angzarr /app/prj_training /app/prj_training
COPY --from=source --chown=angzarr:angzarr /app/poker /app/poker
ENV PATH=/app/.venv/bin:$PATH \
    PORT=50491
EXPOSE 50491
CMD ["python", "-m", "prj_training.main"]
