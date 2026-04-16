"""Tournament aggregate - rich domain model (OO pattern).

This implements the tournament aggregate using CommandHandler base class
with @handles/@applies decorators.
"""

from dataclasses import dataclass, field

from angzarr_client import CommandHandler, applies, handles, now
from angzarr_client.errors import CommandRejectedError
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


class Tournament(CommandHandler[_TournamentState]):
    """Tournament aggregate with event sourcing."""

    domain = "tournament"

    def _create_empty_state(self) -> _TournamentState:
        return _TournamentState()

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
        return bool(self._get_state().tournament_id)

    @property
    def is_registration_open(self) -> bool:
        return (
            self._get_state().status
            == tournament.TournamentStatus.TOURNAMENT_REGISTRATION_OPEN
        )

    @property
    def is_running(self) -> bool:
        return (
            self._get_state().status == tournament.TournamentStatus.TOURNAMENT_RUNNING
        )

    @property
    def status(self) -> int:
        return self._get_state().status

    @property
    def buy_in(self) -> int:
        return self._get_state().buy_in

    @property
    def starting_stack(self) -> int:
        return self._get_state().starting_stack

    @property
    def max_players(self) -> int:
        return self._get_state().max_players

    @property
    def min_players(self) -> int:
        return self._get_state().min_players

    @property
    def registered_players(self) -> dict:
        return self._get_state().registered_players

    @property
    def players_remaining(self) -> int:
        return self._get_state().players_remaining

    @property
    def total_prize_pool(self) -> int:
        return self._get_state().total_prize_pool

    @property
    def current_level(self) -> int:
        return self._get_state().current_level

    @property
    def rebuy_config(self):
        return self._get_state().rebuy_config

    @property
    def blind_structure(self) -> list:
        return self._get_state().blind_structure

    def has_capacity(self) -> bool:
        return len(self._get_state().registered_players) < self._get_state().max_players

    def is_player_registered(self, player_root_hex: str) -> bool:
        return player_root_hex in self._get_state().registered_players

    def can_rebuy(self, player_root_hex: str) -> bool:
        state = self._get_state()
        if state.status != tournament.TournamentStatus.TOURNAMENT_RUNNING:
            return False
        if state.rebuy_config is None or not state.rebuy_config.enabled:
            return False
        if (
            state.rebuy_config.rebuy_level_cutoff > 0
            and state.current_level > state.rebuy_config.rebuy_level_cutoff
        ):
            return False
        registration = state.registered_players.get(player_root_hex)
        if registration is not None:
            if (
                state.rebuy_config.max_rebuys > 0
                and registration.rebuys_used >= state.rebuy_config.max_rebuys
            ):
                return False
        return True

    # --- Command handlers ---

    @handles(tournament.CreateTournament)
    def handle_create_tournament(
        self, cmd: tournament.CreateTournament
    ) -> tournament.TournamentCreated:
        """Create a new tournament."""
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

        return tournament.TournamentCreated(
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

    @handles(tournament.OpenRegistration)
    def handle_open_registration(
        self, cmd: tournament.OpenRegistration
    ) -> tournament.RegistrationOpened:
        """Open registration for the tournament."""
        if not self.exists:
            raise CommandRejectedError("Tournament does not exist")
        if self.is_registration_open:
            raise CommandRejectedError("Registration is already open")
        return tournament.RegistrationOpened(opened_at=now())

    @handles(tournament.CloseRegistration)
    def handle_close_registration(
        self, cmd: tournament.CloseRegistration
    ) -> tournament.RegistrationClosed:
        """Close registration for the tournament."""
        if not self.exists:
            raise CommandRejectedError("Tournament does not exist")
        if not self.is_registration_open:
            raise CommandRejectedError("Registration is not open")
        return tournament.RegistrationClosed(closed_at=now())

    @handles(tournament.EnrollPlayer)
    def handle_enroll_player(
        self, cmd: tournament.EnrollPlayer
    ) -> tournament.TournamentPlayerEnrolled | tournament.TournamentEnrollmentRejected:
        """Enroll a player in the tournament."""
        if not self.exists:
            raise CommandRejectedError("Tournament does not exist")

        # Validate enrollment
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
            return tournament.TournamentEnrollmentRejected(
                player_root=cmd.player_root,
                reservation_id=cmd.reservation_id,
                reason=rejection_reason,
                rejected_at=now(),
            )

        return tournament.TournamentPlayerEnrolled(
            player_root=cmd.player_root,
            reservation_id=cmd.reservation_id,
            fee_paid=self.buy_in,
            starting_stack=self.starting_stack,
            registration_number=len(self.registered_players) + 1,
            enrolled_at=now(),
        )

    @handles(tournament.ProcessRebuy)
    def handle_process_rebuy(
        self, cmd: tournament.ProcessRebuy
    ) -> tournament.RebuyProcessed | tournament.RebuyDenied:
        """Process a rebuy request."""
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
            rejection_reason = "Rebuy not allowed"

        if rejection_reason is not None:
            return tournament.RebuyDenied(
                player_root=cmd.player_root,
                reason=rejection_reason,
                denied_at=now(),
            )

        state = self._get_state()
        registration = state.registered_players.get(cmd.player_root.hex())
        rebuy_count = (registration.rebuys_used + 1) if registration else 1
        rebuy_cost = (
            state.rebuy_config.rebuy_cost if state.rebuy_config else state.buy_in
        )

        return tournament.RebuyProcessed(
            player_root=cmd.player_root,
            rebuy_count=rebuy_count,
            rebuy_cost=rebuy_cost,
            new_stack=state.starting_stack,
            processed_at=now(),
        )

    @handles(tournament.AdvanceBlindLevel)
    def handle_advance_blind_level(
        self, cmd: tournament.AdvanceBlindLevel
    ) -> tournament.BlindLevelAdvanced:
        """Advance the blind level."""
        if not self.exists:
            raise CommandRejectedError("Tournament does not exist")
        if not self.is_running:
            raise CommandRejectedError("Tournament is not running")

        state = self._get_state()
        new_level = state.current_level + 1
        small_blind = big_blind = ante = 0
        if new_level <= len(state.blind_structure):
            level_config = state.blind_structure[new_level - 1]
            small_blind = level_config.small_blind
            big_blind = level_config.big_blind
            ante = level_config.ante

        return tournament.BlindLevelAdvanced(
            level=new_level,
            small_blind=small_blind,
            big_blind=big_blind,
            ante=ante,
            advanced_at=now(),
        )

    @handles(tournament.EliminatePlayer)
    def handle_eliminate_player(
        self, cmd: tournament.EliminatePlayer
    ) -> tournament.PlayerEliminated:
        """Eliminate a player from the tournament."""
        if not self.exists:
            raise CommandRejectedError("Tournament does not exist")
        if not self.is_running:
            raise CommandRejectedError("Tournament is not running")
        if not cmd.player_root:
            raise CommandRejectedError("player_root is required")
        if not self.is_player_registered(cmd.player_root.hex()):
            raise CommandRejectedError("Player is not registered")

        return tournament.PlayerEliminated(
            player_root=cmd.player_root,
            finish_position=self.players_remaining,
            payout=0,
            eliminated_at=now(),
        )

    @handles(tournament.PauseTournament)
    def handle_pause_tournament(
        self, cmd: tournament.PauseTournament
    ) -> tournament.TournamentPaused:
        """Pause the tournament."""
        if not self.exists:
            raise CommandRejectedError("Tournament does not exist")
        if not self.is_running:
            raise CommandRejectedError("Tournament is not running")
        return tournament.TournamentPaused(reason=cmd.reason, paused_at=now())

    @handles(tournament.ResumeTournament)
    def handle_resume_tournament(
        self, cmd: tournament.ResumeTournament
    ) -> tournament.TournamentResumed:
        """Resume a paused tournament."""
        if not self.exists:
            raise CommandRejectedError("Tournament does not exist")
        if self.status != tournament.TournamentStatus.TOURNAMENT_PAUSED:
            raise CommandRejectedError("Tournament is not paused")
        return tournament.TournamentResumed(resumed_at=now())

    @handles(tournament.StartTournament)
    def handle_start_tournament(
        self, cmd: tournament.StartTournament
    ) -> tournament.TournamentStarted:
        """Start the tournament."""
        if not self.exists:
            raise CommandRejectedError("Tournament does not exist")
        if not self.is_registration_open:
            raise CommandRejectedError("Registration is not open")
        if len(self.registered_players) < self.min_players:
            raise CommandRejectedError("Not enough players to start")
        return tournament.TournamentStarted(
            total_entries=len(self.registered_players),
            total_prize_pool=self.total_prize_pool,
            started_at=now(),
        )
