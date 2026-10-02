# syntax=docker/dockerfile:1.4
# Blackjack example (Python): one image per deployable component.
#
# The components live in the ``angzarr_blackjack`` package under ``src/``:
#   agg-player                     -> angzarr_blackjack.player.agg.main (+ upcaster)
#   agg-table                      -> angzarr_blackjack.table.agg.main
#   pmg-buy-in                     -> angzarr_blackjack.pmg_buy_in.main
#   saga-player-table              -> angzarr_blackjack.player.saga_table.main
#   saga-table-player              -> angzarr_blackjack.table.saga_player.main
#   projector-player-table-ledger  -> angzarr_blackjack.prj_ledger.main
#
# The build context must hold the generated ``src/angzarr_blackjack/_gen``
# (`just proto-gen`). The deps stage installs angzarr-client from its pinned
# git revision, which builds its router library with cargo.
#
# Each target launches its module with ``uv run`` (uv resolves/paths the locked
# deps); the package stays on PYTHONPATH so launch uses ``--no-sync``. Components
# dispatch through the router binding ``angzarr_client.router``; its library
# ships inside the angzarr-client package.
#
# Build: docker build -t examples-python-agg-player --target agg-player .

ARG PYTHON_VERSION=3.11
ARG UV_VERSION=0.10.3

# ============================================================================
# Base - Python with uv
# ============================================================================
FROM docker.io/library/python:${PYTHON_VERSION}-slim AS base

ARG UV_VERSION

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    ca-certificates \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

# cargo builds angzarr-client's router library when uv installs it.
ENV RUSTUP_HOME=/opt/rust/rustup \
    CARGO_HOME=/opt/rust/cargo \
    PATH=/opt/rust/cargo/bin:$PATH
RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs \
        | sh -s -- -y --profile minimal --default-toolchain stable --no-modify-path

# Install uv
RUN curl -LsSf https://astral.sh/uv/${UV_VERSION}/install.sh | sh
ENV PATH=/root/.local/bin:$PATH

WORKDIR /app

# ============================================================================
# Dependencies - resolve the locked env (incl. angzarr-client, built from its
# git revision). Project itself is not
# installed; the package is consumed from ``src`` via PYTHONPATH so the build
# caches deps independently of source churn.
# ============================================================================
FROM base AS deps

COPY pyproject.toml uv.lock ./

RUN --mount=type=cache,id=uv-cache,target=/root/.cache/uv \
    uv sync --no-dev --no-install-project

# ============================================================================
# Source - copy the application package
# ============================================================================
FROM deps AS source

COPY src ./src

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
    PYTHONPATH=/app/src

# ============================================================================
# App base - the resolved venv + angzarr-client + the blackjack package. Every
# component target shares this; each only sets its PORT + entrypoint module.
# ============================================================================
FROM runtime-base AS app
COPY --from=deps   --chown=angzarr:angzarr /app/.venv  /app/.venv
COPY --from=source --chown=angzarr:angzarr /app/src    /app/src
# uv launches each component (`uv run` resolves/paths the deps from the locked
# env). It needs the uv binary + the project manifest/lock alongside the
# pre-resolved .venv; the package itself stays on PYTHONPATH (=/app/src), so the
# launch uses `--no-sync` to run the existing env without re-resolving.
COPY --from=base /root/.local/bin/uv /usr/local/bin/uv
COPY --from=deps --chown=angzarr:angzarr /app/pyproject.toml /app/uv.lock ./
ENV PATH=/app/.venv/bin:$PATH \
    UV_PROJECT_ENVIRONMENT=/app/.venv

# ============================================================================
# Component services — one target per deployable; each runs next to its own
# coordinator (replicas=1).
# ============================================================================

FROM app AS agg-player
ENV PORT=50401
EXPOSE 50401
CMD ["uv", "run", "--no-sync", "--no-cache", "python", "-m", "angzarr_blackjack.player.agg.main"]

FROM app AS agg-table
ENV PORT=50402
EXPOSE 50402
CMD ["uv", "run", "--no-sync", "--no-cache", "python", "-m", "angzarr_blackjack.table.agg.main"]

FROM app AS saga-player-table
ENV PORT=50411
EXPOSE 50411
CMD ["uv", "run", "--no-sync", "--no-cache", "python", "-m", "angzarr_blackjack.player.saga_table.main"]

FROM app AS saga-table-player
ENV PORT=50412
EXPOSE 50412
CMD ["uv", "run", "--no-sync", "--no-cache", "python", "-m", "angzarr_blackjack.table.saga_player.main"]

FROM app AS pmg-buy-in
ENV PORT=50421
EXPOSE 50421
CMD ["uv", "run", "--no-sync", "--no-cache", "python", "-m", "angzarr_blackjack.pmg_buy_in.main"]

FROM app AS projector-player-table-ledger
ENV PORT=50431
EXPOSE 50431
CMD ["uv", "run", "--no-sync", "--no-cache", "python", "-m", "angzarr_blackjack.prj_ledger.main"]
