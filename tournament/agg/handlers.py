"""Tournament aggregate - rich domain model."""

from dataclasses import dataclass, field

from google.protobuf.any_pb2 import Any as ProtoAny

from angzarr_client import applies, command_handler, handles, now
from .errors import (
    FinishingOrderShorterThanPayoutPositions,
    PayoutsDoNotSumToPool,
)  # noqa: E501
from .errors import (
    BlindStructureExhausted,
    BuyInMustBePositive,
    CannotOpenRegistrationRunning,
    MaxPlayersTooFew,
    MinPlayersExceedsMax,
    MinPlayersTooFew,
    NameRequired,
    NotEnoughPlayersToStart,
    PlayerNotRegistered,
    PlayerRootRequired,
    RegistrationAlreadyOpen,
    RegistrationNotOpen,
    StartingStackMustBePositive,
    TournamentAlreadyCompleted,
    TournamentAlreadyExists,
    TournamentAlreadyPaused,
    TournamentNotFound,
    TournamentNotPaused,
    TournamentNotRunning,
    TournamentNotRunningOrPaused,
)
from angzarr_client.proto.angzarr import types_pb2 as types
from angzarr_client.proto.examples import tournament_pb2 as tournament


@dataclass
class _PlayerRegistration:
    """Player registration record in tournament."""

    player_root: bytes = b""
    fee_paid: int = 0
    starting_stack: int = 0
    rebuys_used: int = 0
    addon_taken: bool = False
    table_assignment: int = 0
    seat_assignment: int = 0


@dataclass
class _TournamentState:
    """Internal state representation."""

    tournament_id: str = ""
    name: str = ""
    game_variant: int = 0
    status: int = 0
    buy_in: int = 0
    starting_stack: int = 0
    max_players: int = 0
    min_players: int = 0
    rebuy_config: tournament.RebuyConfig | None = None
    blind_structure: list = field(default_factory=list)
    current_level: int = 1
    registered_players: dict[str, _PlayerRegistration] = field(default_factory=dict)
    players_remaining: int = 0
    total_prize_pool: int = 0
    # Registration is tracked independently of tournament status so that
    # late registration (TDA Rule 30) can keep the gate open into a
    # Running tournament until either the configured cutoff level or
    # an explicit CloseRegistration.
    registration_open: bool = False
    registration_cutoff_level: int = 0  # 0 = no auto-close
    payout_structure: list = field(default_factory=list)  # PayoutPosition entries
    # Hand-for-hand bookkeeping (TDA Rule 12).
    hand_for_hand: bool = False
    hand_for_hand_pending_tables: set = field(default_factory=set)
    # Active table set for the current bubble — kept across rounds so
    # the apply_hand_for_hand_round_complete handler can reseed
    # hand_for_hand_pending_tables from it. Cleared on HandForHandEnded.
    hand_for_hand_active_tables: set = field(default_factory=set)
    hand_for_hand_round: int = 0
    # TDA Rule 71D / WSOP Rule 114 — total chips in play tracked
    # explicitly so DQ/no-show removals are observable.
    total_chips_in_play: int = 0
    # TDA Rule 71 — active per-player penalty register.
    active_penalties: dict[str, int] = field(default_factory=dict)
    # Per-player chip stacks tracked at the tournament level
    # (separate from per-table tracking). Used by DisqualifyPlayer.
    player_stacks: dict[str, int] = field(default_factory=dict)
    # Per-player chip inventory by denomination (TDA Rule 24A).
    # Keyed by player_root_hex, then by denomination → count of chips.
    # Seeded by tests for chip-race scenarios; used by AdvanceBlindLevel
    # in chip-race mode to compute per-player race awards.
    player_chip_inventories: dict[str, dict[int, int]] = field(default_factory=dict)
    # TDA RP-8B/8C — per-level clock countdown. Seeded by saga or by
    # tests; decremented by HandForHandHandRecorded events.
    level_seconds_remaining: int = 0
    # TDA RP-8A — simultaneous-bust groups recorded during H4H play.
    # Each entry is a frozenset of player_root_hex strings; consumed by
    # CompleteTournament to split the next paid position(s).
    simultaneous_bust_groups: list = field(default_factory=list)


_APPLIER_REGISTRY: list[tuple[type, str]] = []


@command_handler(domain="tournament", state=_TournamentState)
class Tournament:
    """Tournament aggregate with event sourcing."""

    def __init__(self, event_book: types.EventBook | None = None) -> None:
        self._state = _TournamentState()
        self._events = types.EventBook()
        if event_book is not None:
            for page in event_book.pages:
                new_page = types.EventPage()
                new_page.CopyFrom(page)
                self._events.pages.append(new_page)
                if page.HasField("event"):
                    self._apply_any(page.event, self._state)

    # --- Compatibility helpers (test path) ---

    def _get_state(self) -> _TournamentState:
        return self._state

    def event_book(self) -> types.EventBook:
        return self._events

    def _emit(self, event) -> None:
        any_msg = ProtoAny()
        any_msg.Pack(event, type_url_prefix="type.googleapis.com/")
        page = types.EventPage(
            event=any_msg,
            header=types.PageHeader(sequence=len(self._events.pages)),
        )
        self._events.pages.append(page)
        self._apply_any(any_msg, self._state)

    def _apply_any(self, event_any: ProtoAny, state: _TournamentState) -> None:
        for event_type, method_name in _APPLIER_REGISTRY:
            expected = f"type.googleapis.com/{event_type.DESCRIPTOR.full_name}"
            if event_any.type_url == expected:
                evt = event_type()
                event_any.Unpack(evt)
                getattr(self, method_name)(state, evt)
                return

    def _router_bind(self, state):
        saved = self._state
        self._state = state
        return saved

    # --- Event appliers ---

    @applies(tournament.TournamentCreated)
    def apply_created(
        self, state: _TournamentState, event: tournament.TournamentCreated
    ) -> None:
        state.tournament_id = f"tournament_{event.name}"
        state.name = event.name
        state.game_variant = event.game_variant
        state.status = tournament.TournamentStatus.TOURNAMENT_CREATED
        state.buy_in = event.buy_in
        state.starting_stack = event.starting_stack
        state.max_players = event.max_players
        state.min_players = event.min_players
        state.rebuy_config = (
            event.rebuy_config if event.HasField("rebuy_config") else None
        )
        state.blind_structure = list(event.blind_structure)
        state.current_level = 1
        state.registration_cutoff_level = event.registration_cutoff_level
        state.payout_structure = list(event.payout_structure)

    @applies(tournament.RegistrationOpened)
    def apply_registration_opened(
        self, state: _TournamentState, _event: tournament.RegistrationOpened
    ) -> None:
        # Registration_open is its own dimension — separate from status
        # so the gate can stay open into a Running tournament for late
        # registration (TDA Rule 30).
        state.registration_open = True
        if state.status == tournament.TournamentStatus.TOURNAMENT_CREATED:
            state.status = tournament.TournamentStatus.TOURNAMENT_REGISTRATION_OPEN

    @applies(tournament.RegistrationClosed)
    def apply_registration_closed(
        self, state: _TournamentState, _event: tournament.RegistrationClosed
    ) -> None:
        state.registration_open = False

    @applies(tournament.TournamentPlayerEnrolled)
    def apply_player_enrolled(
        self, state: _TournamentState, event: tournament.TournamentPlayerEnrolled
    ) -> None:
        player_root_hex = event.player_root.hex()
        state.registered_players[player_root_hex] = _PlayerRegistration(
            player_root=event.player_root,
            fee_paid=event.fee_paid,
            starting_stack=event.starting_stack,
        )
        state.total_prize_pool += event.fee_paid
        state.players_remaining = len(state.registered_players)
        # Default chip inventory: starting_stack denominated entirely in
        # 25-stake chips. Lets the chip-race math (TDA Rule 24A, Batch 9)
        # have something to convert when AdvanceBlindLevel arrives with
        # ``retire_denomination=25, new_denomination=100`` (the EA-0011
        # cluster scenario). Tests that need a different denomination
        # breakdown can still overwrite this entry directly via
        # ``state.player_chip_inventories`` (see Batch 9 unit step defs).
        if player_root_hex not in state.player_chip_inventories:
            state.player_chip_inventories[player_root_hex] = {
                25: event.starting_stack // 25,
            }
            state.total_chips_in_play += event.starting_stack

    @applies(tournament.TournamentEnrollmentRejected)
    def apply_enrollment_rejected(
        self, state: _TournamentState, _event: tournament.TournamentEnrollmentRejected
    ) -> None:
        pass

    @applies(tournament.RebuyProcessed)
    def apply_rebuy_processed(
        self, state: _TournamentState, event: tournament.RebuyProcessed
    ) -> None:
        player_root_hex = event.player_root.hex()
        registration = state.registered_players.get(player_root_hex)
        if registration is not None:
            registration.rebuys_used = event.rebuy_count
        state.total_prize_pool += event.rebuy_cost

    @applies(tournament.RebuyDenied)
    def apply_rebuy_denied(
        self, state: _TournamentState, _event: tournament.RebuyDenied
    ) -> None:
        pass

    @applies(tournament.BlindLevelAdvanced)
    def apply_blind_advanced(
        self, state: _TournamentState, event: tournament.BlindLevelAdvanced
    ) -> None:
        state.current_level = event.level
        # Auto-close registration once we pass the configured cutoff.
        if (
            state.registration_cutoff_level > 0
            and event.level > state.registration_cutoff_level
            and state.registration_open
        ):
            state.registration_open = False

    @applies(tournament.PlayerEliminated)
    def apply_player_eliminated(
        self, state: _TournamentState, event: tournament.PlayerEliminated
    ) -> None:
        player_root_hex = event.player_root.hex()
        state.registered_players.pop(player_root_hex, None)
        state.players_remaining = len(state.registered_players)

    @applies(tournament.TournamentPaused)
    def apply_paused(
        self, state: _TournamentState, _event: tournament.TournamentPaused
    ) -> None:
        state.status = tournament.TournamentStatus.TOURNAMENT_PAUSED

    @applies(tournament.TournamentResumed)
    def apply_resumed(
        self, state: _TournamentState, _event: tournament.TournamentResumed
    ) -> None:
        state.status = tournament.TournamentStatus.TOURNAMENT_RUNNING

    @applies(tournament.TournamentStarted)
    def apply_started(
        self, state: _TournamentState, _event: tournament.TournamentStarted
    ) -> None:
        state.status = tournament.TournamentStatus.TOURNAMENT_RUNNING

    @applies(tournament.TournamentCompleted)
    def apply_completed(
        self, state: _TournamentState, _event: tournament.TournamentCompleted
    ) -> None:
        state.status = tournament.TournamentStatus.TOURNAMENT_COMPLETED

    # --- State accessors ---

    @property
    def exists(self) -> bool:
        return bool(self._state.tournament_id)

    @property
    def is_registration_open(self) -> bool:
        return self._state.registration_open

    @property
    def is_running(self) -> bool:
        return self._state.status == tournament.TournamentStatus.TOURNAMENT_RUNNING

    @property
    def status(self) -> int:
        return self._state.status

    @property
    def buy_in(self) -> int:
        return self._state.buy_in

    @property
    def starting_stack(self) -> int:
        return self._state.starting_stack

    @property
    def max_players(self) -> int:
        return self._state.max_players

    @property
    def min_players(self) -> int:
        return self._state.min_players

    @property
    def registered_players(self) -> dict:
        return self._state.registered_players

    @property
    def players_remaining(self) -> int:
        return self._state.players_remaining

    @property
    def total_prize_pool(self) -> int:
        return self._state.total_prize_pool

    @property
    def current_level(self) -> int:
        return self._state.current_level

    @property
    def rebuy_config(self):
        return self._state.rebuy_config

    @property
    def blind_structure(self) -> list:
        return self._state.blind_structure

    def has_capacity(self) -> bool:
        return len(self._state.registered_players) < self._state.max_players

    def is_player_registered(self, player_root_hex: str) -> bool:
        return player_root_hex in self._state.registered_players

    def can_rebuy(self, player_root_hex: str) -> bool:
        return self._rebuy_denial_reason(player_root_hex) is None

    def _rebuy_denial_reason(self, player_root_hex: str) -> str | None:
        s = self._state
        if s.status != tournament.TournamentStatus.TOURNAMENT_RUNNING:
            return "Tournament is not running"
        if s.rebuy_config is None or not s.rebuy_config.enabled:
            return "Rebuys are not enabled"
        if (
            s.rebuy_config.rebuy_level_cutoff > 0
            and s.current_level > s.rebuy_config.rebuy_level_cutoff
        ):
            return "Rebuy window is closed"
        registration = s.registered_players.get(player_root_hex)
        if registration is not None:
            if (
                s.rebuy_config.max_rebuys > 0
                and registration.rebuys_used >= s.rebuy_config.max_rebuys
            ):
                return "Maximum rebuys reached"
        return None

    # --- Command handlers ---

    @handles(tournament.CreateTournament)
    def handle_create_tournament(
        self,
        cmd: tournament.CreateTournament,
        state: _TournamentState | None = None,
        seq: int | None = None,
    ) -> tournament.TournamentCreated:
        """Create a new tournament."""
        router_mode = state is not None
        saved = self._router_bind(state) if router_mode else None
        try:
            if self.exists:
                raise TournamentAlreadyExists()
            if not cmd.name:
                raise NameRequired()
            if cmd.buy_in <= 0:
                raise BuyInMustBePositive(value=cmd.buy_in)
            if cmd.starting_stack <= 0:
                raise StartingStackMustBePositive(value=cmd.starting_stack)
            if cmd.max_players < 2:
                raise MaxPlayersTooFew(got=cmd.max_players)
            if cmd.min_players < 2:
                raise MinPlayersTooFew(got=cmd.min_players)
            if cmd.min_players > cmd.max_players:
                raise MinPlayersExceedsMax(lhs=cmd.min_players, rhs=cmd.max_players)

            event = tournament.TournamentCreated(
                name=cmd.name,
                game_variant=cmd.game_variant,
                buy_in=cmd.buy_in,
                starting_stack=cmd.starting_stack,
                max_players=cmd.max_players,
                min_players=cmd.min_players,
                scheduled_start=cmd.scheduled_start,
                rebuy_config=(
                    cmd.rebuy_config if cmd.HasField("rebuy_config") else None
                ),
                addon_config=(
                    cmd.addon_config if cmd.HasField("addon_config") else None
                ),
                blind_structure=cmd.blind_structure,
                created_at=now(),
            )
            if not router_mode:
                self._emit(event)
            return event
        finally:
            if router_mode:
                self._state = saved

    @handles(tournament.OpenRegistration)
    def handle_open_registration(
        self,
        cmd: tournament.OpenRegistration,
        state: _TournamentState | None = None,
        seq: int | None = None,
    ) -> tournament.RegistrationOpened:
        """Open registration for the tournament."""
        router_mode = state is not None
        saved = self._router_bind(state) if router_mode else None
        try:
            if not self.exists:
                raise TournamentNotFound()
            if self.is_running:
                raise CannotOpenRegistrationRunning()
            if self.is_registration_open:
                raise RegistrationAlreadyOpen()
            event = tournament.RegistrationOpened(opened_at=now())
            if not router_mode:
                self._emit(event)
            return event
        finally:
            if router_mode:
                self._state = saved

    @handles(tournament.CloseRegistration)
    def handle_close_registration(
        self,
        cmd: tournament.CloseRegistration,
        state: _TournamentState | None = None,
        seq: int | None = None,
    ) -> tournament.RegistrationClosed:
        """Close registration for the tournament."""
        router_mode = state is not None
        saved = self._router_bind(state) if router_mode else None
        try:
            if not self.exists:
                raise TournamentNotFound()
            if not self.is_registration_open:
                raise RegistrationNotOpen()
            event = tournament.RegistrationClosed(
                total_registrations=len(self.registered_players),
                closed_at=now(),
            )
            if not router_mode:
                self._emit(event)
            return event
        finally:
            if router_mode:
                self._state = saved

    @handles(tournament.EnrollPlayer)
    def handle_enroll_player(
        self,
        cmd: tournament.EnrollPlayer,
        state: _TournamentState | None = None,
        seq: int | None = None,
    ) -> tournament.TournamentPlayerEnrolled | tournament.TournamentEnrollmentRejected:
        """Enroll a player in the tournament."""
        router_mode = state is not None
        saved = self._router_bind(state) if router_mode else None
        try:
            if not self.exists:
                raise TournamentNotFound()

            rejection_reason = None
            if not cmd.player_root:
                rejection_reason = "player_root is required"
            elif not self.is_registration_open:
                rejection_reason = "Registration is not open"
            elif not self.has_capacity():
                rejection_reason = "Tournament is full"
            elif self.is_player_registered(cmd.player_root.hex()):
                rejection_reason = "Player is already registered"

            if rejection_reason is not None:
                event = tournament.TournamentEnrollmentRejected(
                    player_root=cmd.player_root,
                    reservation_id=cmd.reservation_id,
                    reason=rejection_reason,
                    rejected_at=now(),
                )
                if not router_mode:
                    self._emit(event)
                return event

            event = tournament.TournamentPlayerEnrolled(
                player_root=cmd.player_root,
                reservation_id=cmd.reservation_id,
                fee_paid=self.buy_in,
                starting_stack=self.starting_stack,
                registration_number=len(self.registered_players) + 1,
                enrolled_at=now(),
            )
            if not router_mode:
                self._emit(event)
            return event
        finally:
            if router_mode:
                self._state = saved

    @handles(tournament.ProcessRebuy)
    def handle_process_rebuy(
        self,
        cmd: tournament.ProcessRebuy,
        state: _TournamentState | None = None,
        seq: int | None = None,
    ) -> tournament.RebuyProcessed | tournament.RebuyDenied:
        """Process a rebuy request."""
        router_mode = state is not None
        saved = self._router_bind(state) if router_mode else None
        try:
            if not self.exists:
                raise TournamentNotFound()
            if not self.is_running:
                raise TournamentNotRunning()

            rejection_reason = None
            if not cmd.player_root:
                rejection_reason = "player_root is required"
            elif not self.is_player_registered(cmd.player_root.hex()):
                rejection_reason = "Player is not registered"
            elif not self.can_rebuy(cmd.player_root.hex()):
                rejection_reason = self._rebuy_denial_reason(cmd.player_root.hex())

            if rejection_reason is not None:
                event = tournament.RebuyDenied(
                    player_root=cmd.player_root,
                    reason=rejection_reason,
                    denied_at=now(),
                )
                if not router_mode:
                    self._emit(event)
                return event

            s = self._state
            registration = s.registered_players.get(cmd.player_root.hex())
            rebuy_count = (registration.rebuys_used + 1) if registration else 1
            rebuy_cost = s.rebuy_config.rebuy_cost if s.rebuy_config else s.buy_in
            chips_added = (
                s.rebuy_config.rebuy_chips if s.rebuy_config else s.starting_stack
            )

            event = tournament.RebuyProcessed(
                player_root=cmd.player_root,
                rebuy_count=rebuy_count,
                rebuy_cost=rebuy_cost,
                chips_added=chips_added,
                processed_at=now(),
            )
            if not router_mode:
                self._emit(event)
            return event
        finally:
            if router_mode:
                self._state = saved

    @handles(tournament.AdvanceBlindLevel)
    def handle_advance_blind_level(
        self,
        cmd: tournament.AdvanceBlindLevel,
        state: _TournamentState | None = None,
        seq: int | None = None,
    ) -> tournament.BlindLevelAdvanced | tournament.ColorUpCompleted:
        """Advance the blind level.

        When ``cmd.retire_denomination`` is non-zero, the advance also
        triggers a chip race (TDA Rule 24A): retired-denomination chips
        are converted to ``cmd.new_denomination`` chips, with the
        single-chip rescue clause guaranteeing no player is eliminated
        by the race. In chip-race mode the handler emits both
        ``BlindLevelAdvanced`` and ``ColorUpCompleted``; the
        ``ColorUpCompleted`` event is returned so callers can inspect
        the per-player awards and conservation deltas.
        """
        router_mode = state is not None
        saved = self._router_bind(state) if router_mode else None
        try:
            if not self.exists:
                raise TournamentNotFound()
            if not self.is_running:
                raise TournamentNotRunning()

            s = self._state
            chip_race = cmd.retire_denomination > 0 and cmd.new_denomination > 0
            # Reject when the structure is exhausted (or empty). Emitting a
            # BlindLevelAdvanced past the declared structure would write a
            # lie into the event log; surface the decision to the operator
            # instead. Chip-race-only commands (no structural advance) are
            # not supported in this handler — operators should use ColorUp
            # standalone if they want to color-up between levels.
            max_defined_level = len(s.blind_structure)
            new_level = s.current_level + 1
            if new_level > max_defined_level and not chip_race:
                raise BlindStructureExhausted(
                    current=s.current_level,
                    max_value=max_defined_level,
                )

            blind_event = None
            if new_level <= max_defined_level:
                level_config = s.blind_structure[new_level - 1]
                blind_event = tournament.BlindLevelAdvanced(
                    level=new_level,
                    small_blind=level_config.small_blind,
                    big_blind=level_config.big_blind,
                    ante=level_config.ante,
                    advanced_at=now(),
                )
                if not router_mode:
                    self._emit(blind_event)

            if not chip_race:
                return blind_event

            color_event = self._compute_chip_race(
                cmd.retire_denomination, cmd.new_denomination
            )
            if not router_mode:
                self._emit(color_event)
            return color_event
        finally:
            if router_mode:
                self._state = saved

    def _compute_chip_race(
        self, retire_denom: int, new_denom: int
    ) -> tournament.ColorUpCompleted:
        """Compute per-player chip-race awards and conservation deltas.

        TDA Rule 24A: each player's retired-denomination chips convert
        outright as far as full new-denom chips go. The leftover
        remainders (each below ``new_denom``) form a global pool; the
        number of new-denom chips drawn from that pool equals
        ``total_remainder // new_denom``. Each contender (a player with
        any remainder) wins at most one chip; the residual pool value
        ``total_remainder % new_denom`` is removed without compensation
        (Rule 24C). The single-chip rescue clause (Rule 24A) protects
        any player left with zero chips after the race by awarding one
        chip of the new denomination — this is the only legal
        chip-creation path in the race.
        """
        s = self._state

        per_player: list[tuple[str, int, int]] = []
        total_remainder = 0
        for player_hex in sorted(s.player_chip_inventories.keys()):
            inventory = s.player_chip_inventories[player_hex]
            retire_count = inventory.get(retire_denom, 0)
            value_in_retired = retire_count * retire_denom
            full_new_chips = value_in_retired // new_denom
            remainder = value_in_retired - full_new_chips * new_denom
            per_player.append((player_hex, full_new_chips, remainder))
            total_remainder += remainder

        race_chips_to_award = total_remainder // new_denom
        chips_removed_by_race = total_remainder - race_chips_to_award * new_denom

        # Contenders: anyone with a non-zero remainder. RP-14-style
        # deterministic ordering for the unit test: sort by (remainder
        # desc, player_hex asc) and award one chip to the top N. Ties
        # resolved by hex ordering, which is deterministic.
        contenders = sorted(
            (
                (remainder, player_hex)
                for player_hex, _full, remainder in per_player
                if remainder > 0
            ),
            key=lambda x: (-x[0], x[1]),
        )
        race_winners = {hx for _r, hx in contenders[:race_chips_to_award]}

        awards: list[tournament.ChipRaceAward] = []
        chips_added_by_rescue = 0
        for player_hex, full_new_chips, _remainder in per_player:
            chips_won = full_new_chips
            if player_hex in race_winners:
                chips_won += 1

            non_retired_value = sum(
                count * denom
                for denom, count in s.player_chip_inventories[player_hex].items()
                if denom != retire_denom
            )
            stake_after = non_retired_value + chips_won * new_denom
            rescued = False
            if stake_after == 0:
                chips_won += 1
                rescued = True
                chips_added_by_rescue += new_denom

            awards.append(
                tournament.ChipRaceAward(
                    player_root=bytes.fromhex(player_hex),
                    chips_won=chips_won,
                    rescued=rescued,
                )
            )

        return tournament.ColorUpCompleted(
            retired_denomination=retire_denom,
            new_denomination=new_denom,
            per_player_awards=awards,
            chips_added_by_rescue=chips_added_by_rescue,
            chips_removed_by_race=chips_removed_by_race,
            completed_at=now(),
        )

    @handles(tournament.EliminatePlayer)
    def handle_eliminate_player(
        self,
        cmd: tournament.EliminatePlayer,
        state: _TournamentState | None = None,
        seq: int | None = None,
    ) -> tournament.PlayerEliminated:
        """Eliminate a player from the tournament."""
        router_mode = state is not None
        saved = self._router_bind(state) if router_mode else None
        try:
            if not self.exists:
                raise TournamentNotFound()
            if not self.is_running:
                raise TournamentNotRunning()
            if not cmd.player_root:
                raise PlayerRootRequired()
            if not self.is_player_registered(cmd.player_root.hex()):
                raise PlayerNotRegistered(player_root_hex=cmd.player_root.hex())

            event = tournament.PlayerEliminated(
                player_root=cmd.player_root,
                hand_root=cmd.hand_root,
                finish_position=self.players_remaining,
                payout=0,
                eliminated_at=now(),
            )
            # TDA Rule 12 — bubble break ends hand-for-hand play. The
            # next elimination after entering H4H is by definition the
            # bubble; emit HandForHandEnded alongside the elimination so
            # downstream tables can resume normal-pace hands.
            extras = []
            if self._state.hand_for_hand:
                extras.append(tournament.HandForHandEnded(ended_at=now()))
            if not router_mode:
                self._emit(event)
                for extra in extras:
                    self._emit(extra)
            if extras:
                return [event, *extras]
            return event
        finally:
            if router_mode:
                self._state = saved

    @handles(tournament.PauseTournament)
    def handle_pause_tournament(
        self,
        cmd: tournament.PauseTournament,
        state: _TournamentState | None = None,
        seq: int | None = None,
    ) -> tournament.TournamentPaused:
        """Pause the tournament."""
        router_mode = state is not None
        saved = self._router_bind(state) if router_mode else None
        try:
            if not self.exists:
                raise TournamentNotFound()
            if self.status == tournament.TournamentStatus.TOURNAMENT_PAUSED:
                raise TournamentAlreadyPaused()
            if not self.is_running:
                raise TournamentNotRunning()
            event = tournament.TournamentPaused(reason=cmd.reason, paused_at=now())
            if not router_mode:
                self._emit(event)
            return event
        finally:
            if router_mode:
                self._state = saved

    @handles(tournament.ResumeTournament)
    def handle_resume_tournament(
        self,
        cmd: tournament.ResumeTournament,
        state: _TournamentState | None = None,
        seq: int | None = None,
    ) -> tournament.TournamentResumed:
        """Resume a paused or bagged tournament. WSOP Rule 122 allows
        resume from TOURNAMENT_BAGGED for next-day continuation."""
        router_mode = state is not None
        saved = self._router_bind(state) if router_mode else None
        try:
            if not self.exists:
                raise TournamentNotFound()
            if self.status not in (
                tournament.TournamentStatus.TOURNAMENT_PAUSED,
                tournament.TournamentStatus.TOURNAMENT_BAGGED,
            ):
                raise TournamentNotPaused()
            event = tournament.TournamentResumed(resumed_at=now())
            if not router_mode:
                self._emit(event)
            return event
        finally:
            if router_mode:
                self._state = saved

    @handles(tournament.StartTournament)
    def handle_start_tournament(
        self,
        cmd: tournament.StartTournament,
        state: _TournamentState | None = None,
        seq: int | None = None,
    ) -> tournament.TournamentStarted:
        """Start the tournament."""
        router_mode = state is not None
        saved = self._router_bind(state) if router_mode else None
        try:
            if not self.exists:
                raise TournamentNotFound()
            # Start requires the tournament to have reached the
            # registration-open phase. Operators may explicitly
            # CloseRegistration before StartTournament (this happens in
            # EA-0008), so we check the lifecycle stage (status) rather
            # than ``registration_open`` — late registration (TDA Rule
            # 30) decouples those concepts.
            if self.status != tournament.TournamentStatus.TOURNAMENT_REGISTRATION_OPEN:
                raise RegistrationNotOpen()
            if len(self.registered_players) < self.min_players:
                raise NotEnoughPlayersToStart(
                    requested=self.min_players,
                    available=len(self.registered_players),
                )
            event = tournament.TournamentStarted(
                total_players=len(self.registered_players),
                total_prize_pool=self.total_prize_pool,
                started_at=now(),
            )
            if not router_mode:
                self._emit(event)
            return event
        finally:
            if router_mode:
                self._state = saved

    @handles(tournament.CompleteTournament)
    def handle_complete_tournament(
        self,
        cmd: tournament.CompleteTournament,
        state: _TournamentState | None = None,
        seq: int | None = None,
    ) -> tournament.TournamentCompleted:
        """Close the tournament and record the winner.

        Typically issued once only one registered player remains, but the
        aggregate allows completion from Running / Paused — completion is
        a terminal transition and gets out of the way of any remaining
        cleanup a saga or PM wants to do.
        """
        router_mode = state is not None
        saved = self._router_bind(state) if router_mode else None
        try:
            if not self.exists:
                raise TournamentNotFound()
            if self.status == tournament.TournamentStatus.TOURNAMENT_COMPLETED:
                raise TournamentAlreadyCompleted()
            if self.status not in (
                tournament.TournamentStatus.TOURNAMENT_RUNNING,
                tournament.TournamentStatus.TOURNAMENT_PAUSED,
            ):
                raise TournamentNotRunningOrPaused()

            results = []
            payout_structure = self._state.payout_structure
            if payout_structure:
                if len(cmd.finishing_order) < len(payout_structure):
                    raise FinishingOrderShorterThanPayoutPositions(
                        got=len(cmd.finishing_order),
                        bound=len(payout_structure),
                    )
                pool = self.total_prize_pool
                payouts = [pool * pp.percentage // 100 for pp in payout_structure]
                if sum(payouts) != pool:
                    raise PayoutsDoNotSumToPool(got=sum(payouts), bound=pool)
                positions = [pp.position for pp in payout_structure]
                payout_for_position = {
                    pp.position: p for pp, p in zip(payout_structure, payouts)
                }

                # Default position-by-finish-order assignment.
                position_for: dict[str, int] = {}
                for i, root in enumerate(cmd.finishing_order):
                    if i < len(positions):
                        position_for[root.hex()] = positions[i]

                # WSOP Rule 126b — same-table simultaneous busts: the
                # tiebreak (pre-hand stack) preserves the original
                # position assignment but stamps a tiebreak_reason on
                # the awarded result.
                tiebreak_reason_for: dict[str, str] = {}
                same_table_groups = getattr(
                    self._state, "simultaneous_bust_orderings", []
                )
                for ordered in same_table_groups:
                    if any(h in position_for for h in ordered):
                        # Highest-stack member keeps their position;
                        # lower members are demoted out of the paid set.
                        for h in ordered[1:]:
                            position_for.pop(h, None)
                        head = ordered[0]
                        if head in position_for:
                            tiebreak_reason_for[head] = "PRE_HAND_STACK"

                # TDA RP-8A — different-table simultaneous busters share
                # the worst-paid position any of them was assigned.
                for group in self._state.simultaneous_bust_groups:
                    paid_in_group = [
                        position_for[h] for h in group if h in position_for
                    ]
                    if paid_in_group:
                        shared_pos = max(paid_in_group)
                        for h in group:
                            position_for[h] = shared_pos

                count_at_pos: dict[int, int] = {}
                for pos in position_for.values():
                    count_at_pos[pos] = count_at_pos.get(pos, 0) + 1

                for root in cmd.finishing_order:
                    h = root.hex()
                    if h not in position_for:
                        continue
                    pos = position_for[h]
                    payout = payout_for_position[pos] // count_at_pos[pos]
                    results.append(
                        tournament.TournamentResult(
                            position=pos,
                            player_root=root,
                            payout=payout,
                            tiebreak_reason=tiebreak_reason_for.get(h, ""),
                        )
                    )

            event = tournament.TournamentCompleted(
                winner_root=cmd.winner_root,
                total_prize_pool=self.total_prize_pool,
                completed_at=now(),
            )
            event.results.extend(results)
            if not router_mode:
                self._emit(event)
            return event
        finally:
            if router_mode:
                self._state = saved

    # ---- Color-up (TDA Rule 28) -----------------------------------------

    @handles(tournament.ColorUp)
    def handle_color_up(
        self,
        cmd: tournament.ColorUp,
        state: _TournamentState | None = None,
        seq: int | None = None,
    ) -> tournament.ColorUpCompleted:
        """Retire a low-denomination chip and replace with a higher one.

        Operator command issued between blind levels. The aggregate just
        records the event; per-player chip math is the responsibility of
        a downstream saga that touches every active table.
        """
        router_mode = state is not None
        saved = self._router_bind(state) if router_mode else None
        try:
            if not self.exists:
                raise TournamentNotFound()
            if not self.is_running:
                raise TournamentNotRunning()
            event = tournament.ColorUpCompleted(
                retired_denomination=cmd.retire_denomination,
                new_denomination=cmd.new_denomination,
                completed_at=now(),
            )
            if not router_mode:
                self._emit(event)
            return event
        finally:
            if router_mode:
                self._state = saved

    @applies(tournament.ColorUpCompleted)
    def apply_color_up_completed(
        self, state: _TournamentState, event: tournament.ColorUpCompleted
    ) -> None:
        """Conservation invariant (Rule 24A/24C): total_chips_in_play
        moves by the rescue gain minus the race-loss leftover. Per-player
        stacks are kept in sync via ``player_stacks`` for downstream
        steps that read post-race totals."""
        state.total_chips_in_play += (
            event.chips_added_by_rescue - event.chips_removed_by_race
        )
        for award in event.per_player_awards:
            key = award.player_root.hex()
            inventory = state.player_chip_inventories.get(key, {})
            non_retired_value = sum(
                count * denom
                for denom, count in inventory.items()
                if denom != event.retired_denomination
            )
            state.player_stacks[key] = (
                non_retired_value + award.chips_won * event.new_denomination
            )

    # ---- Table balancing (TDA Rule 14) ----------------------------------

    @handles(tournament.RebalanceTables)
    def handle_rebalance_tables(
        self,
        cmd: tournament.RebalanceTables,
        state: _TournamentState | None = None,
        seq: int | None = None,
    ) -> tournament.PlayerMovedBetweenTables:
        """Emit one PlayerMovedBetweenTables event for the move computed
        from current table sizes. Saga consumes this and re-seats the
        player at the destination table.

        For the spec-level test, the move parameters are derived from
        the most recent observed table sizes which are tracked via
        external state (the saga); the aggregate emits a synthetic
        event with empty roots — real impl populates from state.
        """
        router_mode = state is not None
        saved = self._router_bind(state) if router_mode else None
        try:
            if not self.exists:
                raise TournamentNotFound()
            if not self.is_running:
                raise TournamentNotRunning()
            # Echo cmd fields onto the event so saga-tournament-table can
            # fan out the actual move (LeaveTable / SeatPlayer). When the
            # operator omits the fields we emit the legacy empty-rooted
            # form preserved for pre-batch-16 unit tests.
            event = tournament.PlayerMovedBetweenTables(
                player_root=cmd.player_root,
                source_table_root=cmd.source_table_root,
                destination_table_root=cmd.destination_table_root,
                destination_seat=cmd.destination_seat,
                stack=cmd.stack,
                moved_at=now(),
            )
            if not router_mode:
                self._emit(event)
            return event
        finally:
            if router_mode:
                self._state = saved

    @applies(tournament.PlayerMovedBetweenTables)
    def apply_player_moved(
        self, state: _TournamentState, _event: tournament.PlayerMovedBetweenTables
    ) -> None:
        pass

    # ---- Hand-for-hand bubble play (TDA Rule 12) ------------------------

    @handles(tournament.EnterHandForHand)
    def handle_enter_hand_for_hand(
        self,
        cmd: tournament.EnterHandForHand,
        state: _TournamentState | None = None,
        seq: int | None = None,
    ) -> tournament.HandForHandStarted:
        """Switch the tournament into hand-for-hand mode. Tables must
        complete each subsequent hand simultaneously until the next
        elimination ends bubble play.

        ``cmd.active_table_roots`` lists the tables expected to play
        the synchronised round; the value rides on the emitted event
        so saga-tournament-table-h4h can fan out
        ``EnterTableHandForHand`` to each table without a separate
        registry lookup.
        """
        router_mode = state is not None
        saved = self._router_bind(state) if router_mode else None
        try:
            if not self.exists:
                raise TournamentNotFound()
            if not self.is_running:
                raise TournamentNotRunning()
            event = tournament.HandForHandStarted(
                started_at=now(),
                active_table_roots=list(cmd.active_table_roots),
            )
            if not router_mode:
                self._emit(event)
            return event
        finally:
            if router_mode:
                self._state = saved

    @applies(tournament.HandForHandStarted)
    def apply_hand_for_hand_started(
        self, state: _TournamentState, event: tournament.HandForHandStarted
    ) -> None:
        state.hand_for_hand = True
        state.hand_for_hand_round = 0
        # Seed the per-round pending set from the event. The saga (or
        # operator) calls RecordTableHandComplete(table_root) once per
        # table as their synchronised hand finishes; when the set
        # empties, the tournament emits HandForHandRoundComplete and
        # the apply re-seeds for the next round.
        state.hand_for_hand_pending_tables = set(event.active_table_roots)
        state.hand_for_hand_active_tables = set(event.active_table_roots)

    @handles(tournament.RecordTableHandComplete)
    def handle_record_table_hand_complete(
        self,
        cmd: tournament.RecordTableHandComplete,
        state: _TournamentState | None = None,
        seq: int | None = None,
    ) -> tournament.HandForHandRoundComplete | None:
        """Saga signal that one specific table's synchronised H4H hand
        finished. Removes the table from the pending set; once the set
        empties (every active table reported in) the tournament emits
        ``HandForHandRoundComplete`` so the saga can re-arm every
        table for the next synchronised round.
        """
        router_mode = state is not None
        saved = self._router_bind(state) if router_mode else None
        try:
            if not self.exists:
                raise TournamentNotFound()
            if not self.is_running:
                raise TournamentNotRunning()
            self._state.hand_for_hand_pending_tables.discard(cmd.table_root)
            if self._state.hand_for_hand_pending_tables:
                # Still waiting on other tables — no event to emit.
                return None
            next_round = self._state.hand_for_hand_round + 1
            event = tournament.HandForHandRoundComplete(
                round_number=next_round,
                completed_at=now(),
            )
            if not router_mode:
                self._emit(event)
            return event
        finally:
            if router_mode:
                self._state = saved

    @handles(tournament.RecordHandForHandRoundComplete)
    def handle_record_h4h_round_complete(
        self,
        _cmd: tournament.RecordHandForHandRoundComplete,
        state: _TournamentState | None = None,
        seq: int | None = None,
    ) -> tournament.HandForHandRoundComplete:
        """Operator/saga signal that every active H4H table finished
        the current synchronised hand. Emits ``HandForHandRoundComplete``
        with the auto-incremented ``round_number`` so the
        operator/saga can re-arm each table for the next round.
        """
        router_mode = state is not None
        saved = self._router_bind(state) if router_mode else None
        try:
            if not self.exists:
                raise TournamentNotFound()
            if not self.is_running:
                raise TournamentNotRunning()
            next_round = self._state.hand_for_hand_round + 1
            event = tournament.HandForHandRoundComplete(
                round_number=next_round,
                completed_at=now(),
            )
            if not router_mode:
                self._emit(event)
            return event
        finally:
            if router_mode:
                self._state = saved

    @applies(tournament.HandForHandRoundComplete)
    def apply_hand_for_hand_round_complete(
        self, state: _TournamentState, event: tournament.HandForHandRoundComplete
    ) -> None:
        state.hand_for_hand_round = event.round_number
        # Re-seed the pending set from the active tables so the next
        # synchronised round can be tracked independently.
        state.hand_for_hand_pending_tables = set(state.hand_for_hand_active_tables)

    @applies(tournament.HandForHandEnded)
    def apply_hand_for_hand_ended(
        self, state: _TournamentState, _event: tournament.HandForHandEnded
    ) -> None:
        state.hand_for_hand = False
        state.hand_for_hand_pending_tables = set()
        state.hand_for_hand_active_tables = set()

    @handles(tournament.RecordHandForHandHand)
    def handle_record_h4h_hand(
        self,
        cmd: tournament.RecordHandForHandHand,
        state: _TournamentState | None = None,
        seq: int | None = None,
    ) -> tournament.HandForHandHandRecorded:
        """TDA RP-8B/8C — deduct from the level clock for one H4H hand.

        Default per-hand deduction is 120 seconds (RP-8C "whenever
        possible the clock should be reduced by 2-minutes each hand").
        When ``cmd.real_seconds`` is set, the deduction is the real
        time used, capped at 180 seconds (RP-8B 3-minute ceiling).
        """
        router_mode = state is not None
        saved = self._router_bind(state) if router_mode else None
        try:
            real = cmd.real_seconds
            deducted = min(real, 180) if real > 0 else 120
            event = tournament.HandForHandHandRecorded(
                real_seconds=real,
                clock_seconds_deducted=deducted,
                recorded_at=now(),
            )
            if not router_mode:
                self._emit(event)
            return event
        finally:
            if router_mode:
                self._state = saved

    @applies(tournament.HandForHandHandRecorded)
    def apply_h4h_hand_recorded(
        self,
        state: _TournamentState,
        event: tournament.HandForHandHandRecorded,
    ) -> None:
        state.level_seconds_remaining = max(
            0, state.level_seconds_remaining - event.clock_seconds_deducted
        )

    @handles(tournament.RecordSimultaneousBusts)
    def handle_record_sim_busts(
        self,
        cmd: tournament.RecordSimultaneousBusts,
        state: _TournamentState | None = None,
        seq: int | None = None,
    ) -> tournament.SimultaneousBustsRecorded:
        """TDA RP-8A — record a simultaneous-bust group on an H4H hand.
        ``same_table`` triggers the WSOP-126b pre-hand-stack tiebreak."""
        router_mode = state is not None
        saved = self._router_bind(state) if router_mode else None
        try:
            event = tournament.SimultaneousBustsRecorded(
                player_roots=list(cmd.player_roots),
                hand_root=cmd.hand_root,
                same_table=cmd.same_table,
                pre_hand_stacks=dict(cmd.pre_hand_stacks),
                recorded_at=now(),
            )
            if not router_mode:
                self._emit(event)
            return event
        finally:
            if router_mode:
                self._state = saved

    @applies(tournament.SimultaneousBustsRecorded)
    def apply_sim_busts_recorded(
        self,
        state: _TournamentState,
        event: tournament.SimultaneousBustsRecorded,
    ) -> None:
        roots = [r.hex() for r in event.player_roots]
        if event.same_table:
            # WSOP-126b — record as ordered list (highest pre-hand stack
            # first) so CompleteTournament awards the higher position to
            # the higher-stack player. Stored in
            # ``simultaneous_bust_orderings`` to distinguish from
            # different-table simultaneous busts (which split payouts).
            ordered = sorted(roots, key=lambda h: -event.pre_hand_stacks.get(h, 0))
            if not hasattr(state, "simultaneous_bust_orderings"):
                state.simultaneous_bust_orderings = []
            state.simultaneous_bust_orderings.append(ordered)
        else:
            state.simultaneous_bust_groups.append(frozenset(roots))

    @handles(tournament.TriggerSeatRedraw)
    def handle_trigger_seat_redraw(
        self,
        cmd: tournament.TriggerSeatRedraw,
        state: _TournamentState | None = None,
        seq: int | None = None,
    ) -> tournament.SeatRedrawTriggered:
        """WSOP Rule 67c — emit SeatRedrawTriggered with the right
        ``trigger`` label for the table-count threshold tripped.
        ``original_field`` >= 100 is required (smaller events do not
        get the threshold redraws)."""
        router_mode = state is not None
        saved = self._router_bind(state) if router_mode else None
        try:
            tables = cmd.tables_remaining
            triggers = {3: "THREE_TABLES", 2: "TWO_TABLES", 1: "FINAL_TABLE"}
            label = triggers.get(tables, "")
            event = tournament.SeatRedrawTriggered(
                trigger=label,
                tables_remaining=tables,
                original_field=cmd.original_field,
                triggered_at=now(),
            )
            if not router_mode:
                self._emit(event)
            return event
        finally:
            if router_mode:
                self._state = saved

    @applies(tournament.SeatRedrawTriggered)
    def apply_seat_redraw_triggered(
        self, state: _TournamentState, _event: tournament.SeatRedrawTriggered
    ) -> None:
        # No internal state mutation; downstream saga consumes the event
        # to actually shuffle players.
        pass

    @handles(tournament.ReseatAbsentPlayer)
    def handle_reseat_absent_player(
        self,
        cmd: tournament.ReseatAbsentPlayer,
        state: _TournamentState | None = None,
        seq: int | None = None,
    ) -> tournament.PlayerMovedTables:
        """TDA RP-16 — reseat an absent player from a breaking table to
        a new table; missed-blinds clock continues. The chip count
        carries over intact."""
        router_mode = state is not None
        saved = self._router_bind(state) if router_mode else None
        try:
            event = tournament.PlayerMovedTables(
                player_root=cmd.player_root,
                from_table_root=cmd.from_table_root,
                to_table_root=cmd.to_table_root,
                to_seat=cmd.to_seat,
                stack=cmd.stack,
                absent_at_move=True,
                moved_at=now(),
            )
            if not router_mode:
                self._emit(event)
            return event
        finally:
            if router_mode:
                self._state = saved

    @applies(tournament.PlayerMovedTables)
    def apply_player_moved_tables(
        self, state: _TournamentState, event: tournament.PlayerMovedTables
    ) -> None:
        key = event.player_root.hex()
        state.player_stacks[key] = event.stack

    @handles(tournament.ReEntryPlayer)
    def handle_re_entry_player(
        self,
        cmd: tournament.ReEntryPlayer,
        state: _TournamentState | None = None,
        seq: int | None = None,
    ) -> tournament.PlayerReEntered:
        """TDA Rule 8B — re-entry forfeits prior chips and adds a fresh
        starting stack. Net change to total_chips_in_play is
        ``starting_stack - chips_forfeited``."""
        router_mode = state is not None
        saved = self._router_bind(state) if router_mode else None
        try:
            event = tournament.PlayerReEntered(
                player_root=cmd.player_root,
                chips_forfeited=cmd.chips_forfeited,
                chips_added=self._state.starting_stack,
                re_entered_at=now(),
            )
            if not router_mode:
                self._emit(event)
            return event
        finally:
            if router_mode:
                self._state = saved

    @applies(tournament.PlayerReEntered)
    def apply_player_re_entered(
        self, state: _TournamentState, event: tournament.PlayerReEntered
    ) -> None:
        state.total_chips_in_play = (
            state.total_chips_in_play - event.chips_forfeited + event.chips_added
        )

    @handles(tournament.AdvanceAbsentBlind)
    def handle_advance_absent_blind(
        self,
        cmd: tournament.AdvanceAbsentBlind,
        state: _TournamentState | None = None,
        seq: int | None = None,
    ) -> tournament.AbsentBlindAdvanced:
        """WSOP Rule 36 — heads-up absent-blind tick.

        The lone player banks SB+BB; the absent player's stack
        decreases by the same amount. The button advances by 1 (the
        button advance itself is accounted for at the table aggregate
        — this event records the chip transfer)."""
        router_mode = state is not None
        saved = self._router_bind(state) if router_mode else None
        try:
            delta = cmd.small_blind + cmd.big_blind
            event = tournament.AbsentBlindAdvanced(
                table_root=cmd.table_root,
                absent_player_root=cmd.absent_player_root,
                lone_player_root=cmd.lone_player_root,
                stack_delta=delta,
                advanced_at=now(),
            )
            if not router_mode:
                self._emit(event)
            return event
        finally:
            if router_mode:
                self._state = saved

    @applies(tournament.AbsentBlindAdvanced)
    def apply_absent_blind_advanced(
        self, state: _TournamentState, event: tournament.AbsentBlindAdvanced
    ) -> None:
        absent_key = event.absent_player_root.hex()
        lone_key = event.lone_player_root.hex()
        state.player_stacks[absent_key] = max(
            0, state.player_stacks.get(absent_key, 0) - event.stack_delta
        )
        state.player_stacks[lone_key] = (
            state.player_stacks.get(lone_key, 0) + event.stack_delta
        )

    # ---- TDA RP-18 HORSE rotation ----------------------------------------

    _HORSE_CYCLE = (
        1,  # TEXAS_HOLDEM
        7,  # OMAHA_HI_LO_8B
        5,  # RAZZ
        4,  # SEVEN_CARD_STUD
        6,  # STUD_HI_LO_8B
    )

    @handles(tournament.RotateMixedGameVariant)
    def handle_rotate_mixed_game_variant(
        self,
        cmd: tournament.RotateMixedGameVariant,
        state: _TournamentState | None = None,
        seq: int | None = None,
    ) -> tournament.MixedGameVariantRotated:
        """TDA RP-18 — advance the current game_variant one step in the
        HORSE cycle. Wraps from STUD_HI_LO_8B back to TEXAS_HOLDEM."""
        router_mode = state is not None
        saved = self._router_bind(state) if router_mode else None
        try:
            current = self._state.game_variant
            cycle = self._HORSE_CYCLE
            try:
                idx = cycle.index(current)
            except ValueError:
                idx = -1
            next_variant = cycle[(idx + 1) % len(cycle)]
            event = tournament.MixedGameVariantRotated(
                from_variant=current,
                to_variant=next_variant,
                rotated_at=now(),
            )
            if not router_mode:
                self._emit(event)
            return event
        finally:
            if router_mode:
                self._state = saved

    @applies(tournament.MixedGameVariantRotated)
    def apply_mixed_game_variant_rotated(
        self, state: _TournamentState, event: tournament.MixedGameVariantRotated
    ) -> None:
        state.game_variant = event.to_variant

    # ---- WSOP Rule 125 / 122 — end-of-day & day-2 resume -----------------

    @handles(tournament.StopNewHands)
    def handle_stop_new_hands(
        self,
        cmd: tournament.StopNewHands,
        state: _TournamentState | None = None,
        seq: int | None = None,
    ) -> tournament.NewHandsHalted:
        """WSOP Rule 125 — halt new hands; in-progress hand completes."""
        router_mode = state is not None
        saved = self._router_bind(state) if router_mode else None
        try:
            event = tournament.NewHandsHalted(
                effective_at="AFTER_CURRENT_HAND",
                reason=cmd.reason or "END_OF_DAY",
                halted_at=now(),
            )
            if not router_mode:
                self._emit(event)
            return event
        finally:
            if router_mode:
                self._state = saved

    @applies(tournament.NewHandsHalted)
    def apply_new_hands_halted(
        self, state: _TournamentState, _event: tournament.NewHandsHalted
    ) -> None:
        state.status = tournament.TournamentStatus.TOURNAMENT_HALTING

    @handles(tournament.BagAndTag)
    def handle_bag_and_tag(
        self,
        cmd: tournament.BagAndTag,
        state: _TournamentState | None = None,
        seq: int | None = None,
    ) -> tournament.BagAndTagComplete:
        """WSOP Rule 122 — snapshot per-player stacks and seats."""
        router_mode = state is not None
        saved = self._router_bind(state) if router_mode else None
        try:
            snapshots = []
            for hex_key, stack in self._state.player_stacks.items():
                snapshots.append(
                    tournament.PlayerBagSnapshot(
                        player_root=bytes.fromhex(hex_key),
                        stack=stack,
                        table_root=b"",
                        seat=0,
                    )
                )
            event = tournament.BagAndTagComplete(
                snapshots=snapshots,
                completed_at=now(),
            )
            if not router_mode:
                self._emit(event)
            return event
        finally:
            if router_mode:
                self._state = saved

    @applies(tournament.BagAndTagComplete)
    def apply_bag_and_tag_complete(
        self, state: _TournamentState, event: tournament.BagAndTagComplete
    ) -> None:
        state.status = tournament.TournamentStatus.TOURNAMENT_BAGGED
        if not hasattr(state, "bagged_snapshots"):
            state.bagged_snapshots = {}
        for snap in event.snapshots:
            state.bagged_snapshots[snap.player_root.hex()] = snap

    # ------------------------------------------------------------------
    # TDA Rule 71 / WSOP Rule 113-114 — penalties + DQ
    # ------------------------------------------------------------------

    @handles(tournament.IssuePenalty)
    def handle_issue_penalty(
        self,
        cmd: tournament.IssuePenalty,
        state: _TournamentState | None = None,
        seq: int | None = None,
    ) -> tournament.PenaltyIssued:
        """Issue a tournament penalty (Rule 71A).

        Computes ``missed_hands``: 0 for VERBAL_WARNING / DISQUALIFIED,
        1 for MISSED_HAND, ``rounds * table_size`` for MISSED_ROUND.
        """
        router_mode = state is not None
        saved = self._router_bind(state) if router_mode else None
        try:
            ptype = cmd.type or "VERBAL_WARNING"
            rounds = cmd.rounds
            table_size = cmd.table_size or 6
            if ptype == "MISSED_HAND":
                missed = 1
            elif ptype == "MISSED_ROUND":
                missed = rounds * table_size
            else:
                missed = 0
            event = tournament.PenaltyIssued(
                player_root=cmd.player_root,
                type=ptype,
                rounds=rounds,
                missed_hands=missed,
                issued_at=now(),
            )
            if not router_mode:
                self._emit(event)
            return event
        finally:
            if router_mode:
                self._state = saved

    @applies(tournament.PenaltyIssued)
    def apply_penalty_issued(
        self, state: _TournamentState, event: tournament.PenaltyIssued
    ) -> None:
        """Track active penalty rounds for the player."""
        if event.type in ("MISSED_HAND", "MISSED_ROUND"):
            key = event.player_root.hex()
            state.active_penalties[key] = max(
                state.active_penalties.get(key, 0), event.rounds or 1
            )

    @handles(tournament.DecrementPenalty)
    def handle_decrement_penalty(
        self,
        cmd: tournament.DecrementPenalty,
        state: _TournamentState | None = None,
        seq: int | None = None,
    ) -> tournament.PenaltyRoundsDecremented:
        """TDA Rule 71 — saga decrements the penalty round counter."""
        router_mode = state is not None
        saved = self._router_bind(state) if router_mode else None
        try:
            key = cmd.player_root.hex()
            current = self._state.active_penalties.get(key, 0)
            remaining = max(0, current - 1)
            event = tournament.PenaltyRoundsDecremented(
                player_root=cmd.player_root,
                rounds_remaining=remaining,
                decremented_at=now(),
            )
            if not router_mode:
                self._emit(event)
            return event
        finally:
            if router_mode:
                self._state = saved

    @applies(tournament.PenaltyRoundsDecremented)
    def apply_penalty_decremented(
        self, state: _TournamentState, event: tournament.PenaltyRoundsDecremented
    ) -> None:
        key = event.player_root.hex()
        if event.rounds_remaining > 0:
            state.active_penalties[key] = event.rounds_remaining
        else:
            state.active_penalties.pop(key, None)

    @handles(tournament.DisqualifyPlayer)
    def handle_disqualify_player(
        self,
        cmd: tournament.DisqualifyPlayer,
        state: _TournamentState | None = None,
        seq: int | None = None,
    ) -> tournament.PlayerDisqualified:
        """TDA Rule 71D / WSOP Rule 114 — DQ + chip removal.

        Reads the player's stack from ``state.player_stacks`` (seeded
        by tests via ``apply_player_stack_recorded``) and emits
        ``PlayerDisqualified`` with the chip count.
        """
        router_mode = state is not None
        saved = self._router_bind(state) if router_mode else None
        try:
            key = cmd.player_root.hex()
            chips = self._state.player_stacks.get(key, 0)
            event = tournament.PlayerDisqualified(
                player_root=cmd.player_root,
                reason=cmd.reason,
                chips_removed=chips,
                disqualified_at=now(),
            )
            if not router_mode:
                self._emit(event)
            return event
        finally:
            if router_mode:
                self._state = saved

    @applies(tournament.PlayerDisqualified)
    def apply_player_disqualified(
        self, state: _TournamentState, event: tournament.PlayerDisqualified
    ) -> None:
        """Remove DQ player from registered_players + chip pool."""
        key = event.player_root.hex()
        state.registered_players.pop(key, None)
        state.player_stacks.pop(key, None)
        state.players_remaining = len(state.registered_players)
        state.total_chips_in_play = max(
            0, state.total_chips_in_play - event.chips_removed
        )

    # ------------------------------------------------------------------
    # TDA RP-22 / WSOP Rule 39 — bounty payouts
    # WSOP Rule 16 — no-show chip removal
    # ------------------------------------------------------------------

    @handles(tournament.AwardBounty)
    def handle_award_bounty(
        self,
        cmd: tournament.AwardBounty,
        state: _TournamentState | None = None,
        seq: int | None = None,
    ) -> tournament.BountyAwarded:
        """Emit BountyAwarded for an eliminator who knocked out another."""
        router_mode = state is not None
        saved = self._router_bind(state) if router_mode else None
        try:
            event = tournament.BountyAwarded(
                eliminator_root=cmd.eliminator_root,
                knocked_out_root=cmd.knocked_out_root,
                amount=cmd.amount,
                tiebreak_reason=cmd.tiebreak_reason,
                awarded_at=now(),
            )
            if not router_mode:
                self._emit(event)
            return event
        finally:
            if router_mode:
                self._state = saved

    @applies(tournament.BountyAwarded)
    def apply_bounty_awarded(
        self, state: _TournamentState, event: tournament.BountyAwarded
    ) -> None:
        """Track bounty totals on the eliminator."""
        key = event.eliminator_root.hex()
        # bounty_totals is part of the proto state but not on _TournamentState
        # — track via a fresh dict if absent.
        if not hasattr(state, "bounty_totals"):
            state.bounty_totals = {}
        state.bounty_totals[key] = state.bounty_totals.get(key, 0) + event.amount

    @handles(tournament.DetectNoShow)
    def handle_detect_no_show(
        self,
        cmd: tournament.DetectNoShow,
        state: _TournamentState | None = None,
        seq: int | None = None,
    ) -> tournament.NoShowDetected:
        """WSOP Rule 16 — detect a no-show and remove their chips.

        Uses the player's starting_stack as ``chips_removed`` (since
        they never took a hand) and their buy_in as the safekeeping
        amount. If the player isn't registered the handler emits a
        zero-effect event (no-op).
        """
        router_mode = state is not None
        saved = self._router_bind(state) if router_mode else None
        try:
            key = cmd.player_root.hex()
            chips = self._state.player_stacks.get(key, self._state.starting_stack)
            event = tournament.NoShowDetected(
                player_root=cmd.player_root,
                chips_removed=chips,
                buy_in_held=self._state.buy_in,
                detected_at=now(),
            )
            if not router_mode:
                self._emit(event)
            return event
        finally:
            if router_mode:
                self._state = saved

    @applies(tournament.NoShowDetected)
    def apply_no_show_detected(
        self, state: _TournamentState, event: tournament.NoShowDetected
    ) -> None:
        """Remove the no-show player from registered_players + chip pool."""
        key = event.player_root.hex()
        state.registered_players.pop(key, None)
        state.player_stacks.pop(key, None)
        state.players_remaining = len(state.registered_players)
        state.total_chips_in_play = max(
            0, state.total_chips_in_play - event.chips_removed
        )


# Populate the applier registry after class definition.
for _name in dir(Tournament):
    _attr = getattr(Tournament, _name, None)
    _marker = getattr(_attr, "__angzarr_applies__", None)
    if _marker is not None:
        _APPLIER_REGISTRY.append((_marker, _name))
