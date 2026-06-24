"""Cross-domain orchestration steps — the reservation PM deciding a buy-in /
registration / rebuy against its FOLDED cross-domain read model (look-before-leap
without a synchronous read).

The Given seeds the orchestrator's read model by folding the other domain's state
event (e.g. table.TableCreated, carrying the buy-in range) into the PM's
process_state via ``prior_events``; the When dispatches the request trigger; the
Then asserts the orchestrator either offered the command (accept) or refused up
front with a failure event and NO command (refuse).
"""

from __future__ import annotations

from behave import given, then, when

from angzarr_poker._gen.io.angzarr.examples.v1 import buy_in_pb2 as buy_in
from angzarr_poker._gen.io.angzarr.examples.v1 import poker_types_pb2 as poker
from angzarr_poker._gen.io.angzarr.examples.v1 import table_pb2 as table
from unit_steps._harness import uuid_for

P = "io.angzarr.examples.v1."


def _reservation_id(player: str) -> bytes:
    return uuid_for(f"{player}-buy-in")


@given(
    'table "{table_name}" has seat {seat:d} available with a buy-in range of '
    "{low:d} to {high:d}"
)
def _given_table_range(context, table_name, seat, low, high):
    context.orch_table = table_name
    # Folded into the PM's read model so the buy-in decision can see the range.
    context.orch_prior = [
        (
            P + "TableCreated",
            table.TableCreated(min_buy_in=low, max_buy_in=high, max_players=9),
        )
    ]


@given("{player} has requested a buy-in for seat {seat:d} with amount {amount:d}")
def _given_buy_in_request(context, player, seat, amount):
    context.orch_player = player
    context.orch_buy_in = buy_in.BuyInRequested(
        player_root=uuid_for(player),
        table_root=uuid_for(context.orch_table),
        reservation_id=_reservation_id(player),
        seat=seat,
        amount=poker.Currency(amount=amount, currency_code="CHIPS"),
    )


@when("{player}'s buy-in is processed")
def _when_buy_in_processed(context, player):
    context.world.dispatch_process_manager(
        "reservation",
        P + "BuyInRequested",
        context.orch_buy_in,
        prior_events=getattr(context, "orch_prior", None),
    )


def _emitted_command_fqs(context):
    return [fq for (_domain, fq, _cmd) in context.world.emitted_commands()]


@then('{player} is offered seat {seat:d} at table "{table_name}"')
def _then_offered_seat(context, player, seat, table_name):
    for _domain, fq, cmd_any in context.world.emitted_commands():
        if fq == P + "SeatPlayer":
            cmd = buy_in.SeatPlayer()
            cmd.ParseFromString(cmd_any.value)
            assert cmd.seat == seat, f"offered seat {cmd.seat}, expected {seat}"
            return
    raise AssertionError(
        f"no SeatPlayer offered; commands={_emitted_command_fqs(context)}"
    )


@then("the buy-in is recorded as initiated")
def _then_recorded_initiated(context):
    context.world.process_event(P + "BuyInInitiated", buy_in.BuyInInitiated())


@then("{player} is not offered a seat")
def _then_not_offered(context, player):
    fqs = _emitted_command_fqs(context)
    assert (
        P + "SeatPlayer" not in fqs
    ), f"a seat was offered (SeatPlayer); commands={fqs}"


@then("the buy-in is refused because the amount is outside the allowed range")
def _then_refused_out_of_range(context):
    failed = buy_in.BuyInFailed()
    context.world.process_event(P + "BuyInFailed", failed)
    assert failed.failure.code == "AMOUNT_OUT_OF_RANGE", failed.failure.code
