# syntax=docker/dockerfile:1.4
# Python poker examples - standalone repo build
# Build: docker build -t poker-python-player --target agg-player .

ARG PYTHON_VERSION=3.11
ARG UV_VERSION=0.10.3

# ============================================================================
# Base - Python with uv
# ============================================================================
FROM docker.io/library/python:${PYTHON_VERSION}-slim AS base

ARG UV_VERSION

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

# Install uv
RUN curl -LsSf https://astral.sh/uv/${UV_VERSION}/install.sh | sh
ENV PATH=/root/.local/bin:$PATH

WORKDIR /app

# ============================================================================
# Dependencies - install angzarr-client and generate protos
# ============================================================================
FROM base AS deps

# Copy project files and angzarr-client-python submodule (local path source)
COPY pyproject.toml uv.lock ./
COPY angzarr-client-python ./angzarr-client-python

# Copy pre-generated protos (buf generate runs in CI before docker build)
COPY proto ./proto
RUN mkdir -p angzarr/proto

# Install dependencies (including angzarr-client from local path source)
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
