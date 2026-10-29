# PLACEHOLDER: replace with `angzarr scaffold python` output.
"""The player as a child process of angzarr-embedded: the PlayerAggregate
on a ComponentHost, served under angzarr_client.child's handshake."""

from __future__ import annotations

from angzarr_client import ComponentHost, configure_logging
from angzarr_client.child import run_child

from ._gen.io.angzarr.examples.v1.player_aggregate_angzarr import (
    new_player_aggregate_dispatch,
)
from ._version import __version__
from .adapter import PlayerAggregate


def register(host: ComponentHost) -> ComponentHost:
    """The PlayerAggregate on ``host``."""
    return host.add_aggregate(new_player_aggregate_dispatch(PlayerAggregate()))


def host() -> ComponentHost:
    """The child's host, reporting the build version versionator generated
    (``_version``) as its rules_version."""
    return register(ComponentHost(rules_version=__version__))


def main() -> None:
    configure_logging()
    run_child(host())


if __name__ == "__main__":
    main()
