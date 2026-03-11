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

MIT - See LICENSE file
