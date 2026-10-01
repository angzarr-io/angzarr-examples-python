# Angzarr blackjack example (Python)
#
# Container overlay pattern:
#   * `justfile` (this file) runs on the host and delegates build/test recipes
#     to the dev container;
#   * `justfile.container` is mounted over it inside the container (and used
#     directly by CI container jobs).
# Inside a devcontainer (DEVCONTAINER=true) recipes run directly.
#
# Cluster recipes (kind, skaffold, helm, kubectl) run on the host.

set shell := ["bash", "-c"]

# Reusable submodule-protection recipes (install-submodule-hooks,
# check-submodules-clean). Source of truth: angzarr-project/submodule.just.
import? 'angzarr-project/submodule.just'

ROOT := `git rev-parse --show-toplevel`
ANGZARR_ROOT := `realpath "$(git rev-parse --show-toplevel)/../.."`
REPO_DIR := file_name(ROOT)
IMAGE := "angzarr-examples-python-dev"
UID := `id -u`
GID := `id -g`

# Build the devcontainer image
[private]
_build-image:
    docker build -t {{IMAGE}} -f "{{ROOT}}/.devcontainer/Containerfile" "{{ROOT}}/.devcontainer"

# Run a justfile.container recipe in the dev container (or directly inside one).
[private]
_container +ARGS: _build-image
    #!/usr/bin/env bash
    set -euo pipefail
    if [ "${DEVCONTAINER:-}" = "true" ]; then
        just -f justfile.container {{ARGS}}
    else
        # Rootless Docker maps the container's root to the host user, so files
        # written in the mounted repo stay host-owned only when the container
        # runs as root; rootful Docker needs the host UID/GID instead. The
        # security options are read whole before matching: under pipefail,
        # `docker info | grep -q` fails whenever grep exits before docker
        # finishes writing.
        security_options="$(docker info --format '{{{{json .SecurityOptions}}')"
        if [[ "${security_options}" == *rootless* ]]; then
            user_flag=(-u 0:0)
        else
            user_flag=(-u {{UID}}:{{GID}})
        fi
        docker run --rm --network=host \
            "${user_flag[@]}" \
            -e UV_CACHE_DIR=/angzarr/examples-python/{{REPO_DIR}}/.uv-cache \
            -e PLAYER_URL="${PLAYER_URL:-}" \
            -e TABLE_URL="${TABLE_URL:-}" \
            -e LEDGER_URL="${LEDGER_URL:-}" \
            -e AMQP_URL="${AMQP_URL:-}" \
            -e ANGZARR_CLI_SRC="${ANGZARR_CLI_SRC:-/angzarr/angzarr-cli/main}" \
            -e ANGZARR_ROUTER_SRC="${ANGZARR_ROUTER_SRC:-/angzarr/angzarr-router/main}" \
            -e KUBECONFIG=/home/user/.kube/config \
            -v "{{ANGZARR_ROOT}}:/angzarr" \
            -v "{{ROOT}}/justfile.container:/angzarr/examples-python/{{REPO_DIR}}/justfile:ro" \
            -v "/usr/bin/kubectl:/usr/local/bin/kubectl:ro" \
            -v "${HOME}/.kube:/home/user/.kube:ro" \
            -w /angzarr/examples-python/{{REPO_DIR}} \
            {{IMAGE}} just {{ARGS}}
    fi

default:
    @just --list

# --- build and test (in the dev container) ------------------------------------------

cli-build:
    just _container cli-build

client-setup:
    just -f justfile.container client-setup

proto-gen:
    just _container proto-gen

install:
    just _container install

test-unit:
    just _container test-unit

test-example-unit:
    just _container test-example-unit

test-example-acceptance:
    just _container test-example-acceptance

acceptance-dry-run:
    just _container acceptance-dry-run

test:
    just _container test

mutation-test:
    just _container mutation-test

fmt *FLAGS:
    just _container fmt {{FLAGS}}

fmt-fix:
    just _container fmt-fix

lint:
    just _container lint

demo-session *ARGS:
    just _container demo-session {{ARGS}}

components:
    @just -f {{ROOT}}/justfile.container components

# --- CI entry points ---------------------------------------------------------------------

# Tests, lint, format check and the acceptance dry run.
ci-test:
    just _container ci-test

# Build every component image (skaffold, content-addressed tags).
ci-images:
    skaffold build --file-output={{ROOT}}/build.json

# Deploy to a kind cluster (published chart) and run the required acceptance
# scenarios.
ci-acceptance:
    SKAFFOLD_PROFILE=ci just up
    just -f justfile.container test-example-acceptance

# --- kind cluster and deployment (host) ------------------------------------------------------

KIND_CLUSTER := "angzarr-blackjack"
NAMESPACE := "angzarr"
CHART_REGISTRY := "oci://ghcr.io/angzarr-io/charts"

# Deploy everything to the kind cluster (repeatable).
up: kind-create seed-secrets deploy-infra deploy-apps
    @just status

# Tear down the kind cluster.
down:
    kind delete cluster --name {{KIND_CLUSTER}} || true

status:
    #!/usr/bin/env bash
    kubectl get pods -n {{NAMESPACE}} -o wide 2>/dev/null || echo "Namespace not found"
    kubectl get svc -n {{NAMESPACE}} 2>/dev/null || true

kind-create:
    #!/usr/bin/env bash
    set -euo pipefail
    if ! kind get clusters 2>/dev/null | grep -q "^{{KIND_CLUSTER}}$"; then
        kind create cluster --config {{ROOT}}/kind-config.yaml
    fi
    kubectl create namespace {{NAMESPACE}} --dry-run=client -o yaml | kubectl apply -f -

# Generate db/mq passwords into the angzarr-credentials Secret (never on disk).
seed-secrets: kind-create
    python3 {{ROOT}}/tools/generate_secrets.py --namespace {{NAMESPACE}} --name angzarr-credentials \
        | kubectl apply -f -

[private]
_credentials:
    #!/usr/bin/env bash
    set -euo pipefail
    for key in db-password mq-password; do
        kubectl get secret -n {{NAMESPACE}} angzarr-credentials -o jsonpath="{.data.${key}}" | base64 -d >/dev/null \
            || { echo "angzarr-credentials is missing ${key}; run 'just seed-secrets'" >&2; exit 1; }
    done

# PostgreSQL and RabbitMQ, with the passwords from angzarr-credentials.
deploy-infra: _credentials
    #!/usr/bin/env bash
    set -euo pipefail
    DB_PW=$(kubectl get secret -n {{NAMESPACE}} angzarr-credentials -o jsonpath='{.data.db-password}' | base64 -d)
    MQ_PW=$(kubectl get secret -n {{NAMESPACE}} angzarr-credentials -o jsonpath='{.data.mq-password}' | base64 -d)
    helm upgrade --install angzarr-db {{CHART_REGISTRY}}/angzarr-db-postgres-simple \
      --namespace {{NAMESPACE}} --set fullnameOverride=angzarr-db \
      --set-string auth.password="$DB_PW" --set-string auth.postgresPassword="$DB_PW" \
      --wait --timeout 2m
    helm upgrade --install angzarr-mq {{CHART_REGISTRY}}/angzarr-mq-rabbitmq-simple \
      --namespace {{NAMESPACE}} --set fullnameOverride=angzarr-mq \
      --set-string auth.password="$MQ_PW" \
      --wait --timeout 3m

# Build the component images, load them into kind and deploy the example.
deploy-apps: _credentials
    #!/usr/bin/env bash
    set -euo pipefail
    export ANGZARR_DB_PASSWORD=$(kubectl get secret -n {{NAMESPACE}} angzarr-credentials -o jsonpath='{.data.db-password}' | base64 -d)
    export ANGZARR_MQ_PASSWORD=$(kubectl get secret -n {{NAMESPACE}} angzarr-credentials -o jsonpath='{.data.mq-password}' | base64 -d)
    cd {{ROOT}}
    # Build, load the images into the kind node (they are never pushed), then
    # deploy exactly those builds.
    skaffold build --kube-context "kind-{{KIND_CLUSTER}}" --file-output=build.json
    for image in $(python3 -c 'import json; print(" ".join(b["tag"] for b in json.load(open("build.json"))["builds"]))'); do
        kind load docker-image "$image" --name {{KIND_CLUSTER}}
    done
    skaffold deploy --kube-context "kind-{{KIND_CLUSTER}}" --build-artifacts=build.json --status-check=true

# --- submodules -----------------------------------------------------------------------------
# Submodules are kept chmod a-w so accidental edits fail loudly.

submodules-lock:
    chmod -R a-w angzarr-project

submodules-unlock:
    chmod -R u+w angzarr-project

bump-angzarr-project:
    chmod -R u+w angzarr-project
    git submodule update --remote --merge angzarr-project
    git add angzarr-project
    chmod -R a-w angzarr-project
