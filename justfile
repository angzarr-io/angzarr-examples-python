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
            -v "{{ANGZARR_ROOT}}:/angzarr" \
            -v "{{ROOT}}/justfile.container:/angzarr/examples-python/main/justfile:ro" \
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

test-unit:
    just _container test-unit

test-acceptance:
    just _container test-acceptance

test: test-unit test-acceptance

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
ANGZARR_CHART_VERSION := "0.2.2"

# Image names
PLAYER_IMAGE := "ghcr.io/angzarr-io/poker-python-player"
TABLE_IMAGE := "ghcr.io/angzarr-io/poker-python-table"
HAND_IMAGE := "ghcr.io/angzarr-io/poker-python-hand"
AI_IMAGE := "ghcr.io/angzarr-io/poker-python-ai-player"
AI_CHART := ROOT + "/deploy/k8s/helm/ai-player"

# =============================================================================
# Main deployment targets
# =============================================================================

# Deploy everything to kind cluster (repeatable)
up: kind-create build-images load-images deploy-infra deploy-apps deploy-ai
    @echo "=== Deployment complete ==="
    @just status

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

# Deploy infrastructure (postgres, rabbitmq)
deploy-infra:
    #!/usr/bin/env bash
    set -euo pipefail
    echo "=== Deploying PostgreSQL ==="
    helm upgrade --install angzarr-db {{CHART_REGISTRY}}/angzarr-db-postgres-simple \
      --namespace {{NAMESPACE}} \
      --wait --timeout 2m
    echo "=== Deploying RabbitMQ ==="
    helm upgrade --install angzarr-mq {{CHART_REGISTRY}}/angzarr-mq-rabbitmq-simple \
      --namespace {{NAMESPACE}} \
      --wait --timeout 3m
    echo "Infrastructure deployed"

# =============================================================================
# Application deployment targets
# =============================================================================

# Deploy poker applications using Helm
deploy-apps:
    #!/usr/bin/env bash
    set -euo pipefail
    echo "=== Deploying poker applications ==="
    helm upgrade --install poker {{CHART_REGISTRY}}/angzarr \
      --version {{ANGZARR_CHART_VERSION}} \
      -f {{ROOT}}/values.yaml \
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
