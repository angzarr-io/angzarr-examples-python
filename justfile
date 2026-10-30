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

# Reusable submodule-protection and secret-scanning recipes
# (install-submodule-hooks, check-submodules-clean, scan-secrets). Source of truth: angzarr-project/submodule.just.
import? 'angzarr-project/submodule.just'

ROOT := `git rev-parse --show-toplevel`
# The repository's shared git dir: `.git` of the main checkout, also when ROOT
# is a linked worktree (whose `.git` file points into it). Mounted at its own
# path in the dev container so git resolves there.
GIT_COMMON := `git rev-parse --path-format=absolute --git-common-dir`
# The angzarr-cli source checkout `cli-build` compiles. Defaults to the
# sibling of this repository's main checkout (the workspace layout
# <workspace>/examples-python/main beside <workspace>/angzarr-cli/main), found
# from the shared git dir so a worktree elsewhere resolves the same checkout.
CLI_SRC := env_var_or_default("ANGZARR_CLI_SRC", parent_directory(GIT_COMMON) / "../../angzarr-cli/main")
IMAGE := "angzarr-examples-python-dev"
UID := `id -u`
GID := `id -g`

# Build the devcontainer image
[private]
_build-image:
    #!/usr/bin/env bash
    set -euo pipefail
    # Inside a devcontainer _container runs recipes directly, so no image is
    # needed (and there is no docker to build one with).
    if [ "${DEVCONTAINER:-}" = "true" ]; then
        exit 0
    fi
    docker build -t {{IMAGE}} -f "{{ROOT}}/.devcontainer/Containerfile" "{{ROOT}}/.devcontainer"

# Run a justfile.container recipe in the dev container (or directly inside one).
#
# The container sees exactly what the build needs, wherever the checkout
# lives (main checkout or a linked worktree):
#   * ROOT (this checkout's top level) at /workspace, the working directory,
#     with justfile.container mounted over its justfile;
#   * the shared git dir at its own host path, so git works in a worktree;
#   * the angzarr-cli source (CLI_SRC) at /deps/angzarr-cli, for `cli-build`.
# The uv cache stays inside the checkout (.uv-cache), as before.
[private]
_container +ARGS: _build-image
    #!/usr/bin/env bash
    set -euo pipefail
    if [ "${DEVCONTAINER:-}" = "true" ]; then
        just --justfile "{{ROOT}}/justfile.container" {{ARGS}}
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
        cli_mount=()
        if [ -d "{{CLI_SRC}}" ]; then
            cli_mount=(-v "$(realpath "{{CLI_SRC}}"):/deps/angzarr-cli")
        fi
        docker run --rm --network=host \
            "${user_flag[@]}" \
            -e UV_CACHE_DIR=/workspace/.uv-cache \
            -e ANGZARR_CLI_SRC=/deps/angzarr-cli \
            -e KUBECONFIG=/home/user/.kube/config \
            -e GIT_CONFIG_COUNT=1 \
            -e GIT_CONFIG_KEY_0=safe.directory \
            -e GIT_CONFIG_VALUE_0='*' \
            -v "{{ROOT}}:/workspace" \
            -v "{{GIT_COMMON}}:{{GIT_COMMON}}" \
            "${cli_mount[@]}" \
            -v "{{ROOT}}/justfile.container:/workspace/justfile:ro" \
            -v "/usr/bin/kubectl:/usr/local/bin/kubectl:ro" \
            -v "${HOME}/.kube:/home/user/.kube:ro" \
            -w /workspace \
            {{IMAGE}} just {{ARGS}}
    fi

default:
    @just --list

# --- build and test (in the dev container) ------------------------------------------

cli-build:
    just _container cli-build


proto-gen:
    just _container proto-gen

install:
    just _container install

# Generate the build version (src/angzarr_blackjack/_version.py) with versionator.
version:
    just _container version

test-unit:
    just _container test-unit

test-example-unit:
    just _container test-example-unit

test:
    just _container test

mutation-test *CHANGED:
    just _container mutation-test {{CHANGED}}

# lefthook's pre-push step, given the remote's name and git's pushed refs on
# stdin: every test, the root app's (`just install`, then `just test`, in the
# dev container) and the player's (`install` and `test` of player/justfile,
# on the host), in each pushed commit's tree checked out alone at
# build/push-tree, so an unpushed edit cannot pass or fail it. No mutation: no
# git hook runs it. The push tree's angzarr-project is the pushed commit's
# submodule commit, exported from this checkout's submodule (fetched if it is
# missing there); its .tools (the angzarr CLI) is copied from here, and its
# .uv-cache starts as a hard-linked copy of this checkout's. The range
# reported runs from the merge base of the commit pushed and the remote's
# current tip of that ref (a fast-forward's base is that tip); for a new ref,
# or a tip not fetched here, the merge base with the remote's default branch
# (<remote>/HEAD, else main). A deleted ref passes at once. The log is
# build/logs/push-tests.log.
#
# Red tests are allowed on a branch and kept out of the default branch: pushed
# to another branch, failing tests pass with a warning that the branch cannot
# merge until they pass; pushed to the default branch they are refused.
# `lefthook` is what lefthook.yml passes to stop lefthook skipping it, and is
# ignored. To check a push to main by hand without pushing:
#
#     echo "refs/heads/B $(git rev-parse HEAD) refs/heads/main 0" | just push-check origin
[positional-arguments]
push-check remote *lefthook:
    #!/usr/bin/env bash
    set -euo pipefail
    # git exports repository-locating variables (GIT_DIR, ...) into a hook;
    # with them, a git -C the push tree or a submodule would act on this
    # checkout instead.
    unset $(git rev-parse --local-env-vars)
    top='{{ROOT}}'
    remote=$1
    default=$(git -C "$top" symbolic-ref --quiet --short "refs/remotes/$remote/HEAD" 2>/dev/null) && default=${default#"$remote"/} || default=main
    tree="$top/build/push-tree"
    mkdir -p "$top/build/logs"
    log="$top/build/logs/push-tests.log"
    exec 9> "$top/build/.push-tree.lock"
    flock 9
    pushed=0
    while read -r local_ref local_sha remote_ref remote_sha; do
        [ -n "${local_sha:-}" ] || continue
        [ "${local_sha//0/}" = "" ] && continue  # a deletion
        pushed=1
        target=${remote_ref#refs/heads/}
        base=
        if [ -n "${remote_sha//0/}" ] && git -C "$top" cat-file -e "$remote_sha^{commit}" 2>/dev/null; then
            base=$(git -C "$top" merge-base "$remote_sha" "$local_sha") || base=
        fi
        if [ -z "$base" ]; then
            for ref in "refs/remotes/$remote/$default" "refs/heads/$default"; do
                if git -C "$top" rev-parse --verify --quiet "$ref^{commit}" > /dev/null; then
                    base=$(git -C "$top" merge-base "$ref" "$local_sha") && break
                fi
            done
        fi
        if [ -z "$base" ]; then
            echo "FAIL push-check: $local_ref shares no history with $remote's tip or with $default" >&2
            exit 1
        fi
        range="$(git -C "$top" rev-parse --short "$base")..$(git -C "$top" rev-parse --short "$local_sha") to $remote/$target"
        # The pushed commit's tree, alone; no hook of this repository runs for
        # it (core.hooksPath), and its .venv and .uv-cache (ignored, so kept
        # by clean) carry across pushes.
        nohooks=(-c core.hooksPath=/dev/null)
        if ! git -C "$tree" rev-parse --git-dir > /dev/null 2>&1; then
            rm -rf "$tree"
            git -C "$top" worktree prune
            git "${nohooks[@]}" -C "$top" worktree add --quiet --detach --no-checkout "$tree" "$local_sha"
        fi
        git "${nohooks[@]}" -C "$tree" checkout --quiet --detach --force "$local_sha"
        git -C "$tree" clean -fdq
        sub=$(git -C "$top" ls-tree "$local_sha" angzarr-project | awk '{print $3}')
        if ! git -C "$top/angzarr-project" cat-file -e "$sub^{commit}" 2>/dev/null; then
            git -C "$top/angzarr-project" fetch --quiet origin "$sub" || {
                echo "FAIL push-check: angzarr-project $sub, the pushed commit's submodule, is not here (git submodule update --init)" >&2
                exit 1
            }
        fi
        rm -rf "$tree/angzarr-project"
        mkdir -p "$tree/angzarr-project"
        git -C "$top/angzarr-project" archive "$sub" | tar -x -C "$tree/angzarr-project"
        if [ ! -d "$tree/.tools" ] && [ -d "$top/.tools" ]; then cp -a "$top/.tools" "$tree/.tools"; fi
        if [ ! -d "$tree/.uv-cache" ] && [ -d "$top/.uv-cache" ]; then cp -al "$top/.uv-cache" "$tree/.uv-cache"; fi
        rc=0
        (
            cd "$tree"
            just --justfile "$tree/justfile" install
            just --justfile "$tree/justfile" test
            just --justfile "$tree/player/justfile" install
            just --justfile "$tree/player/justfile" test
        ) > "$log" 2>&1 9>&- || rc=$?
        if [ "$rc" -ne 0 ]; then
            if [ "$remote_ref" != "refs/heads/$default" ]; then
                echo "RED  push-check: $range: the tests fail (build/logs/push-tests.log); allowed off $default, which $target cannot merge into until they pass"
                continue
            fi
            echo "FAIL push-check: $range: the tests fail, and $default takes no red tests (full log: build/logs/push-tests.log)" >&2
            grep -E '^(FAILED|ERROR|error:)|[0-9]+ (failed|error)|^Failing scenarios' "$log" | head -20 >&2 || true
            exit 1
        fi
        echo "ok   push-check ($range): tests pass"
    done
    [ "$pushed" = 1 ] || echo "ok   push-check (no commit pushed: nothing to test)"

test-tools:
    just _container test-tools

fmt *FLAGS:
    just _container fmt {{FLAGS}}

fmt-fix:
    just _container fmt-fix

lint:
    just _container lint

archlint:
    just _container archlint

components:
    @just -f {{ROOT}}/justfile.container components

# --- CI entry points ---------------------------------------------------------------------

# Tests, lint, architecture lint and the format check.
ci-test:
    just _container ci-test

# Build every component image (skaffold, content-addressed tags).
ci-images:
    skaffold build --file-output={{ROOT}}/build.json

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
# An existing Secret is kept: PostgreSQL and RabbitMQ keep the passwords they
# were first deployed with, so replacing them would lock every component out.
seed-secrets: kind-create
    #!/usr/bin/env bash
    set -euo pipefail
    if kubectl get secret -n {{NAMESPACE}} angzarr-credentials >/dev/null 2>&1; then
        exit 0
    fi
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
    # deploy exactly those builds. Always rebuilt: the git-commit tag of a
    # working tree with uncommitted changes never changes, so skaffold's
    # artifact cache would serve stale images (docker's layer cache keeps an
    # unchanged build fast).
    skaffold build --kube-context "kind-{{KIND_CLUSTER}}" --cache-artifacts=false --file-output=build.json
    for image in $(python3 -c 'import json; print(" ".join(b["tag"] for b in json.load(open("build.json"))["builds"]))'); do
        kind load docker-image "$image" --name {{KIND_CLUSTER}}
    done
    skaffold deploy --kube-context "kind-{{KIND_CLUSTER}}" --build-artifacts=build.json --status-check=true

# --- local deployment against core built from source (host) ------------------------------
#
# `just core-images` builds the four coordinators from a core checkout
# (ANGZARR_CORE_SRC, default ../../core/main) with core's own skaffold and
# loads them into kind; `just deploy-apps-local` then deploys the components
# with that checkout's chart and coordinators. (The cluster acceptance tier
# and `just acceptance-local` wait on the blackjack rulings R1-R4; README.)

CORE_SRC := env_var_or_default("ANGZARR_CORE_SRC", ROOT + "/../../core/main")
CORE_BUILD := ROOT + "/.core-build.json"
CORE_COORDINATORS := "angzarr-aggregate angzarr-saga angzarr-projector angzarr-process-manager"

# Build the coordinators from CORE_SRC with core's skaffold; load them into kind.
core-images: kind-create
    #!/usr/bin/env bash
    set -euo pipefail
    cd "{{CORE_SRC}}"
    images=(-b ghcr.io/angzarr-io/angzarr-base -b ghcr.io/angzarr-io/angzarr-rust)
    for c in {{CORE_COORDINATORS}}; do images+=(-b "ghcr.io/angzarr-io/$c"); done
    # Always rebuild (docker's layer cache keeps unchanged builds fast): the
    # git-commit tag of a checkout with uncommitted changes never changes, so
    # skaffold's artifact cache would serve images built before the changes.
    skaffold build "${images[@]}" --cache-artifacts=false --file-output="{{CORE_BUILD}}"
    for c in {{CORE_COORDINATORS}}; do
        kind load docker-image "$(just -f {{justfile()}} _core-image "$c")" --name {{KIND_CLUSTER}}
    done

# The built tag of one coordinator image (from CORE_BUILD).
[private]
_core-image name:
    @python3 -c 'import json,sys; print(next(b["tag"] for b in json.load(open(sys.argv[1]))["builds"] if b["imageName"].endswith("/" + sys.argv[2])).split("@")[0])' "{{CORE_BUILD}}" "{{name}}"

# Deploy the components with the chart and coordinators from CORE_SRC.
deploy-apps-local:
    #!/usr/bin/env bash
    set -euo pipefail
    export ANGZARR_CORE_SRC="$(realpath "{{CORE_SRC}}")"
    for c in {{CORE_COORDINATORS}}; do
        image="$(just -f {{justfile()}} _core-image "$c")"
        var="$(echo "${c#angzarr-}" | tr 'a-z-' 'A-Z_')"
        export "ANGZARR_${var}_TAG=${image##*:}"
    done
    SKAFFOLD_PROFILE=local-core just -f {{justfile()}} deploy-apps

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
