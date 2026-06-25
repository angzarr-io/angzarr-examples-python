"""Tournament aggregate — cross-table coordination slice.

Implements the coordination commands/appliers of ``TournamentAggregateHandler``
on the angzarr-cli generated seam: the per-table active-player counts (fed by the
TableTournamentSaga forwarding PlayerJoined/PlayerLeft) and the TDA Rule 11D
short-table halt decision.

The tournament is the authority for cross-table coordination: it holds the
per-table counts in ``TournamentState.table_player_counts`` and decides when a
table is short enough to halt — deficit = (largest table's count) − (this table's
count); a deficit of 3 or more, signalled when the big blind would land on an empty
seat, emits ``TableHaltOrdered`` which the TournamentTableSaga fans out to the
table's ``HaltForBalancing``.

The cross-table coordination methods and the lifecycle foundation (create /
open-close registration / enroll) are ported. The remaining lifecycle (start /
blind levels / rebuys / eliminations / pause-resume / complete / payouts) is a
separate port, so dispatching those commands raises AttributeError (loud, not a
silent no-op).
"""

from __future__ import annotations

from typing import Optional

import angzarr_router_ffi as _az
from google.protobuf.timestamp_pb2 import Timestamp

from angzarr_poker._gen.io.angzarr.examples.v1 import tournament_pb2 as _trn
from angzarr_poker._gen.io.angzarr.v1 import types_pb2 as _t

# Rule 11D: a table 3 or more players short of the largest table halts.
_HALT_DEFICIT_THRESHOLD = 3


def _now() -> Timestamp:
    ts = Timestamp()
    ts.GetCurrentTime()
    return ts


def _book(*events) -> _t.EventBook:
    book = _t.EventBook()
    for ev in events:
        book.pages.add().event.CopyFrom(_az.pack(ev))
    return book


def _exists(state: _trn.TournamentState) -> bool:
    """A tournament exists once TournamentCreated has been folded."""
    return bool(state.tournament_id)


def _reject(code: str, message: str, **extras: str) -> _az.CodedError:
    """An invalid-argument business rejection carrying a stable code (and
    optional detail fields, e.g. lhs/rhs for a bound violation)."""
    return _az.CodedError(
        code=code, message=message, grpc=_az.GrpcCode.INVALID_ARGUMENT, extras=extras or None
    )


def _registration_open(state: _trn.TournamentState) -> bool:
    """Whether the tournament currently accepts enrollments. Open while the
    tournament is taking registrations OR running (late registration, TDA Rule
    30) — until registration is explicitly closed or the cutoff level is passed."""
    if state.registration_closed:
        return False
    if state.registration_cutoff_level > 0 and state.current_level > state.registration_cutoff_level:
        return False
    return state.status in (_trn.TOURNAMENT_REGISTRATION_OPEN, _trn.TOURNAMENT_RUNNING)


def _rebuy_denial_reason(state: _trn.TournamentState, player_root: bytes) -> Optional[str]:
    """Why a rebuy is denied (a stream event, not a coded reject), or None if it
    may proceed. Combines registration with rebuy config (TDA Rule 27): enabled,
    level cutoff, and per-player max."""
    if not player_root:
        return "player_root is required"
    reg = state.registered_players.get(player_root.hex())
    if reg is None:
        return "Player is not registered"
    if not state.HasField("rebuy_config") or not state.rebuy_config.enabled:
        return "Rebuys are not enabled"
    cfg = state.rebuy_config
    if cfg.rebuy_level_cutoff > 0 and state.current_level > cfg.rebuy_level_cutoff:
        return "Rebuy window is closed"
    if cfg.max_rebuys > 0 and reg.rebuys_used >= cfg.max_rebuys:
        return "Maximum rebuys reached"
    return None


class TournamentAggregate:
    """Coordination slice of ``TournamentAggregateHandler``."""

    # --- per-table counts (forwarded by TableTournamentSaga) ---

    def record_table_player_joined(
        self, cmd: _trn.RecordTablePlayerJoined, state: _trn.TournamentState, cctx: _az.CommandContext
    ) -> Optional[_t.EventBook]:
        return _book(
            _trn.TournamentTablePlayerJoined(
                table_root=cmd.table_root, player_root=cmd.player_root, recorded_at=_now()
            )
        )

    def record_table_player_left(
        self, cmd: _trn.RecordTablePlayerLeft, state: _trn.TournamentState, cctx: _az.CommandContext
    ) -> Optional[_t.EventBook]:
        return _book(
            _trn.TournamentTablePlayerLeft(
                table_root=cmd.table_root, player_root=cmd.player_root, recorded_at=_now()
            )
        )

    def apply_tournament_table_player_joined(
        self, state: _trn.TournamentState, event: _trn.TournamentTablePlayerJoined
    ) -> None:
        state.table_player_counts[event.table_root.hex()] += 1

    def apply_tournament_table_player_left(
        self, state: _trn.TournamentState, event: _trn.TournamentTablePlayerLeft
    ) -> None:
        key = event.table_root.hex()
        if state.table_player_counts.get(key, 0) > 0:
            state.table_player_counts[key] -= 1

    # --- Rule 11D halt/resume decision ---

    def record_table_bb_on_empty(
        self, cmd: _trn.RecordTableBBOnEmpty, state: _trn.TournamentState, cctx: _az.CommandContext
    ) -> Optional[_t.EventBook]:
        counts = state.table_player_counts
        if not counts:
            return None
        this_count = counts.get(cmd.table_root.hex(), 0)
        # Rule 11D second clause: compared to the table with the MOST players,
        # not the average across peers.
        deficit = max(counts.values()) - this_count
        if deficit >= _HALT_DEFICIT_THRESHOLD:
            return _book(
                _trn.TableHaltOrdered(
                    target_table_root=cmd.table_root, deficit=deficit, ordered_at=_now()
                )
            )
        return None

    def record_table_bb_on_empty_cleared(
        self,
        cmd: _trn.RecordTableBBOnEmptyCleared,
        state: _trn.TournamentState,
        cctx: _az.CommandContext,
    ) -> Optional[_t.EventBook]:
        return _book(
            _trn.TableResumeOrdered(target_table_root=cmd.table_root, ordered_at=_now())
        )

    def apply_table_halt_ordered(
        self, state: _trn.TournamentState, event: _trn.TableHaltOrdered
    ) -> None:
        # Order-of-record; no count change. (Re-arm tracking is added with EU-1184F.)
        pass

    def apply_table_resume_ordered(
        self, state: _trn.TournamentState, event: _trn.TableResumeOrdered
    ) -> None:
        pass

    # --- lifecycle: create / open-close registration / enroll ---

    def create_tournament(
        self, cmd: _trn.CreateTournament, state: _trn.TournamentState, cctx: _az.CommandContext
    ) -> Optional[_t.EventBook]:
        if _exists(state):
            raise _reject("TOURNAMENT_EXISTS", "Tournament already exists")
        if not cmd.name:
            raise _reject("NAME_REQUIRED", "name is required")
        if cmd.buy_in <= 0:
            raise _reject("BUY_IN_NOT_POSITIVE", "buy_in must be positive")
        if cmd.starting_stack <= 0:
            raise _reject("STARTING_STACK_NOT_POSITIVE", "starting_stack must be positive")
        if cmd.max_players < 2:
            raise _reject("MAX_PLAYERS_TOO_LOW", "max_players must be at least 2")
        if cmd.min_players < 2:
            raise _reject("MIN_PLAYERS_TOO_LOW", "min_players must be at least 2")
        if cmd.min_players > cmd.max_players:
            raise _reject(
                "MIN_PLAYERS_EXCEEDS_MAX",
                "min_players exceeds max_players",
                lhs=str(cmd.min_players),
                rhs=str(cmd.max_players),
            )
        return _book(
            _trn.TournamentCreated(
                name=cmd.name,
                game_variant=cmd.game_variant,
                buy_in=cmd.buy_in,
                starting_stack=cmd.starting_stack,
                max_players=cmd.max_players,
                min_players=cmd.min_players,
                scheduled_start=cmd.scheduled_start,
                rebuy_config=cmd.rebuy_config if cmd.HasField("rebuy_config") else None,
                addon_config=cmd.addon_config if cmd.HasField("addon_config") else None,
                blind_structure=cmd.blind_structure,
                created_at=_now(),
            )
        )

    def apply_tournament_created(
        self, state: _trn.TournamentState, event: _trn.TournamentCreated
    ) -> None:
        state.tournament_id = f"tournament_{event.name}"
        state.name = event.name
        state.game_variant = event.game_variant
        state.buy_in = event.buy_in
        state.starting_stack = event.starting_stack
        state.max_players = event.max_players
        state.min_players = event.min_players
        state.status = _trn.TOURNAMENT_CREATED
        state.current_level = 1
        if event.HasField("rebuy_config"):
            state.rebuy_config.CopyFrom(event.rebuy_config)
        del state.blind_structure[:]
        state.blind_structure.extend(event.blind_structure)
        del state.payout_structure[:]
        state.payout_structure.extend(event.payout_structure)
        state.registration_cutoff_level = event.registration_cutoff_level
        state.bounty_per_knockout = event.bounty_per_knockout

    def open_registration(
        self, cmd: _trn.OpenRegistration, state: _trn.TournamentState, cctx: _az.CommandContext
    ) -> Optional[_t.EventBook]:
        if not _exists(state):
            raise _reject("TOURNAMENT_NOT_FOUND", "Tournament does not exist")
        if state.status == _trn.TOURNAMENT_RUNNING:
            raise _reject("TOURNAMENT_RUNNING", "Cannot open registration on a running tournament")
        if state.status == _trn.TOURNAMENT_REGISTRATION_OPEN:
            raise _reject("REGISTRATION_ALREADY_OPEN", "Registration is already open")
        return _book(_trn.RegistrationOpened(opened_at=_now()))

    def apply_registration_opened(
        self, state: _trn.TournamentState, event: _trn.RegistrationOpened
    ) -> None:
        state.status = _trn.TOURNAMENT_REGISTRATION_OPEN
        state.registration_closed = False

    def close_registration(
        self, cmd: _trn.CloseRegistration, state: _trn.TournamentState, cctx: _az.CommandContext
    ) -> Optional[_t.EventBook]:
        if not _exists(state):
            raise _reject("TOURNAMENT_NOT_FOUND", "Tournament does not exist")
        if not _registration_open(state):
            raise _reject("REGISTRATION_NOT_OPEN", "Registration is not open")
        return _book(
            _trn.RegistrationClosed(
                total_registrations=len(state.registered_players), closed_at=_now()
            )
        )

    def apply_registration_closed(
        self, state: _trn.TournamentState, event: _trn.RegistrationClosed
    ) -> None:
        # No status change (the enum has no CLOSED value); the registration_closed
        # flag gates further enrollment while the status stays REGISTRATION_OPEN.
        state.registration_closed = True

    def enroll_player(
        self, cmd: _trn.EnrollPlayer, state: _trn.TournamentState, cctx: _az.CommandContext
    ) -> Optional[_t.EventBook]:
        if not _exists(state):
            raise _reject("TOURNAMENT_NOT_FOUND", "Tournament does not exist")
        # Guard failures are recorded as a rejection EVENT (not a coded reject) so
        # the reservation PM sees the enrollment outcome on the stream.
        reason = None
        if not cmd.player_root:
            reason = "a player identity is required"
        elif not _registration_open(state):
            reason = "Registration is not open"
        elif len(state.registered_players) >= state.max_players:
            reason = "Tournament is full"
        elif cmd.player_root.hex() in state.registered_players:
            reason = "Player is already registered"
        if reason is not None:
            return _book(
                _trn.TournamentEnrollmentRejected(
                    player_root=cmd.player_root,
                    reservation_id=cmd.reservation_id,
                    reason=reason,
                    rejected_at=_now(),
                )
            )
        return _book(
            _trn.TournamentPlayerEnrolled(
                player_root=cmd.player_root,
                reservation_id=cmd.reservation_id,
                fee_paid=state.buy_in,
                starting_stack=state.starting_stack,
                registration_number=len(state.registered_players) + 1,
                enrolled_at=_now(),
            )
        )

    def apply_tournament_player_enrolled(
        self, state: _trn.TournamentState, event: _trn.TournamentPlayerEnrolled
    ) -> None:
        reg = state.registered_players[event.player_root.hex()]
        reg.player_root = event.player_root
        reg.fee_paid = event.fee_paid
        reg.starting_stack = event.starting_stack
        reg.registered_at.CopyFrom(event.enrolled_at)
        state.total_prize_pool += event.fee_paid
        state.players_remaining += 1

    def apply_tournament_enrollment_rejected(
        self, state: _trn.TournamentState, event: _trn.TournamentEnrollmentRejected
    ) -> None:
        pass

    # --- lifecycle: start / blind levels / eliminate / pause-resume / rebuy ---

    def start_tournament(
        self, cmd: _trn.StartTournament, state: _trn.TournamentState, cctx: _az.CommandContext
    ) -> Optional[_t.EventBook]:
        if not _exists(state):
            raise _reject("TOURNAMENT_NOT_FOUND", "Tournament does not exist")
        if state.status != _trn.TOURNAMENT_REGISTRATION_OPEN:
            raise _reject("REGISTRATION_NOT_OPEN", "Registration is not open")
        if len(state.registered_players) < state.min_players:
            raise _reject("NOT_ENOUGH_PLAYERS", "Not enough players to start")
        return _book(
            _trn.TournamentStarted(
                total_players=len(state.registered_players),
                total_prize_pool=state.total_prize_pool,
                started_at=_now(),
            )
        )

    def apply_tournament_started(
        self, state: _trn.TournamentState, event: _trn.TournamentStarted
    ) -> None:
        state.status = _trn.TOURNAMENT_RUNNING
        state.current_level = 1
        state.players_remaining = event.total_players

    def advance_blind_level(
        self, cmd: _trn.AdvanceBlindLevel, state: _trn.TournamentState, cctx: _az.CommandContext
    ) -> Optional[_t.EventBook]:
        if not _exists(state):
            raise _reject("TOURNAMENT_NOT_FOUND", "Tournament does not exist")
        if state.status != _trn.TOURNAMENT_RUNNING:
            raise _reject("TOURNAMENT_NOT_RUNNING", "Tournament is not running")
        new_level = state.current_level + 1
        max_levels = len(state.blind_structure)
        # Advancing past the defined structure is refused so the operator decides
        # explicitly (extend the structure or end the tournament).
        if new_level > max_levels:
            raise _reject(
                "BLIND_STRUCTURE_EXHAUSTED",
                "blind structure is exhausted",
                current=str(state.current_level),
                max_value=str(max_levels),
            )
        level = state.blind_structure[new_level - 1]
        return _book(
            _trn.BlindLevelAdvanced(
                level=new_level,
                small_blind=level.small_blind,
                big_blind=level.big_blind,
                ante=level.ante,
                advanced_at=_now(),
            )
        )

    def apply_blind_level_advanced(
        self, state: _trn.TournamentState, event: _trn.BlindLevelAdvanced
    ) -> None:
        state.current_level = event.level

    def eliminate_player(
        self, cmd: _trn.EliminatePlayer, state: _trn.TournamentState, cctx: _az.CommandContext
    ) -> Optional[_t.EventBook]:
        if not _exists(state):
            raise _reject("TOURNAMENT_NOT_FOUND", "Tournament does not exist")
        if state.status != _trn.TOURNAMENT_RUNNING:
            raise _reject("TOURNAMENT_NOT_RUNNING", "Tournament is not running")
        if not cmd.player_root:
            raise _reject("PLAYER_ROOT_REQUIRED", "player_root is required")
        if cmd.player_root.hex() not in state.registered_players:
            raise _reject("PLAYER_NOT_REGISTERED", "Player is not registered")
        return _book(
            _trn.PlayerEliminated(
                player_root=cmd.player_root,
                hand_root=cmd.hand_root,
                finish_position=state.players_remaining,
                payout=0,
                eliminated_at=_now(),
            )
        )

    def apply_player_eliminated(
        self, state: _trn.TournamentState, event: _trn.PlayerEliminated
    ) -> None:
        key = event.player_root.hex()
        if key in state.registered_players:
            del state.registered_players[key]
        if state.players_remaining > 0:
            state.players_remaining -= 1

    def pause_tournament(
        self, cmd: _trn.PauseTournament, state: _trn.TournamentState, cctx: _az.CommandContext
    ) -> Optional[_t.EventBook]:
        if not _exists(state):
            raise _reject("TOURNAMENT_NOT_FOUND", "Tournament does not exist")
        if state.status == _trn.TOURNAMENT_PAUSED:
            raise _reject("TOURNAMENT_ALREADY_PAUSED", "Tournament is already paused")
        if state.status != _trn.TOURNAMENT_RUNNING:
            raise _reject("TOURNAMENT_NOT_RUNNING", "Tournament is not running")
        return _book(_trn.TournamentPaused(reason=cmd.reason, paused_at=_now()))

    def apply_tournament_paused(
        self, state: _trn.TournamentState, event: _trn.TournamentPaused
    ) -> None:
        state.status = _trn.TOURNAMENT_PAUSED

    def resume_tournament(
        self, cmd: _trn.ResumeTournament, state: _trn.TournamentState, cctx: _az.CommandContext
    ) -> Optional[_t.EventBook]:
        if not _exists(state):
            raise _reject("TOURNAMENT_NOT_FOUND", "Tournament does not exist")
        if state.status != _trn.TOURNAMENT_PAUSED:
            raise _reject("TOURNAMENT_NOT_PAUSED", "Tournament is not paused")
        return _book(_trn.TournamentResumed(resumed_at=_now()))

    def apply_tournament_resumed(
        self, state: _trn.TournamentState, event: _trn.TournamentResumed
    ) -> None:
        state.status = _trn.TOURNAMENT_RUNNING

    def apply_tournament_completed(
        self, state: _trn.TournamentState, event: _trn.TournamentCompleted
    ) -> None:
        state.status = _trn.TOURNAMENT_COMPLETED

    def process_rebuy(
        self, cmd: _trn.ProcessRebuy, state: _trn.TournamentState, cctx: _az.CommandContext
    ) -> Optional[_t.EventBook]:
        if not _exists(state):
            raise _reject("TOURNAMENT_NOT_FOUND", "Tournament does not exist")
        if state.status != _trn.TOURNAMENT_RUNNING:
            raise _reject("TOURNAMENT_NOT_RUNNING", "Tournament is not running")
        # A registered-player guard failure is a denial EVENT (the rebuy PM sees
        # the outcome on the stream), not a coded reject.
        reason = _rebuy_denial_reason(state, cmd.player_root)
        if reason is not None:
            return _book(
                _trn.RebuyDenied(
                    player_root=cmd.player_root,
                    reservation_id=cmd.reservation_id,
                    reason=reason,
                    denied_at=_now(),
                )
            )
        reg = state.registered_players[cmd.player_root.hex()]
        has_cfg = state.HasField("rebuy_config")
        return _book(
            _trn.RebuyProcessed(
                player_root=cmd.player_root,
                reservation_id=cmd.reservation_id,
                rebuy_cost=state.rebuy_config.rebuy_cost if has_cfg else state.buy_in,
                chips_added=state.rebuy_config.rebuy_chips if has_cfg else state.starting_stack,
                rebuy_count=reg.rebuys_used + 1,
                processed_at=_now(),
            )
        )

    def apply_rebuy_processed(
        self, state: _trn.TournamentState, event: _trn.RebuyProcessed
    ) -> None:
        # The rebuy fee grows the prize pool. Track the player's count only if
        # they are registered (a rebuy recorded for an unknown player still grows
        # the pool but adds no registration).
        state.total_prize_pool += event.rebuy_cost
        key = event.player_root.hex()
        if key in state.registered_players:
            state.registered_players[key].rebuys_used = event.rebuy_count

    def apply_rebuy_denied(
        self, state: _trn.TournamentState, event: _trn.RebuyDenied
    ) -> None:
        pass

    # --- completion + multi-place payout (RP-9 / WSOP §III) ---

    def complete_tournament(
        self, cmd: _trn.CompleteTournament, state: _trn.TournamentState, cctx: _az.CommandContext
    ) -> Optional[_t.EventBook]:
        if not _exists(state):
            raise _reject("TOURNAMENT_NOT_FOUND", "Tournament does not exist")
        if state.status == _trn.TOURNAMENT_COMPLETED:
            raise _reject("TOURNAMENT_ALREADY_COMPLETED", "Tournament is already completed")
        if state.status not in (_trn.TOURNAMENT_RUNNING, _trn.TOURNAMENT_PAUSED):
            raise _reject(
                "TOURNAMENT_NOT_RUNNING", "Tournament must be running or paused to complete"
            )
        results = []
        schedule = sorted(state.payout_structure, key=lambda p: p.position)
        if schedule:
            # The finishing order must cover every paid position (the caller
            # decides explicitly rather than silently skipping a payout).
            if len(cmd.finishing_order) < len(schedule):
                raise _reject(
                    "FINISHING_ORDER_SHORTER_THAN_PAYOUT_POSITIONS",
                    "finishing order is shorter than the paid positions",
                    got=str(len(cmd.finishing_order)),
                    bound=str(len(schedule)),
                )
            total = 0
            for p in schedule:
                payout = state.total_prize_pool * p.percentage // 100
                results.append(
                    _trn.TournamentResult(
                        position=p.position,
                        player_root=cmd.finishing_order[p.position - 1],
                        payout=payout,
                    )
                )
                total += payout
            # The schedule must distribute the whole pool (guards the chip ledger).
            if total != state.total_prize_pool:
                raise _reject(
                    "PAYOUTS_DO_NOT_SUM_TO_POOL",
                    "payouts do not sum to the prize pool",
                    got=str(total),
                    bound=str(state.total_prize_pool),
                )
        return _book(
            _trn.TournamentCompleted(
                winner_root=cmd.winner_root,
                total_prize_pool=state.total_prize_pool,
                results=results,
                completed_at=_now(),
            )
        )

    # --- bounty (TDA RP-22 / WSOP Rule 39) ---

    def award_bounty(
        self, cmd: _trn.AwardBounty, state: _trn.TournamentState, cctx: _az.CommandContext
    ) -> Optional[_t.EventBook]:
        if not _exists(state):
            raise _reject("TOURNAMENT_NOT_FOUND", "Tournament does not exist")
        # The bounty paid per knockout is the configured amount; the caller names
        # the eliminator + knocked-out player (and the tiebreak when a last-two
        # simultaneous bust was resolved by pre-hand stack).
        return _book(
            _trn.BountyAwarded(
                eliminator_root=cmd.eliminator_root,
                knocked_out_root=cmd.knocked_out_root,
                amount=state.bounty_per_knockout,
                tiebreak_reason=cmd.tiebreak_reason,
                awarded_at=_now(),
            )
        )

    def apply_bounty_awarded(
        self, state: _trn.TournamentState, event: _trn.BountyAwarded
    ) -> None:
        state.bounty_totals[event.eliminator_root.hex()] += event.amount
