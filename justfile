# Angzarr Python Examples - Poker Domain
#
# Container Overlay Pattern:
# --------------------------
# This justfile uses an overlay pattern for container execution:
#
# 1. `justfile` (this file) - runs on the host, delegates to container
# 2. `justfile.container` - mounted over this file inside the container
#
# When running outside a devcontainer:
#   - Builds/uses local devcontainer image with `just` pre-installed
#   - Docker mounts justfile.container as /workspace/justfile
#   - Runs with host UID/GID to avoid permission issues
#
# When running inside a devcontainer (DEVCONTAINER=true):
#   - Commands execute directly via `just <target>`
#   - No container nesting

set shell := ["bash", "-c"]

ROOT := `git rev-parse --show-toplevel`
ANGZARR_ROOT := `realpath "$(git rev-parse --show-toplevel)/../.."`
IMAGE := "angzarr-examples-python-dev"
UID := `id -u`
GID := `id -g`

# Build the devcontainer image
[private]
_build-image:
    docker build -t {{IMAGE}} -f "{{ROOT}}/.devcontainer/Containerfile" "{{ROOT}}/.devcontainer"

# Run just target in container (or directly if already in devcontainer)
[private]
_container +ARGS: _build-image
    #!/usr/bin/env bash
    if [ "${DEVCONTAINER:-}" = "true" ]; then
        just {{ARGS}}
    else
        docker run --rm --network=host \
            -u {{UID}}:{{GID}} \
            -e UV_CACHE_DIR=/angzarr/examples-python/main/.uv-cache \
            -e PLAYER_URL="${PLAYER_URL:-}" \
            -e TABLE_URL="${TABLE_URL:-}" \
            -e HAND_URL="${HAND_URL:-}" \
            -e TOURNAMENT_URL="${TOURNAMENT_URL:-}" \
            -e RESERVATION_URL="${RESERVATION_URL:-}" \
            -e KUBECONFIG=/home/user/.kube/config \
            -v "{{ANGZARR_ROOT}}:/angzarr" \
            -v "{{ROOT}}/justfile.container:/angzarr/examples-python/main/justfile:ro" \
            -v "/usr/bin/kubectl:/usr/local/bin/kubectl:ro" \
            -v "${HOME}/.kube:/home/user/.kube:ro" \
            -w /angzarr/examples-python/main \
            {{IMAGE}} just {{ARGS}}
    fi

# Run command in container as root (for cleanup tasks)
[private]
_container-root +ARGS: _build-image
    #!/usr/bin/env bash
    docker run --rm -u 0 \
        -v "{{ANGZARR_ROOT}}:/angzarr" \
        -w /angzarr/examples-python/main \
        {{IMAGE}} {{ARGS}}

# Clean up files created with wrong permissions
clean-venv:
    just _container-root rm -rf .venv .pytest_cache .uv-cache

default:
    @just --list

install:
    just _container install

test-pytest:
    just _container test-pytest

test-example-unit:
    just _container test-example-unit

test-example-acceptance:
    just _container test-example-acceptance

mutation-test:
    just _container mutation-test

test: test-pytest test-example-unit test-example-acceptance

fmt:
    just _container fmt

lint:
    just _container lint

typecheck:
    just _container typecheck

run-player:
    just _container run-player

run-table:
    just _container run-table

run-hand:
    just _container run-hand

# =============================================================================
# Kind Cluster & Deployment (runs on host, not in container)
# =============================================================================

KIND_CLUSTER := "poker-ai"
NAMESPACE := "angzarr"

# OCI chart references
CHART_REGISTRY := "oci://ghcr.io/angzarr-io/charts"
ANGZARR_CHART_VERSION := "0.5.1"

# Image names
PLAYER_IMAGE := "ghcr.io/angzarr-io/poker-python-player"
TABLE_IMAGE := "ghcr.io/angzarr-io/poker-python-table"
HAND_IMAGE := "ghcr.io/angzarr-io/poker-python-hand"
AI_IMAGE := "ghcr.io/angzarr-io/poker-python-ai-player"
SAGA_TABLE_HAND_IMAGE := "ghcr.io/angzarr-io/poker-python-saga-table-hand"
SAGA_TABLE_PLAYER_IMAGE := "ghcr.io/angzarr-io/poker-python-saga-table-player"
SAGA_HAND_TABLE_IMAGE := "ghcr.io/angzarr-io/poker-python-saga-hand-table"
SAGA_HAND_PLAYER_IMAGE := "ghcr.io/angzarr-io/poker-python-saga-hand-player"
TOURNAMENT_IMAGE := "ghcr.io/angzarr-io/poker-python-tournament"
RESERVATION_IMAGE := "ghcr.io/angzarr-io/poker-python-reservation"
PMG_RESERVATION_IMAGE := "ghcr.io/angzarr-io/poker-python-pmg-reservation"
AI_CHART := ROOT + "/deploy/k8s/helm/ai-player"

# =============================================================================
# Main deployment targets
# =============================================================================

# Deploy everything to kind cluster (repeatable)
up: kind-create seed-secrets seed-gateway-descriptor build-images load-images load-coordinators-local deploy-infra deploy-apps deploy-ai
    @echo "=== Deployment complete ==="
    @just status

# Load locally-built coordinator images into kind so the deploy doesn't fall
# back to the published :latest from GHCR (which can be stale relative to
# core/main HEAD — recently the published aggregate sidecar served gRPC
# routes that returned UNIMPLEMENTED, blocking acceptance tests). Skips
# silently if a tag isn't present locally so a fresh checkout still works
# off the published images.
load-coordinators-local:
    #!/usr/bin/env bash
    set -euo pipefail
    coordinators=(angzarr-aggregate angzarr-saga angzarr-process-manager angzarr-projector)
    for name in "${coordinators[@]}"; do
        img="ghcr.io/angzarr-io/${name}:latest"
        if docker image inspect "$img" >/dev/null 2>&1; then
            echo "Loading local $img into kind..."
            kind load docker-image "$img" --name {{KIND_CLUSTER}}
        else
            echo "Skipping $img (not built locally; will pull from registry on deploy)"
        fi
    done

# Build the gRPC gateway's protobuf descriptor with `buf build` and load it
# as a ConfigMap. The gateway pod mounts this to transcode HTTP/JSON → gRPC;
# without it the pod is stuck in ContainerCreating and the helm `--wait`
# in `deploy-apps` times out. CI does the equivalent step (see ci.yml).
# `kubectl create` (not `apply`) — the descriptor exceeds the 256KiB
# last-applied-configuration annotation cap; recreate is fine, the gateway
# rereads on container restart.
seed-gateway-descriptor: kind-create
    #!/usr/bin/env bash
    set -euo pipefail
    echo "=== Building gateway descriptor ==="
    tmp=$(mktemp --suffix=.bin)
    trap 'rm -f "$tmp"' EXIT
    (cd {{ROOT}}/angzarr-project/proto && buf build -o "$tmp")
    kubectl delete configmap gateway-descriptor -n {{NAMESPACE}} --ignore-not-found
    kubectl create configmap gateway-descriptor \
        --from-file=types.bin="$tmp" \
        --namespace {{NAMESPACE}}

# Generate random db/mq passwords and store them as a K8s Secret in the
# cluster. Idempotent: re-running rotates the passwords, so run this
# BEFORE deploy-infra / deploy-apps on a fresh cluster, and re-run the
# whole deploy chain when rotating.
#
# Passwords are never written to disk; generate_secrets.py emits a Secret
# manifest on stdout and we pipe it directly into kubectl.
seed-secrets: kind-create
    #!/usr/bin/env bash
    set -euo pipefail
    echo "=== Seeding angzarr-credentials Secret in namespace {{NAMESPACE}} ==="
    python3 {{ROOT}}/tools/generate_secrets.py \
        --namespace {{NAMESPACE}} \
        --name angzarr-credentials \
        | kubectl apply -f -

# Tear down kind cluster
down:
    kind delete cluster --name {{KIND_CLUSTER}} || true

# Show cluster status
status:
    #!/usr/bin/env bash
    echo "=== Pods ==="
    kubectl get pods -n {{NAMESPACE}} -o wide 2>/dev/null || echo "Namespace not found"
    echo ""
    echo "=== Services ==="
    kubectl get svc -n {{NAMESPACE}} 2>/dev/null || echo "Namespace not found"

# =============================================================================
# Build targets
# =============================================================================

# Build all images
build-images:
    #!/usr/bin/env bash
    set -euo pipefail
    echo "=== Building poker aggregates ==="
    docker build -t {{PLAYER_IMAGE}}:latest -f {{ROOT}}/Containerfile --target agg-player {{ROOT}}
    docker build -t {{TABLE_IMAGE}}:latest -f {{ROOT}}/Containerfile --target agg-table {{ROOT}}
    docker build -t {{HAND_IMAGE}}:latest -f {{ROOT}}/Containerfile --target agg-hand {{ROOT}}
    docker build -t {{TOURNAMENT_IMAGE}}:latest -f {{ROOT}}/Containerfile --target agg-tournament {{ROOT}}
    docker build -t {{RESERVATION_IMAGE}}:latest -f {{ROOT}}/Containerfile --target agg-reservation {{ROOT}}
    echo "=== Building reservation PM ==="
    docker build -t {{PMG_RESERVATION_IMAGE}}:latest -f {{ROOT}}/Containerfile --target pmg-reservation {{ROOT}}
    echo "=== Building poker sagas ==="
    docker build -t {{SAGA_TABLE_HAND_IMAGE}}:latest -f {{ROOT}}/Containerfile --target saga-table-hand {{ROOT}}
    docker build -t {{SAGA_TABLE_PLAYER_IMAGE}}:latest -f {{ROOT}}/Containerfile --target saga-table-player {{ROOT}}
    docker build -t {{SAGA_HAND_TABLE_IMAGE}}:latest -f {{ROOT}}/Containerfile --target saga-hand-table {{ROOT}}
    docker build -t {{SAGA_HAND_PLAYER_IMAGE}}:latest -f {{ROOT}}/Containerfile --target saga-hand-player {{ROOT}}
    echo "=== Building AI player ==="
    docker build -t {{AI_IMAGE}}:latest -f {{ROOT}}/ai_player/Containerfile --target production {{ROOT}}

# Load images into Kind
load-images:
    #!/usr/bin/env bash
    set -euo pipefail
    echo "=== Loading images into Kind ==="
    kind load docker-image {{PLAYER_IMAGE}}:latest --name {{KIND_CLUSTER}}
    kind load docker-image {{TABLE_IMAGE}}:latest --name {{KIND_CLUSTER}}
    kind load docker-image {{HAND_IMAGE}}:latest --name {{KIND_CLUSTER}}
    kind load docker-image {{TOURNAMENT_IMAGE}}:latest --name {{KIND_CLUSTER}}
    kind load docker-image {{RESERVATION_IMAGE}}:latest --name {{KIND_CLUSTER}}
    kind load docker-image {{PMG_RESERVATION_IMAGE}}:latest --name {{KIND_CLUSTER}}
    kind load docker-image {{SAGA_TABLE_HAND_IMAGE}}:latest --name {{KIND_CLUSTER}}
    kind load docker-image {{SAGA_TABLE_PLAYER_IMAGE}}:latest --name {{KIND_CLUSTER}}
    kind load docker-image {{SAGA_HAND_TABLE_IMAGE}}:latest --name {{KIND_CLUSTER}}
    kind load docker-image {{SAGA_HAND_PLAYER_IMAGE}}:latest --name {{KIND_CLUSTER}}
    kind load docker-image {{AI_IMAGE}}:latest --name {{KIND_CLUSTER}}

# Pull and load coordinator images into kind
load-coordinators:
    #!/usr/bin/env bash
    set -euo pipefail
    coordinators=(
        "angzarr-aggregate"
        "angzarr-saga"
        "angzarr-projector"
        "angzarr-grpc-gateway"
    )
    for name in "${coordinators[@]}"; do
        img="ghcr.io/angzarr-io/${name}:latest"
        echo "Pulling $img..."
        docker pull "$img"
        echo "Loading $img into kind..."
        kind load docker-image "$img" --name {{KIND_CLUSTER}}
    done

# =============================================================================
# Cluster & infrastructure targets
# =============================================================================

# Create Kind cluster
kind-create:
    #!/usr/bin/env bash
    set -euo pipefail
    if kind get clusters 2>/dev/null | grep -q "^{{KIND_CLUSTER}}$"; then
        echo "Cluster {{KIND_CLUSTER}} already exists"
    else
        kind create cluster --config {{ROOT}}/kind-config.yaml
    fi
    kubectl create namespace {{NAMESPACE}} --dry-run=client -o yaml | kubectl apply -f -

# Delete Kind cluster
kind-delete:
    kind delete cluster --name {{KIND_CLUSTER}} || true

# Deploy infrastructure (postgres, rabbitmq).
#
# Passwords come from the in-cluster Secret ``angzarr-credentials``
# (populated by ``just seed-secrets``). They're injected into the infra
# charts via ``--set-string`` on every install so there's no in-repo
# fallback and no file on disk that holds a credential. If the Secret
# is missing the recipe fails early with a clear message.
#
# Chart-side: ``angzarr-db-postgres-simple`` / ``angzarr-mq-rabbitmq-simple``
# may or may not honor these override keys. Where a chart ignores the
# override, its own internal default applies; the associated app-side
# URI will then fail to auth and the pod will crash loudly — which is
# the right signal ("chart can't consume the override yet") rather than
# silently succeeding with a baked-in secret. Track chart-extension
# needs separately rather than papering over with our own hard-coded
# fallback.
deploy-infra:
    #!/usr/bin/env bash
    set -euo pipefail
    DB_PW=$(kubectl get secret -n {{NAMESPACE}} angzarr-credentials \
        -o jsonpath='{.data.db-password}' 2>/dev/null | base64 -d)
    MQ_PW=$(kubectl get secret -n {{NAMESPACE}} angzarr-credentials \
        -o jsonpath='{.data.mq-password}' 2>/dev/null | base64 -d)
    if [[ -z "$DB_PW" || -z "$MQ_PW" ]]; then
        echo "error: angzarr-credentials Secret missing db-password or mq-password." >&2
        echo "       run 'just seed-secrets' first." >&2
        exit 1
    fi
    echo "=== Deploying PostgreSQL ==="
    helm upgrade --install angzarr-db {{CHART_REGISTRY}}/angzarr-db-postgres-simple \
      --namespace {{NAMESPACE}} \
      --set fullnameOverride=angzarr-db \
      --set-string auth.password="$DB_PW" \
      --set-string auth.postgresPassword="$DB_PW" \
      --wait --timeout 2m
    echo "=== Deploying RabbitMQ ==="
    helm upgrade --install angzarr-mq {{CHART_REGISTRY}}/angzarr-mq-rabbitmq-simple \
      --namespace {{NAMESPACE}} \
      --set fullnameOverride=angzarr-mq \
      --set-string auth.password="$MQ_PW" \
      --wait --timeout 3m
    echo "Infrastructure deployed"

# =============================================================================
# Application deployment targets
# =============================================================================

# Deploy poker applications using Helm.
#
# values.yaml holds UNUSED_REPLACED_AT_DEPLOY sentinels for the password
# / uri / url fields — they are intentionally invalid so that a forgotten
# override triggers an auth failure rather than a silent connection.
# This recipe reads the real values from the in-cluster Secret
# ``angzarr-credentials`` and injects them via ``--set-string``. The
# secret itself is populated by ``just seed-secrets``; this recipe fails
# early if the Secret (or either required key) is missing.
deploy-apps:
    #!/usr/bin/env bash
    set -euo pipefail
    DB_PW=$(kubectl get secret -n {{NAMESPACE}} angzarr-credentials \
        -o jsonpath='{.data.db-password}' 2>/dev/null | base64 -d)
    MQ_PW=$(kubectl get secret -n {{NAMESPACE}} angzarr-credentials \
        -o jsonpath='{.data.mq-password}' 2>/dev/null | base64 -d)
    if [[ -z "$DB_PW" || -z "$MQ_PW" ]]; then
        echo "error: angzarr-credentials Secret missing db-password or mq-password." >&2
        echo "       run 'just seed-secrets' first." >&2
        exit 1
    fi
    echo "=== Deploying poker applications ==="
    helm upgrade --install poker {{CHART_REGISTRY}}/angzarr \
      --version {{ANGZARR_CHART_VERSION}} \
      -f {{ROOT}}/values.yaml \
      --set-string storage.postgres.password="$DB_PW" \
      --set-string storage.postgres.uri="postgres://angzarr:${DB_PW}@angzarr-db:5432/angzarr" \
      --set-string messaging.amqp.url="amqp://angzarr:${MQ_PW}@angzarr-mq:5672/%2F" \
      --namespace {{NAMESPACE}} \
      --wait --timeout 5m
    echo "Poker applications deployed"

# Deploy AI Player with helm
deploy-ai:
    #!/usr/bin/env bash
    set -euo pipefail
    echo "=== Deploying AI Player ==="
    helm upgrade --install poker-ai-player {{AI_CHART}} \
        --namespace {{NAMESPACE}} \
        --wait --timeout 2m
    echo "AI Player deployed"

# Undeploy AI Player
undeploy-ai:
    helm uninstall poker-ai-player --namespace {{NAMESPACE}} || true

# =============================================================================
# AI Player targets
# =============================================================================

# Build AI Player container image
ai-build tag="latest":
    docker build \
        -t {{AI_IMAGE}}:{{tag}} \
        -f {{ROOT}}/ai_player/Containerfile \
        --target production \
        {{ROOT}}

# Generate AI Player protos from buf registry
ai-proto:
    cd {{ROOT}}/ai_player && buf generate

# Integration tests against the running AiSidecar container image.
# Prereq: `just ai-build` (or `docker pull` the published image).
# --confcutdir isolates these from the outer tests/conftest.py, which imports
# angzarr_client's older ai_sidecar proto and would collide in the protobuf
# descriptor pool with the ai_player-local generated pb2.
ai-test-integration:
    cd {{ROOT}} && AI_IMAGE={{AI_IMAGE}}:latest uv run --frozen pytest \
        tests/integration/ai_player/ -v --no-cov -p no:cacheprovider \
        --confcutdir=tests/integration/ai_player \
        --rootdir=tests/integration/ai_player

# Show AI Player status
ai-status:
    kubectl get pods -n {{NAMESPACE}} -l app.kubernetes.io/name=poker-ai-player
    kubectl get svc -n {{NAMESPACE}} -l app.kubernetes.io/name=poker-ai-player

# View AI Player logs
ai-logs:
    kubectl logs -n {{NAMESPACE}} -l app.kubernetes.io/name=poker-ai-player -f

# Port-forward AI Player service (for local testing)
ai-forward:
    kubectl port-forward -n {{NAMESPACE}} svc/poker-ai-player 50500:50500

# Run game with AI Player (assumes ai-forward is running in another terminal)
run-game-ai *ARGS:
    just _container run-game-ai {{ARGS}}

# Auto-format code
fmt-fix:
    just _container fmt-fix

# =============================================================================
# Submodule management
# =============================================================================
# Submodules are kept chmod a-w so accidental edits (Claude, editors, scripts)
# fail loudly. Use the `bump-*` targets to update — they unlock, pull the
# tracking branch, stage the new pointer, then relock.

# Lock submodules read-only (filesystem enforcement).
submodules-lock:
    chmod -R a-w angzarr-project angzarr-client-python

# Unlock submodules for manual edits. Remember to `submodules-lock` after.
submodules-unlock:
    chmod -R u+w angzarr-project angzarr-client-python

# Bump angzarr-project to latest on its tracking branch.
bump-angzarr-project:
    chmod -R u+w angzarr-project
    git submodule update --remote --merge angzarr-project
    git add angzarr-project
    chmod -R a-w angzarr-project

# Bump angzarr-client-python to latest on its tracking branch.
bump-angzarr-client-python:
    chmod -R u+w angzarr-client-python
    git submodule update --remote --merge angzarr-client-python
    git add angzarr-client-python
    chmod -R a-w angzarr-client-python
