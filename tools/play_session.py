"""Watch a live blackjack session: one basic-strategy player against a deployed
cluster (`just demo-session [rounds]`). Not a component and never deployed.

Hard totals: stand on 17+, stand on 12-16 against a dealer 2-6, otherwise hit;
double on 10 or 11 against a lower dealer card. Soft totals: stand on 18+.
"""

from __future__ import annotations

import sys

from acceptance_steps import _play as play
from acceptance_steps._client import TABLE, ClusterClient
from acceptance_steps._world import World
from angzarr_blackjack._gen.io.angzarr.examples.v1 import table_pb2 as _table
from angzarr_blackjack.cards import format_cards, hand_value, points


def decide(cards, dealer_up, can_double: bool):
    total, soft = hand_value(cards)
    up = 11 if dealer_up.rank == 1 else points(dealer_up)
    if can_double and not soft and total in (10, 11) and up < total:
        return _table.DoubleDown
    if soft:
        return _table.Stand if total >= 18 else _table.Hit
    if total >= 17 or (total >= 12 and 2 <= up <= 6):
        return _table.Stand
    return _table.Hit


def main(rounds: int = 5) -> None:
    client = ClusterClient()
    w = World(client, None)
    play.register(w, "Demo", 1000)
    play.open_table(w, "Demo", seed=7)
    play.buy_in(w, "Demo", 0, 500, "Demo")
    for number in range(1, rounds + 1):
        play.bet(w, "Demo", 20, "Demo")
        play.deal(w, "Demo")
        state = play.table_state(w, "Demo")
        while state.phase == play.Phase.PHASE_PLAYER_TURNS:
            seat = state.seated[state.turn]
            action = decide(
                seat.hand.cards, state.dealer_cards[0], len(seat.hand.cards) == 2
            )
            play.must(w, TABLE, w.table("Demo"), action(seat=state.turn))
            state = play.table_state(w, "Demo")
        settled = play.stored(w, TABLE, w.table("Demo"), _table.RoundSettled)[-1]
        played = play.stored(w, TABLE, w.table("Demo"), _table.DealerPlayed)[-1]
        outcome = settled.outcomes[0]
        print(
            f"round {number}: dealer {played.total} ({format_cards([played.hole, *played.drawn])}) "
            f"-> {_table.SeatOutcome.Outcome.Name(outcome.outcome)}, stack {outcome.stack_after}"
        )
    client.close()


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 5)
