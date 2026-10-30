#!/bin/bash
# Post-create setup for Python example devcontainer

set -e

# Install system dependencies
sudo apt-get update && sudo apt-get install -y --no-install-recommends \
    jq \
    && sudo rm -rf /var/lib/apt/lists/*

# Install just
curl --proto '=https' --tlsv1.2 -sSf https://just.systems/install.sh | bash -s -- --to ~/.local/bin

# Install uv (fast Python package manager)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Create local bin directory
mkdir -p ~/.local/bin

# Add local bin to PATH
echo 'export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"' >> ~/.bashrc

# Set up the root's tooling environment and the player's
if [ -f "pyproject.toml" ]; then
    ~/.cargo/bin/uv sync
fi
if [ -f "player/pyproject.toml" ]; then
    (cd player && ~/.cargo/bin/uv sync)
fi

echo ""
echo "Python development environment ready!"
echo "  - uv: fast package manager"
echo "  - ruff: linting and formatting"
echo ""
echo "Quick start:"
echo "  just test                          # The root's tests (tools/)"
echo "  just --justfile player/justfile test   # The player's tests"
echo "  just                               # List all commands"
