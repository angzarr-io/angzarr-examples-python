# syntax=docker/dockerfile:1.4
# Python poker examples - self-contained repo build.
#
# Layout: the poker components live in the ``angzarr_poker`` package under
# ``src/`` (the post-reorg layout). Every component-type is a single service
# entrypoint:
#   aggregates  -> angzarr_poker.{player,table,hand,tournament,reservation}.main
#   sagas       -> angzarr_poker.sagas.main           (hosts all 6 sagas)
#   process mgr -> angzarr_poker.process_managers.main (hosts hand_flow + reservation)
#   projector   -> angzarr_poker.projectors.main
#
# Components dispatch through the FFI router (``angzarr_router_ffi``), an
# editable path dep at ``vendor/angzarr-router-ffi`` whose cdylib is located at
# runtime via ANGZARR_ROUTER_LIB.
#
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
# Dependencies - resolve the locked env (incl. the editable router-ffi path
# source: its Python binding + cdylib under vendor/). Project itself is not
# installed; the package is consumed from ``src`` via PYTHONPATH so the build
# caches deps independently of source churn.
# ============================================================================
FROM base AS deps

COPY pyproject.toml uv.lock ./
COPY vendor ./vendor

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
    PYTHONPATH=/app/src \
    ANGZARR_ROUTER_LIB=/app/vendor/angzarr-router-ffi/libangzarr_router_ffi.so

# ============================================================================
# App base - the resolved venv + router-ffi cdylib + the poker package. Every
# component target shares this; each only sets its PORT + entrypoint module.
# ============================================================================
FROM runtime-base AS app
COPY --from=deps   --chown=angzarr:angzarr /app/.venv  /app/.venv
COPY --from=deps   --chown=angzarr:angzarr /app/vendor /app/vendor
COPY --from=source --chown=angzarr:angzarr /app/src    /app/src
ENV PATH=/app/.venv/bin:$PATH

# ============================================================================
# Aggregates - one service per domain
# ============================================================================
FROM app AS agg-player
ENV PORT=50401
EXPOSE 50401
CMD ["python", "-m", "angzarr_poker.player.main"]

FROM app AS agg-table
ENV PORT=50402
EXPOSE 50402
CMD ["python", "-m", "angzarr_poker.table.main"]

FROM app AS agg-hand
ENV PORT=50403
EXPOSE 50403
CMD ["python", "-m", "angzarr_poker.hand.main"]

FROM app AS agg-tournament
ENV PORT=50404
EXPOSE 50404
CMD ["python", "-m", "angzarr_poker.tournament.main"]

# Reservation aggregate: owns lifecycle records (pending buy-in / rebuy /
# registration) and emits the *Requested / *Confirmed / *Released events that
# drive the reservation PM.
FROM app AS agg-reservation
ENV PORT=50405
EXPOSE 50405
CMD ["python", "-m", "angzarr_poker.reservation.main"]

# ============================================================================
# Sagas - one service hosting every poker saga. The core routes a source event
# by its cover domain to each registered saga that consumes it, so the single
# service backs the table, hand, and tournament saga coordinators.
# ============================================================================
FROM app AS saga
ENV PORT=50410
EXPOSE 50410
CMD ["python", "-m", "angzarr_poker.sagas.main"]

# ============================================================================
# Process managers - one service hosting every poker PM (hand_flow +
# reservation). The core routes a trigger to every co-resident PM that consumes
# its domain.
# ============================================================================
FROM app AS pmg
ENV PORT=50395
EXPOSE 50395
CMD ["python", "-m", "angzarr_poker.process_managers.main"]

# ============================================================================
# Projector - OutputProjector (read-model renderer)
# ============================================================================
FROM app AS projector
ENV PORT=50491
EXPOSE 50491
CMD ["python", "-m", "angzarr_poker.projectors.main"]

# ============================================================================
# Player projector - per-domain bankroll read model. Folds player-domain funds
# events into a queryable read model and ALSO serves PlayerProjectionQueryService
# on the same port, so a client can observe read-model eventual consistency from
# outside the write side (EA-0004). Distinct from the auxiliary OutputProjector.
# ============================================================================
FROM app AS projector-player
ENV PORT=50492
EXPOSE 50492
CMD ["python", "-m", "angzarr_poker.projectors.player_main"]
