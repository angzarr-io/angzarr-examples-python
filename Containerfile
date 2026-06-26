# syntax=docker/dockerfile:1.4
# Python poker examples - self-contained repo build.
#
# Layout: the poker components live in the ``angzarr_poker`` package under
# ``src/`` as domain-grouped vertical slices, one entrypoint PER component
# (per-component images / services — no consolidated saga/PM host):
#   aggregates  -> angzarr_poker.<domain>.aggregate.main          (5)
#   sagas       -> angzarr_poker.<domain>.sagas.<name>.main       (6)
#   process mgr -> angzarr_poker.<domain>.process_managers.<name>.main  (2)
#   projectors  -> angzarr_poker.player.projectors.main           (player read model + query)
#                  angzarr_poker._shared.projectors.output.main   (cross-domain narrator)
#
# Each target launches its module with ``uv run`` (uv resolves/paths the locked
# deps); the package stays on PYTHONPATH so launch uses ``--no-sync``. Components
# dispatch through the FFI router (``angzarr_router_ffi``), an editable path dep
# at ``vendor/angzarr-router-ffi`` whose cdylib is located via ANGZARR_ROUTER_LIB.
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
# uv launches each component (`uv run` resolves/paths the deps from the locked
# env). It needs the uv binary + the project manifest/lock alongside the
# pre-resolved .venv; the package itself stays on PYTHONPATH (=/app/src), so the
# launch uses `--no-sync` to run the existing env without re-resolving.
COPY --from=base /root/.local/bin/uv /usr/local/bin/uv
COPY --from=deps --chown=angzarr:angzarr /app/pyproject.toml /app/uv.lock ./
ENV PATH=/app/.venv/bin:$PATH \
    UV_PROJECT_ENVIRONMENT=/app/.venv

# ============================================================================
# Component services — one target per component (domain-grouped vertical slices,
# angzarr_poker.<domain>.<type>[.<name>].main). Per-component services: each
# saga / process-manager runs its own coordinator (replicas=1) rather than a
# single consolidated host.
# ============================================================================

# --- Aggregates (one per domain) ---
FROM app AS agg-player
ENV PORT=50401
EXPOSE 50401
CMD ["uv", "run", "--no-sync", "--no-cache", "python", "-m", "angzarr_poker.player.aggregate.main"]

FROM app AS agg-table
ENV PORT=50402
EXPOSE 50402
CMD ["uv", "run", "--no-sync", "--no-cache", "python", "-m", "angzarr_poker.table.aggregate.main"]

FROM app AS agg-hand
ENV PORT=50403
EXPOSE 50403
CMD ["uv", "run", "--no-sync", "--no-cache", "python", "-m", "angzarr_poker.hand.aggregate.main"]

FROM app AS agg-tournament
ENV PORT=50404
EXPOSE 50404
CMD ["uv", "run", "--no-sync", "--no-cache", "python", "-m", "angzarr_poker.tournament.aggregate.main"]

# Reservation aggregate: owns lifecycle records (pending buy-in / rebuy /
# registration) and emits the *Requested / *Confirmed / *Released events.
FROM app AS agg-reservation
ENV PORT=50405
EXPOSE 50405
CMD ["uv", "run", "--no-sync", "--no-cache", "python", "-m", "angzarr_poker.reservation.aggregate.main"]

# --- Sagas (one service per saga, owned by its source domain) ---
FROM app AS saga-table-hand
ENV PORT=50411
EXPOSE 50411
CMD ["uv", "run", "--no-sync", "--no-cache", "python", "-m", "angzarr_poker.table.sagas.table_hand.main"]

FROM app AS saga-table-player
ENV PORT=50412
EXPOSE 50412
CMD ["uv", "run", "--no-sync", "--no-cache", "python", "-m", "angzarr_poker.table.sagas.table_player.main"]

FROM app AS saga-table-tournament
ENV PORT=50413
EXPOSE 50413
CMD ["uv", "run", "--no-sync", "--no-cache", "python", "-m", "angzarr_poker.table.sagas.table_tournament.main"]

FROM app AS saga-hand-table
ENV PORT=50414
EXPOSE 50414
CMD ["uv", "run", "--no-sync", "--no-cache", "python", "-m", "angzarr_poker.hand.sagas.hand_table.main"]

FROM app AS saga-hand-player
ENV PORT=50415
EXPOSE 50415
CMD ["uv", "run", "--no-sync", "--no-cache", "python", "-m", "angzarr_poker.hand.sagas.hand_player.main"]

FROM app AS saga-tournament-table
ENV PORT=50416
EXPOSE 50416
CMD ["uv", "run", "--no-sync", "--no-cache", "python", "-m", "angzarr_poker.tournament.sagas.tournament_table.main"]

# --- Process managers (one service per PM, owned by its source domain) ---
FROM app AS pmg-hand-flow
ENV PORT=50395
EXPOSE 50395
CMD ["uv", "run", "--no-sync", "--no-cache", "python", "-m", "angzarr_poker.hand.process_managers.hand_flow.main"]

FROM app AS pmg-reservation
ENV PORT=50396
EXPOSE 50396
CMD ["uv", "run", "--no-sync", "--no-cache", "python", "-m", "angzarr_poker.reservation.process_managers.reservation.main"]

# --- Projectors ---
# OutputProjector: auxiliary cross-domain narrator (read-model renderer).
FROM app AS projector-output
ENV PORT=50491
EXPOSE 50491
CMD ["uv", "run", "--no-sync", "--no-cache", "python", "-m", "angzarr_poker._shared.projectors.output.main"]

# PlayerProjector: per-domain bankroll read model + PlayerProjectionQueryService
# on the same port (queried out-of-process for EA-0004 read-model consistency).
FROM app AS projector-player
ENV PORT=50492
EXPOSE 50492
CMD ["uv", "run", "--no-sync", "--no-cache", "python", "-m", "angzarr_poker.player.projectors.main"]
