"""Tournament state rebuild helper for Registration PM.

Replaces the former StateRouter-based builder with a plain rebuild function.

Usage:
    state = TournamentStateHelper()
    for event in events:
        state = tournament_state_rebuild(state, event)
"""

from dataclasses import dataclass, field

from angzarr_client.proto.examples import tournament_pb2 as tournament


@dataclass
class TournamentStateHelper:
    """Minimal tournament state for PM validation."""

    status: int = tournament.TournamentStatus.TOURNAMENT_STATUS_UNSPECIFIED
    registration_open: bool = True
    max_players: int = 0
    registered_count: int = 0
    buy_in: int = 0
    starting_stack: int = 0
    registered_players: set[str] = field(default_factory=set)  # hex player roots
    rebuy_allowed: bool = False
    rebuy_cost: int = 0
    rebuy_chips: int = 0


# --- State appliers (pure functions) ---


def apply_tournament_created(
    state: TournamentStateHelper, event: tournament.TournamentCreated
) -> None:
    """Apply TournamentCreated event."""
    state.status = tournament.TournamentStatus.TOURNAMENT_CREATED
    state.max_players = event.max_players
    state.buy_in = event.buy_in
    state.starting_stack = event.starting_stack
    state.registration_open = True
    if event.HasField("rebuy_config"):
        state.rebuy_allowed = event.rebuy_config.enabled
        state.rebuy_cost = event.rebuy_config.rebuy_cost
        state.rebuy_chips = event.rebuy_config.rebuy_chips


def apply_registration_opened(
    state: TournamentStateHelper, event: tournament.RegistrationOpened
) -> None:
    """Apply RegistrationOpened event."""
    state.status = tournament.TournamentStatus.TOURNAMENT_REGISTRATION_OPEN
    state.registration_open = True


def apply_registration_closed(
    state: TournamentStateHelper, event: tournament.RegistrationClosed
) -> None:
    """Apply RegistrationClosed event."""
    state.registration_open = False


def apply_tournament_started(
    state: TournamentStateHelper, event: tournament.TournamentStarted
) -> None:
    """Apply TournamentStarted event."""
    state.status = tournament.TournamentStatus.TOURNAMENT_RUNNING
    state.registration_open = False


def apply_player_enrolled(
    state: TournamentStateHelper, event: tournament.TournamentPlayerEnrolled
) -> None:
    """Apply TournamentPlayerEnrolled event."""
    state.registered_players.add(event.player_root.hex())
    state.registered_count = len(state.registered_players)


def tournament_state_rebuild(
    prior_state: TournamentStateHelper, event
) -> TournamentStateHelper:
    """Rebuild ``TournamentStateHelper`` by applying ``event`` to ``prior_state``.

    Mutates and returns the state for chaining.
    """
    if isinstance(event, tournament.TournamentCreated):
        apply_tournament_created(prior_state, event)
    elif isinstance(event, tournament.RegistrationOpened):
        apply_registration_opened(prior_state, event)
    elif isinstance(event, tournament.RegistrationClosed):
        apply_registration_closed(prior_state, event)
    elif isinstance(event, tournament.TournamentStarted):
        apply_tournament_started(prior_state, event)
    elif isinstance(event, tournament.TournamentPlayerEnrolled):
        apply_player_enrolled(prior_state, event)
    return prior_state


def tournament_state_from_event_book(event_book) -> TournamentStateHelper:
    """Rebuild a ``TournamentStateHelper`` from an ``EventBook`` proto.

    Unpacks each event page into its proto message based on the type URL and
    folds it into the state.
    """
    state = TournamentStateHelper()
    _type_map = {
        "examples.TournamentCreated": tournament.TournamentCreated,
        "examples.RegistrationOpened": tournament.RegistrationOpened,
        "examples.RegistrationClosed": tournament.RegistrationClosed,
        "examples.TournamentStarted": tournament.TournamentStarted,
        "examples.TournamentPlayerEnrolled": tournament.TournamentPlayerEnrolled,
    }
    for page in event_book.pages:
        if not page.HasField("event"):
            continue
        type_name = page.event.type_url.split("/")[-1]
        proto_cls = _type_map.get(type_name)
        if proto_cls is None:
            continue
        evt = proto_cls()
        page.event.Unpack(evt)
        tournament_state_rebuild(state, evt)
    return state
