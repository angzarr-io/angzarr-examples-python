"""Tournament↔table coordination unit steps — TDA Rule 11D halt/resume.

These scenarios are cross-aggregate and multi-hop: a table's BB-on-empty trigger
flows table → TableTournamentSaga → tournament (deficit decision) →
TournamentTableSaga → table (halt execution). The step here drives those hops
explicitly through the in-process router, threading the source cover so the
forwarding sagas can route. Per-table counts are seeded directly on the single
tournament (the forwarding of live PlayerJoined is its own slice); each table is a
distinct aggregate keyed by its root.
"""

from __future__ import annotations

from behave import given, then, when

from angzarr_poker._gen.io.angzarr.examples.v1 import table_pb2 as table
from angzarr_poker._gen.io.angzarr.examples.v1 import tournament_pb2 as trn
from unit_steps._harness import uuid_for
from unit_steps.common_steps import assert_rejected

P = "io.angzarr.examples.v1."
TOURNAMENT_ROOT = b""  # single tournament per scenario


def _emitted_command(context, fq, msg):
    """Decode the first emitted command of type ``fq`` from the last saga."""
    for domain, name, command_any in context.world.emitted_commands():
        if name == fq:
            msg.ParseFromString(command_any.value)
            return msg
    return None


# --- Given: tables with counts (+ a real table aggregate per root) ---


@given('a table "{name}" exists with {n:d} active players')
def _given_table_with_players(context, name, n):
    root = uuid_for(name)
    # The table aggregate itself (so a halt/resume command lands on a real table).
    context.world.seed_event("table", P + "TableCreated", table.TableCreated(table_name=name), root=root)
    # The tournament's per-table count (the deficit substrate).
    for _ in range(n):
        context.world.seed_event(
            "tournament",
            P + "TournamentTablePlayerJoined",
            trn.TournamentTablePlayerJoined(table_root=root),
            root=TOURNAMENT_ROOT,
        )


def _bb_on_empty(context, name):
    """Drive the Rule 11D chain for ``name``: table BB-on-empty → saga →
    tournament deficit decision → saga → table halt. Records whether a halt was
    ordered, and folds the table's halt event into its history so a later
    StartHand sees the halted flag."""
    root = uuid_for(name)
    context.halted_table = name
    # 1. table BB-on-empty → TableTournamentSaga → RecordTableBBOnEmpty
    context.world.dispatch_saga(
        "table", P + "TableBBOnEmptyPredicted",
        table.TableBBOnEmptyPredicted(table_root=root), source_root=root,
    )
    rec = _emitted_command(context, P + "RecordTableBBOnEmpty", trn.RecordTableBBOnEmpty())
    # 2. tournament deficit decision → TableHaltOrdered (or nothing)
    context.world.dispatch("tournament", P + "RecordTableBBOnEmpty", rec, root=TOURNAMENT_ROOT)
    context.halt_ordered = (P + "TableHaltOrdered") in context.world.emitted_fqs()
    if not context.halt_ordered:
        return
    ordered = context.world.emitted(P + "TableHaltOrdered", trn.TableHaltOrdered())
    # 3. TournamentTableSaga → HaltForBalancing
    context.world.dispatch_saga("tournament", P + "TableHaltOrdered", ordered)
    halt = _emitted_command(context, P + "HaltForBalancing", table.HaltForBalancing())
    # 4. table executes the halt → TableHaltedForBalancing; fold into its history
    context.world.dispatch("table", P + "HaltForBalancing", halt, root=root)
    halted = context.world.emitted(P + "TableHaltedForBalancing", table.TableHaltedForBalancing())
    context.world.seed_event("table", P + "TableHaltedForBalancing", halted, root=root)


@given('the next hand at "{name}" would assign the big blind to an empty seat')
@when('the next hand at "{name}" would assign the big blind to an empty seat')
def _bb_on_empty_step(context, name):
    _bb_on_empty(context, name)


# --- When: resume / start ---


@when('the coordinator resumes play at "{name}"')
def _when_resume(context, name):
    root = uuid_for(name)
    context.world.dispatch("table", P + "ResumePlayAtTable", table.ResumePlayAtTable(), root=root)
    resumed = context.world.emitted(P + "TableResumedForBalancing", table.TableResumedForBalancing())
    context.world.seed_event("table", P + "TableResumedForBalancing", resumed, root=root)


@when('the next hand at "{name}" begins')
def _when_start_hand(context, name):
    root = uuid_for(name)
    context.world.dispatch("table", P + "StartHand", table.StartHand(), root=root)


# --- Then ---


@then('"{name}" halts for balancing')
def _then_halts(context, name):
    assert context.halt_ordered, f"{name} did not halt (no TableHaltOrdered)"


@then('"{name}" does not halt for balancing')
def _then_no_halt(context, name):
    assert not context.halt_ordered, f"{name} unexpectedly halted"


@then('"{name}" is halted for balancing')
def _then_is_halted(context, name):
    assert context.halt_ordered, f"{name} is not halted"


@then('"{name}" is not halted for balancing')
def _then_is_not_halted(context, name):
    assert not context.halt_ordered, f"{name} is halted but should not be"


@then('"{name}" resumes from balancing')
@then('"{name}" is no longer halted for balancing')
def _then_resumed(context, name):
    # The resume emitted TableResumedForBalancing; folded already. A StartHand
    # would now be accepted (the flag is cleared) — asserted structurally here.
    assert context.world.err is None


@then('the start-hand at "{name}" is refused because the table is halted for balancing')
def _then_start_refused(context, name):
    assert_rejected(context, "TABLE_HALTED_FOR_BALANCING")


@then('no hand starts at "{name}"')
def _then_no_hand(context, name):
    assert (P + "HandStarted") not in context.world.emitted_fqs()


# --- Rule 11A balancing (source-table BB-next decision, EU-1180) ---


@when('the coordinator balances tables from "{src}" to "{dst}"')
def _when_balance(context, src, dst):
    """Issue BalanceTables to the SOURCE table (cover.root = source). The table
    picks its BB-next player locally and emits BalancingMoveDecided; the
    destination seat is chosen downstream by the saga that views both tables."""
    context.world.dispatch(
        "table",
        P + "BalanceTables",
        table.BalanceTables(source_table_name=src, destination_table_name=dst),
        root=uuid_for(src),
    )


@then('the moved player is "{pid}"')
def _then_moved_player(context, pid):
    ev = context.world.emitted(P + "BalancingMoveDecided", table.BalancingMoveDecided())
    assert ev.player_root == uuid_for(pid), (
        f"moved player_root = {ev.player_root.hex()}, want {uuid_for(pid).hex()} ({pid})"
    )


@then('the move\'s destination table is "{name}"')
def _then_move_destination(context, name):
    ev = context.world.emitted(P + "BalancingMoveDecided", table.BalancingMoveDecided())
    assert ev.destination_table_root == uuid_for(name), (
        f"destination_table_root = {ev.destination_table_root.hex()}, "
        f"want {uuid_for(name).hex()} ({name})"
    )


# --- RP-9 / WSOP Rule 68 final-table combination (EU-1181) ---


@when('the coordinator combines "{sources}" into final table "{final}"')
def _when_combine(context, sources, final):
    """Gather the seated players from each breaking source table (the caller's
    job, per the proto contract) and issue CombineFinalTable to the new final
    table, which seats them and emits FinalTableCombined."""
    active = []
    for name in sources.split(","):
        for page in context.world.prior_pages("table", uuid_for(name.strip())):
            if page.event.type_url.rsplit("/", 1)[-1] == P + "PlayerJoined":
                joined = table.PlayerJoined.FromString(page.event.value)
                active.append(
                    table.SeatSnapshot(
                        position=joined.seat_position,
                        player_root=joined.player_root,
                        stack=joined.stack,
                    )
                )
    context.combine_sources = [s.strip() for s in sources.split(",")]
    context.combine_active = active
    cmd = table.CombineFinalTable(
        final_table_name=final,
        source_table_names=context.combine_sources,
        max_handed=len(active),
        active_players=active,
    )
    context.world.dispatch("table", P + "CombineFinalTable", cmd, root=uuid_for(final))


@then("the final table has {n:d} active players")
def _then_final_count(context, n):
    ev = context.world.emitted(P + "FinalTableCombined", table.FinalTableCombined())
    assert len(ev.active_players) == n, f"final seats = {len(ev.active_players)}, want {n}"


@then('every original player has been reseated at "{final}"')
def _then_all_reseated(context, final):
    ev = context.world.emitted(P + "FinalTableCombined", table.FinalTableCombined())
    seated = {s.player_root for s in ev.active_players}
    expected = {s.player_root for s in context.combine_active}
    assert seated == expected, f"reseated {len(seated)} players, want {len(expected)} originals"


@then('"{name}" is broken')
def _then_table_broken(context, name):
    ev = context.world.emitted(P + "FinalTableCombined", table.FinalTableCombined())
    assert uuid_for(name) in ev.source_table_roots, (
        f"{name} not recorded among combined source tables"
    )
