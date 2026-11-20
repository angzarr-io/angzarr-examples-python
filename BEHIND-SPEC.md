# This branch is known to be way behind the spec

Branch `chore/project-f7362501` bumps the `angzarr-project` submodule to
`f736250199182ad25cba9b2ae26ba9481915a5e5` (angzarr-project `main`, 2026-11-20).
The code in this repository has not caught up with that spec. **This branch is
not meant to be merged as-is.**

## What is broken here

Declared red. It depends on the lagging `angzarr-client-python`, and regenerating against the new spec is unverified.

The default branch `main` was already red (the README calls it "intentionally
lagging") since the 2026-05-19 submodule bump; this branch does not fix that.

## What a port needs

- Reason keys (done for Python only).
- Removal of `Handling` and `ConflictResolution`.
- `CommandResult`.
- The Command | Fact split.
- Descriptor checks and the child handshake, which moved to the coordinator.
- Typed refusal messages.
