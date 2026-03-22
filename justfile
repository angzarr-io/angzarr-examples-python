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
