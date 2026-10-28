"""Shared building blocks for the in-process step definitions.

Givens run the real commands through the components, so every history a
scenario starts from is one the components themselves produced.
"""

from __future__ import annotations

from angzarr_blackjack._gen.io.angzarr.examples.v1 import table_pb2 as _table
from unit_steps._harness import TABLE, World, table_root

TABLE_DEFAULTS = dict(
    min_bet=10, max_bet=100, min_buy_in=100, max_buy_in=1000, seats=3, decks=1
)


def ok(outcome):
    assert outcome.error is None, f"setup step was refused: {outcome.error}"
    return outcome


# --- the table -----------------------------------------------------------------


def create_table(w: World, name: str = "Main", seed: int = 42, **config):
    settings = {**TABLE_DEFAULTS, **config}
    return w.command(
        TABLE,
        table_root(name),
        _table.CreateTable(name=name, shoe_seed=seed, **settings),
    )


def table_state(w: World, name: str = "Main") -> _table.TableState:
    return w.state(TABLE, table_root(name))
