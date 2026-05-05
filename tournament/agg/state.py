"""Tournament state and event appliers (pure-function form).

The live state + applier logic now lives on the ``Tournament`` class in
``tournament/agg/handlers.py``. This module retains the same contents in
pure-function form for reuse (e.g. projections or docs examples).
"""

from dataclasses import dataclass, field

from angzarr_client.proto.examples import tournament_pb2 as tournament


@dataclass
class PlayerRegistration:
    """Player registration record in tournament."""

    player_root: bytes = b""
    fee_paid: int = 0
    starting_stack: int = 0
    rebuys_used: int = 0
    addon_taken: bool = False
    table_assignment: int = 0
    seat_assignment: int = 0


@dataclass
class TournamentState:
    """Tournament aggregate state."""

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
    registered_players: dict[str, PlayerRegistration] = field(default_factory=dict)
    players_remaining: int = 0
    total_prize_pool: int = 0
    # TDA Rule 71D / WSOP Rule 114 — total chips in play tracked
    # explicitly so DQ/no-show removals are observable.
    total_chips_in_play: int = 0
    # TDA Rule 71 — active per-player penalty register. player_root_hex →
    # remaining round count (0 for VERBAL_WARNING / one-hand penalties
    # that resolve on next deal).
    active_penalties: dict[str, int] = field(default_factory=dict)
    # Per-player chip stacks tracked at the tournament level (separate
    # from per-table tracking). Updated via DisqualifyPlayer for now.
    player_stacks: dict[str, int] = field(default_factory=dict)

    @property
    def exists(self) -> bool:
        """Check if the tournament exists."""
        return bool(self.tournament_id)

    @property
    def is_registration_open(self) -> bool:
        """Check if registration is open."""
        return self.status == tournament.TournamentStatus.TOURNAMENT_REGISTRATION_OPEN

    @property
    def is_running(self) -> bool:
        """Check if tournament is running."""
        return self.status == tournament.TournamentStatus.TOURNAMENT_RUNNING

    def has_capacity(self) -> bool:
        """Check if tournament has capacity for more players."""
        return len(self.registered_players) < self.max_players

    def is_player_registered(self, player_root_hex: str) -> bool:
        """Check if a player is registered."""
        return player_root_hex in self.registered_players

    def can_rebuy(self, player_root_hex: str) -> bool:
        """Check if rebuy is allowed for a player."""
        if not self.is_running:
            return False

        if self.rebuy_config is None or not self.rebuy_config.enabled:
            return False

        # Check level cutoff
        if (
            self.rebuy_config.rebuy_level_cutoff > 0
            and self.current_level > self.rebuy_config.rebuy_level_cutoff
        ):
            return False

        # Check max rebuys
        registration = self.registered_players.get(player_root_hex)
        if registration is not None:
            if (
                self.rebuy_config.max_rebuys > 0
                and registration.rebuys_used >= self.rebuy_config.max_rebuys
            ):
                return False

        return True


# --- Event appliers (pure functions) ---


def apply_created(state: TournamentState, event: tournament.TournamentCreated) -> None:
    """Apply TournamentCreated event to state."""
    state.tournament_id = f"tournament_{event.name}"
    state.name = event.name
    state.game_variant = event.game_variant
    state.status = tournament.TournamentStatus.TOURNAMENT_CREATED
    state.buy_in = event.buy_in
    state.starting_stack = event.starting_stack
    state.max_players = event.max_players
    state.min_players = event.min_players
    state.rebuy_config = event.rebuy_config if event.HasField("rebuy_config") else None
    state.blind_structure = list(event.blind_structure)
    state.current_level = 1


def apply_registration_opened(
    state: TournamentState, _event: tournament.RegistrationOpened
) -> None:
    """Apply RegistrationOpened event to state."""
    state.status = tournament.TournamentStatus.TOURNAMENT_REGISTRATION_OPEN


def apply_registration_closed(
    _state: TournamentState, _event: tournament.RegistrationClosed
) -> None:
    """Apply RegistrationClosed event to state."""
    # Status will change to Running when tournament starts
    pass


def apply_player_enrolled(
    state: TournamentState, event: tournament.TournamentPlayerEnrolled
) -> None:
    """Apply TournamentPlayerEnrolled event to state."""
    player_root_hex = event.player_root.hex()
    state.registered_players[player_root_hex] = PlayerRegistration(
        player_root=event.player_root,
        fee_paid=event.fee_paid,
        starting_stack=event.starting_stack,
        rebuys_used=0,
        addon_taken=False,
        table_assignment=0,
        seat_assignment=0,
    )
    state.total_prize_pool += event.fee_paid
    state.players_remaining = len(state.registered_players)


def apply_enrollment_rejected(
    _state: TournamentState, _event: tournament.TournamentEnrollmentRejected
) -> None:
    """Apply TournamentEnrollmentRejected event to state."""
    # No state change - just an event for the player
    pass


def apply_rebuy_processed(
    state: TournamentState, event: tournament.RebuyProcessed
) -> None:
    """Apply RebuyProcessed event to state."""
    player_root_hex = event.player_root.hex()
    registration = state.registered_players.get(player_root_hex)
    if registration is not None:
        registration.rebuys_used = event.rebuy_count
    state.total_prize_pool += event.rebuy_cost


def apply_rebuy_denied(_state: TournamentState, _event: tournament.RebuyDenied) -> None:
    """Apply RebuyDenied event to state."""
    # No state change
    pass


def apply_blind_advanced(
    state: TournamentState, event: tournament.BlindLevelAdvanced
) -> None:
    """Apply BlindLevelAdvanced event to state."""
    state.current_level = event.level


def apply_player_eliminated(
    state: TournamentState, event: tournament.PlayerEliminated
) -> None:
    """Apply PlayerEliminated event to state."""
    player_root_hex = event.player_root.hex()
    state.registered_players.pop(player_root_hex, None)
    state.players_remaining = len(state.registered_players)


def apply_paused(state: TournamentState, _event: tournament.TournamentPaused) -> None:
    """Apply TournamentPaused event to state."""
    state.status = tournament.TournamentStatus.TOURNAMENT_PAUSED


def apply_resumed(state: TournamentState, _event: tournament.TournamentResumed) -> None:
    """Apply TournamentResumed event to state."""
    state.status = tournament.TournamentStatus.TOURNAMENT_RUNNING


def apply_started(state: TournamentState, _event: tournament.TournamentStarted) -> None:
    """Apply TournamentStarted event to state."""
    state.status = tournament.TournamentStatus.TOURNAMENT_RUNNING


def apply_completed(
    state: TournamentState, _event: tournament.TournamentCompleted
) -> None:
    """Apply TournamentCompleted event to state."""
    state.status = tournament.TournamentStatus.TOURNAMENT_COMPLETED


def build_state(state: TournamentState, events: list) -> TournamentState:
    """Build state from a list of Any-wrapped events.

    Args:
        state: Initial state to mutate.
        events: List of Any-wrapped protobuf events.

    Returns:
        The mutated state.
    """
    from google.protobuf.any_pb2 import Any as AnyProto

    _appliers = {
        "angzarr_client.proto.examples.TournamentCreated": (
            tournament.TournamentCreated,
            apply_created,
        ),
        "angzarr_client.proto.examples.RegistrationOpened": (
            tournament.RegistrationOpened,
            apply_registration_opened,
        ),
        "angzarr_client.proto.examples.RegistrationClosed": (
            tournament.RegistrationClosed,
            apply_registration_closed,
        ),
        "angzarr_client.proto.examples.TournamentPlayerEnrolled": (
            tournament.TournamentPlayerEnrolled,
            apply_player_enrolled,
        ),
        "angzarr_client.proto.examples.TournamentEnrollmentRejected": (
            tournament.TournamentEnrollmentRejected,
            apply_enrollment_rejected,
        ),
        "angzarr_client.proto.examples.RebuyProcessed": (
            tournament.RebuyProcessed,
            apply_rebuy_processed,
        ),
        "angzarr_client.proto.examples.RebuyDenied": (
            tournament.RebuyDenied,
            apply_rebuy_denied,
        ),
        "angzarr_client.proto.examples.BlindLevelAdvanced": (
            tournament.BlindLevelAdvanced,
            apply_blind_advanced,
        ),
        "angzarr_client.proto.examples.PlayerEliminated": (
            tournament.PlayerEliminated,
            apply_player_eliminated,
        ),
        "angzarr_client.proto.examples.TournamentPaused": (
            tournament.TournamentPaused,
            apply_paused,
        ),
        "angzarr_client.proto.examples.TournamentResumed": (
            tournament.TournamentResumed,
            apply_resumed,
        ),
        "angzarr_client.proto.examples.TournamentStarted": (
            tournament.TournamentStarted,
            apply_started,
        ),
        "angzarr_client.proto.examples.TournamentCompleted": (
            tournament.TournamentCompleted,
            apply_completed,
        ),
    }

    for event_any in events:
        if not isinstance(event_any, AnyProto):
            continue
        # Extract type name from type_url
        type_name = event_any.type_url.split("/")[-1]
        if type_name in _appliers:
            proto_cls, applier = _appliers[type_name]
            event = proto_cls()
            event_any.Unpack(event)
            applier(state, event)

    return state
