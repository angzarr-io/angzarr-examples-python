"""Tournament aggregate - rich domain model."""

from dataclasses import dataclass, field

from google.protobuf.any_pb2 import Any as ProtoAny

from angzarr_client import applies, command_handler, handles, now
from angzarr_client.errors import CommandRejectedError
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
        if not state.blind_structure:
            state.blind_structure.append(
                tournament.BlindLevel(level=1, small_blind=0, big_blind=0, ante=0)
            )
        state.current_level = 1

    @applies(tournament.RegistrationOpened)
    def apply_registration_opened(
        self, state: _TournamentState, _event: tournament.RegistrationOpened
    ) -> None:
        state.status = tournament.TournamentStatus.TOURNAMENT_REGISTRATION_OPEN

    @applies(tournament.RegistrationClosed)
    def apply_registration_closed(
        self, state: _TournamentState, _event: tournament.RegistrationClosed
    ) -> None:
        pass

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
        return (
            self._state.status
            == tournament.TournamentStatus.TOURNAMENT_REGISTRATION_OPEN
        )

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
                raise CommandRejectedError("Tournament already exists")
            if not cmd.name:
                raise CommandRejectedError("name is required")
            if cmd.buy_in <= 0:
                raise CommandRejectedError("buy_in must be positive")
            if cmd.starting_stack <= 0:
                raise CommandRejectedError("starting_stack must be positive")
            if cmd.max_players < 2:
                raise CommandRejectedError("max_players must be at least 2")
            if cmd.min_players < 2:
                raise CommandRejectedError("min_players must be at least 2")
            if cmd.min_players > cmd.max_players:
                raise CommandRejectedError("min_players cannot exceed max_players")

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
                raise CommandRejectedError("Tournament does not exist")
            if self.is_running:
                raise CommandRejectedError(
                    "Cannot open registration on a running tournament"
                )
            if self.is_registration_open:
                raise CommandRejectedError("Registration is already open")
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
                raise CommandRejectedError("Tournament does not exist")
            if not self.is_registration_open:
                raise CommandRejectedError("Registration is not open")
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
                raise CommandRejectedError("Tournament does not exist")

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
                raise CommandRejectedError("Tournament does not exist")
            if not self.is_running:
                raise CommandRejectedError("Tournament is not running")

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
    ) -> tournament.BlindLevelAdvanced:
        """Advance the blind level."""
        router_mode = state is not None
        saved = self._router_bind(state) if router_mode else None
        try:
            if not self.exists:
                raise CommandRejectedError("Tournament does not exist")
            if not self.is_running:
                raise CommandRejectedError("Tournament is not running")

            s = self._state
            new_level = s.current_level + 1
            small_blind = big_blind = ante = 0
            if new_level <= len(s.blind_structure):
                level_config = s.blind_structure[new_level - 1]
                small_blind = level_config.small_blind
                big_blind = level_config.big_blind
                ante = level_config.ante

            event = tournament.BlindLevelAdvanced(
                level=new_level,
                small_blind=small_blind,
                big_blind=big_blind,
                ante=ante,
                advanced_at=now(),
            )
            if not router_mode:
                self._emit(event)
            return event
        finally:
            if router_mode:
                self._state = saved

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
                raise CommandRejectedError("Tournament does not exist")
            if not self.is_running:
                raise CommandRejectedError("Tournament is not running")
            if not cmd.player_root:
                raise CommandRejectedError("player_root is required")
            if not self.is_player_registered(cmd.player_root.hex()):
                raise CommandRejectedError("Player is not registered")

            event = tournament.PlayerEliminated(
                player_root=cmd.player_root,
                hand_root=cmd.hand_root,
                finish_position=self.players_remaining,
                payout=0,
                eliminated_at=now(),
            )
            if not router_mode:
                self._emit(event)
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
                raise CommandRejectedError("Tournament does not exist")
            if self.status == tournament.TournamentStatus.TOURNAMENT_PAUSED:
                raise CommandRejectedError("Tournament is already paused")
            if not self.is_running:
                raise CommandRejectedError("Tournament is not running")
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
        """Resume a paused tournament."""
        router_mode = state is not None
        saved = self._router_bind(state) if router_mode else None
        try:
            if not self.exists:
                raise CommandRejectedError("Tournament does not exist")
            if self.status != tournament.TournamentStatus.TOURNAMENT_PAUSED:
                raise CommandRejectedError("Tournament is not paused")
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
                raise CommandRejectedError("Tournament does not exist")
            if not self.is_registration_open:
                raise CommandRejectedError("Registration is not open")
            if len(self.registered_players) < self.min_players:
                raise CommandRejectedError("Not enough players to start")
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


# Populate the applier registry after class definition.
for _name in dir(Tournament):
    _attr = getattr(Tournament, _name, None)
    _marker = getattr(_attr, "__angzarr_applies__", None)
    if _marker is not None:
        _APPLIER_REGISTRY.append((_marker, _name))
