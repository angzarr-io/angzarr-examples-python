> **⚠️ Notice:** This repository was recently extracted from the [angzarr monorepo](https://github.com/angzarr-io/angzarr) and has not yet been validated as a standalone project. Expect rough edges. See the [Angzarr documentation](https://angzarr.io/) for more information.

# Angzarr Python Examples

Example implementations demonstrating angzarr-client usage in Python.

## Overview

This repository contains poker domain examples implementing:
- Player aggregate (bankroll management)
- Table aggregate (game state)
- Hand aggregate (gameplay logic)
- Cross-domain sagas and process managers
- Projectors for read models

## Installation

```bash
pip install angzarr-client
```

## Build

Generate proto files from buf registry:

```bash
buf generate
```

## Run Tests

```bash
behave
```

## Deploy

Build and deploy to Kubernetes:

```bash
skaffold run
```

## License

BSD-3-Clause


## Development

### Setup

Install git hooks (requires [lefthook](https://github.com/evilmartians/lefthook)):

```bash
lefthook install
```

This configures a pre-commit hook that auto-formats code before each commit.

### Recipes

```bash
just -l              # List all available recipes
just build           # Build the library
just test            # Run tests
just fmt             # Check formatting
just fmt-fix         # Auto-format code
```
