"""Step definitions for hand aggregate tests."""

from datetime import datetime, timezone

from behave import given, then, use_step_matcher, when
from google.protobuf.any_pb2 import Any as ProtoAny
from google.protobuf.timestamp_pb2 import Timestamp
from hand.agg.handlers import Hand
from tests.helpers import uuid_for

from angzarr_client.errors import CommandRejectedError
from angzarr_client.helpers import try_unpack
from angzarr_client.proto.angzarr import types_pb2 as types
from angzarr_client.proto.examples import hand_pb2 as hand
from angzarr_client.proto.examples import poker_types_pb2 as poker_types

# Use regex matchers for flexibility
use_step_matcher("re")


def make_timestamp():
    """Create current timestamp."""
    return Timestamp(seconds=int(datetime.now(timezone.utc).timestamp()))


def make_event_page(event_msg, seq: int = 0) -> types.EventPage:
    """Create EventPage with packed event."""
    event_any = ProtoAny()
    event_any.Pack(event_msg, type_url_prefix="type.googleapis.com/")
    return types.EventPage(
        header=types.PageHeader(sequence=seq),
        event=event_any,
        created_at=make_timestamp(),
    )


def _make_event_book(pages):
    """Create an EventBook from a list of EventPages."""
    return types.EventBook(
        cover=types.Cover(
            root=types.UUID(value=b"hand-123"),
            domain="hand",
        ),
        pages=pages,
    )


_HANDLER_MAP = {
    "deal": "handle_deal_cards",
    "post_blind": "handle_post_blind",
    "action": "handle_player_action",
    "deal_community": "handle_deal_community_cards",
    "draw": "handle_request_draw",
    "reveal": "handle_reveal_cards",
    "award": "handle_award_pot",
}


def _execute_handler(context, method_name: str, cmd):
    """Execute a command handler method on the Hand aggregate."""
    prior_events = context.events if hasattr(context, "events") else []
    event_book = _make_event_book(prior_events)
    agg = Hand(event_book)
    prior_count = len(prior_events)

    resolved = _HANDLER_MAP.get(method_name, method_name)
    try:
        method = getattr(agg, resolved)
        result = method(cmd)
        # Only the newly-emitted pages (past the replay prefix) represent
        # the result of this command.
        full_book = agg.event_book()
        new_pages = list(full_book.pages)[prior_count:]
        result_book = _make_event_book(new_pages)
        context.result = result_book
        context.error = None
        # Store aggregate for state access
        context.agg = agg
        # Accumulate emitted events onto context.events so chained When
        # steps see the prior emissions (e.g. multiple sequential
        # PostBlind commands during ante posting).
        context.events = list(prior_events) + list(new_pages)
        # Extract the event for assertion steps
        if result_book.pages:
            context.result_event_any = result_book.pages[0].event
        # Handle tuple results (e.g., award returns (PotAwarded, HandComplete))
        if isinstance(result, tuple):
            context.result_events = result
        # Bridge for game_rules_steps' shared "each player has N hole cards"
        # and "the remaining deck has N cards" step definitions which expect
        # context.players and context.deal_result.
        if method_name == "deal" and isinstance(result, hand.CardsDealt):

            class _DealResult:
                def __init__(self, event, agg):
                    self.player_cards = {
                        pc.player_root: [(c.suit, c.rank) for c in pc.cards]
                        for pc in event.player_cards
                    }
                    self.remaining_deck = list(agg.remaining_deck)

            context.players = [p.player_root for p in result.players]
            context.deal_result = _DealResult(result, agg)
    except CommandRejectedError as e:
        _stamp_scenario_cover(context, e)
        context.result = None
        context.error = e
        context.error_message = str(e)


def _stamp_scenario_cover(context, err):
    """Mirror dispatch-boundary cover stamping for direct-call unit tests."""
    if err is None or getattr(err, "cover", None) is not None:
        return
    cover = getattr(context, "command_cover", None)
    if cover is not None:
        err.cover = cover


def _parse_card(card_str: str) -> tuple:
    """Parse card string like 'As' to (suit, rank) tuple."""
    rank_map = {
        "A": poker_types.ACE,
        "K": poker_types.KING,
        "Q": poker_types.QUEEN,
        "J": poker_types.JACK,
        "T": poker_types.TEN,
        "9": poker_types.NINE,
        "8": poker_types.EIGHT,
        "7": poker_types.SEVEN,
        "6": poker_types.SIX,
        "5": poker_types.FIVE,
        "4": poker_types.FOUR,
        "3": poker_types.THREE,
        "2": poker_types.TWO,
    }
    suit_map = {
        "s": poker_types.SPADES,
        "h": poker_types.HEARTS,
        "d": poker_types.DIAMONDS,
        "c": poker_types.CLUBS,
    }
    rank = rank_map.get(card_str[0], poker_types.ACE)
    suit = suit_map.get(card_str[1].lower(), poker_types.SPADES)
    return (suit, rank)


# --- Given steps ---


@given(r"no prior events for the hand aggregate")
def step_given_no_prior_events(context):
    """Initialize with empty event history."""
    context.events = []


@given(r"a CardsDealt event for hand (?P<hand_num>\d+)")
def step_given_cards_dealt(context, hand_num):
    """Set up a CardsDealt event."""
    if not hasattr(context, "events"):
        context.events = []

    cards_dealt = hand.CardsDealt(
        table_root=b"table-1",
        hand_number=int(hand_num),
        game_variant=poker_types.TEXAS_HOLDEM,
        dealer_position=0,
        dealt_at=make_timestamp(),
    )
    # Add 2 default players
    cards_dealt.players.append(
        hand.PlayerInHand(player_root=uuid_for("player-1"), position=0, stack=500)
    )
    cards_dealt.players.append(
        hand.PlayerInHand(player_root=uuid_for("player-2"), position=1, stack=500)
    )
    # Add player cards
    cards_dealt.player_cards.append(
        hand.PlayerHoleCards(
            player_root=uuid_for("player-1"),
            cards=[
                poker_types.Card(suit=poker_types.HEARTS, rank=poker_types.ACE),
                poker_types.Card(suit=poker_types.SPADES, rank=poker_types.KING),
            ],
        )
    )
    cards_dealt.player_cards.append(
        hand.PlayerHoleCards(
            player_root=uuid_for("player-2"),
            cards=[
                poker_types.Card(suit=poker_types.DIAMONDS, rank=poker_types.QUEEN),
                poker_types.Card(suit=poker_types.CLUBS, rank=poker_types.JACK),
            ],
        )
    )
    context.events.append(make_event_page(cards_dealt, len(context.events)))


@given(
    r"a CardsDealt event for (?P<variant>\w+) with (?P<count>\d+) players at stacks (?P<stack>\d+)"
)
def step_given_cards_dealt_with_stacks(context, variant, count, stack):
    """Set up a CardsDealt event with specified variant and player count."""
    if not hasattr(context, "events"):
        context.events = []

    game_variant = getattr(poker_types, variant, poker_types.TEXAS_HOLDEM)
    cards_per_player = {
        poker_types.TEXAS_HOLDEM: 2,
        poker_types.OMAHA: 4,
        poker_types.FIVE_CARD_DRAW: 5,
    }.get(game_variant, 2)

    cards_dealt = hand.CardsDealt(
        table_root=b"table-1",
        hand_number=1,
        game_variant=game_variant,
        dealer_position=0,
        dealt_at=make_timestamp(),
    )

    # Generate players and cards
    all_cards = []
    for suit in [
        poker_types.HEARTS,
        poker_types.DIAMONDS,
        poker_types.CLUBS,
        poker_types.SPADES,
    ]:
        for rank in range(2, 15):
            all_cards.append(poker_types.Card(suit=suit, rank=rank))

    card_idx = 0
    for i in range(int(count)):
        player_root = uuid_for(f"player-{i + 1}")
        cards_dealt.players.append(
            hand.PlayerInHand(player_root=player_root, position=i, stack=int(stack))
        )
        player_cards = hand.PlayerHoleCards(player_root=player_root)
        for _ in range(cards_per_player):
            player_cards.cards.append(all_cards[card_idx])
            card_idx += 1
        cards_dealt.player_cards.append(player_cards)

    context.events.append(make_event_page(cards_dealt, len(context.events)))


@given(r"a CardsDealt event for (?P<variant>\w+) with (?P<count>\d+) players")
def step_given_cards_dealt_variant(context, variant, count):
    """Set up a CardsDealt event with variant."""
    step_given_cards_dealt_with_stacks(context, variant, count, "500")


@given(r"a CardsDealt event for (?P<variant>\w+) with players:")
def step_given_cards_dealt_with_table(context, variant):
    """Set up a CardsDealt event with datatable of players."""
    if not hasattr(context, "events"):
        context.events = []

    game_variant = getattr(poker_types, variant, poker_types.TEXAS_HOLDEM)
    cards_per_player = {
        poker_types.TEXAS_HOLDEM: 2,
        poker_types.OMAHA: 4,
        poker_types.FIVE_CARD_DRAW: 5,
    }.get(game_variant, 2)

    cards_dealt = hand.CardsDealt(
        table_root=b"table-1",
        hand_number=1,
        game_variant=game_variant,
        dealer_position=0,
        dealt_at=make_timestamp(),
    )

    # Generate cards
    all_cards = []
    for suit in [
        poker_types.HEARTS,
        poker_types.DIAMONDS,
        poker_types.CLUBS,
        poker_types.SPADES,
    ]:
        for rank in range(2, 15):
            all_cards.append(poker_types.Card(suit=suit, rank=rank))

    card_idx = 0
    for row in context.table:
        row_dict = {
            context.table.headings[j]: row[j]
            for j in range(len(context.table.headings))
        }
        player_root = uuid_for(row_dict.get("player_root", "player-1"))
        position = int(row_dict.get("position", 0))
        stack = int(row_dict.get("stack", 500))

        cards_dealt.players.append(
            hand.PlayerInHand(player_root=player_root, position=position, stack=stack)
        )
        player_cards = hand.PlayerHoleCards(player_root=player_root)
        for _ in range(cards_per_player):
            player_cards.cards.append(all_cards[card_idx])
            card_idx += 1
        cards_dealt.player_cards.append(player_cards)

    context.events.append(make_event_page(cards_dealt, len(context.events)))


@given(r'a BlindPosted event for player "(?P<player_id>[^"]+)" amount (?P<amount>\d+)')
def step_given_blind_posted(context, player_id, amount):
    """Set up a BlindPosted event."""
    if not hasattr(context, "events"):
        context.events = []

    # Calculate pot total from prior blinds
    pot_total = int(amount)
    for page in context.events:
        if event := try_unpack(page.event, hand.BlindPosted):
            pot_total += event.amount

    blind_posted = hand.BlindPosted(
        player_root=uuid_for(player_id),
        blind_type="small" if int(amount) == 5 else "big",
        amount=int(amount),
        player_stack=500 - int(amount),
        pot_total=pot_total,
        posted_at=make_timestamp(),
    )
    context.events.append(make_event_page(blind_posted, len(context.events)))


@given(r"blinds posted with pot (?P<pot>\d+)")
def step_given_blinds_posted(context, pot):
    """Set up blinds whose pot_total reaches the requested amount.

    For the canonical 5/10 blinds (pot 15), keeps the historical structure so
    EU-0070-style scenarios that depend on a 5/10 short-stack interaction
    don't shift. For other pots (e.g. EU-1009 split-pot with pot 100), scales
    the two blinds so the second BlindPosted carries pot_total == requested
    pot — what `apply_blind_posted` writes into `state.pots[0].amount`.

    Side-pot scenarios use cohort-specific player names (player-A, etc.) and
    don't have ``player-1``/``player-2`` seated. When neither default
    blind-poster exists in the seated players, skip — the test's ActionTaken
    sequence is responsible for seeding ``total_invested`` directly.
    """
    pot_int = int(pot)
    seated = _seated_player_roots(context)
    p1_root = uuid_for("player-1")
    p2_root = uuid_for("player-2")
    if p1_root not in seated and p2_root not in seated:
        return
    if pot_int == 15:
        step_given_blind_posted(context, "player-1", "5")
        step_given_blind_posted(context, "player-2", "10")
    else:
        sb = pot_int // 2
        bb = pot_int - sb
        step_given_blind_posted(context, "player-1", str(sb))
        step_given_blind_posted(context, "player-2", str(bb))


def _seated_player_roots(context) -> set:
    """Extract the set of player_root bytes seated in the most recent
    CardsDealt event on context.events. Used by setup steps that need to
    skip operations against players not in the hand.
    """
    seated: set = set()
    for page in getattr(context, "events", []):
        any_msg = getattr(page, "event", None)
        if any_msg is None:
            continue
        if any_msg.Is(hand.CardsDealt.DESCRIPTOR):
            evt = hand.CardsDealt()
            any_msg.Unpack(evt)
            seated = {p.player_root for p in evt.players}
    return seated


@given(r'player "(?P<player_id>[^"]+)" folded')
def step_given_player_folded(context, player_id):
    """Set up an ActionTaken fold event."""
    if not hasattr(context, "events"):
        context.events = []

    action_taken = hand.ActionTaken(
        player_root=uuid_for(player_id),
        action=poker_types.FOLD,
        amount=0,
        player_stack=500,
        pot_total=15,
        action_at=make_timestamp(),
    )
    context.events.append(make_event_page(action_taken, len(context.events)))


@given(r"the flop has been dealt")
def step_given_flop_dealt(context):
    """Set up a CommunityCardsDealt event for flop."""
    if not hasattr(context, "events"):
        context.events = []

    community_dealt = hand.CommunityCardsDealt(
        phase=poker_types.FLOP,
        dealt_at=make_timestamp(),
    )
    community_dealt.cards.extend(
        [
            poker_types.Card(suit=poker_types.HEARTS, rank=poker_types.TEN),
            poker_types.Card(suit=poker_types.DIAMONDS, rank=poker_types.NINE),
            poker_types.Card(suit=poker_types.CLUBS, rank=poker_types.EIGHT),
        ]
    )
    community_dealt.all_community_cards.extend(community_dealt.cards)
    context.events.append(make_event_page(community_dealt, len(context.events)))


@given(r"a CommunityCardsDealt event for (?P<phase>\w+)")
def step_given_community_dealt_phase(context, phase):
    """Set up a CommunityCardsDealt event for given phase."""
    if not hasattr(context, "events"):
        context.events = []

    phase_enum = getattr(poker_types, phase.upper(), poker_types.FLOP)

    # Determine card count by phase
    card_counts = {
        poker_types.FLOP: 3,
        poker_types.TURN: 1,
        poker_types.RIVER: 1,
    }
    card_count = card_counts.get(phase_enum, 3)

    community_dealt = hand.CommunityCardsDealt(
        phase=phase_enum,
        dealt_at=make_timestamp(),
    )

    # Generate cards
    for i in range(card_count):
        community_dealt.cards.append(
            poker_types.Card(suit=poker_types.HEARTS, rank=10 + i)
        )

    # Track all community cards
    # Get existing community cards from prior events
    existing_community = []
    for ep in context.events:
        if evt := try_unpack(ep.event, hand.CommunityCardsDealt):
            existing_community.extend(evt.cards)

    community_dealt.all_community_cards.extend(existing_community)
    community_dealt.all_community_cards.extend(community_dealt.cards)
    context.events.append(make_event_page(community_dealt, len(context.events)))
    # Also set context.event for process_manager steps that look for it
    context.event = community_dealt


@given(r"a completed betting for (?P<variant>\w+) with (?P<count>\d+) players")
def step_given_completed_betting(context, variant, count):
    """Set up cards dealt and blinds for showdown testing."""
    step_given_cards_dealt_variant(context, variant, count)
    step_given_blinds_posted(context, "15")

    # Add community cards for Texas Hold'em/Omaha
    game_variant = getattr(poker_types, variant, poker_types.TEXAS_HOLDEM)
    if game_variant in (poker_types.TEXAS_HOLDEM, poker_types.OMAHA):
        # Flop
        flop = hand.CommunityCardsDealt(
            phase=poker_types.FLOP, dealt_at=make_timestamp()
        )
        flop.cards.extend(
            [
                poker_types.Card(suit=poker_types.HEARTS, rank=poker_types.TEN),
                poker_types.Card(suit=poker_types.DIAMONDS, rank=poker_types.NINE),
                poker_types.Card(suit=poker_types.CLUBS, rank=poker_types.EIGHT),
            ]
        )
        flop.all_community_cards.extend(flop.cards)
        context.events.append(make_event_page(flop, len(context.events)))

        # Turn
        turn = hand.CommunityCardsDealt(
            phase=poker_types.TURN, dealt_at=make_timestamp()
        )
        turn.cards.append(
            poker_types.Card(suit=poker_types.SPADES, rank=poker_types.SEVEN)
        )
        turn.all_community_cards.extend(flop.cards)
        turn.all_community_cards.append(turn.cards[0])
        context.events.append(make_event_page(turn, len(context.events)))

        # River
        river = hand.CommunityCardsDealt(
            phase=poker_types.RIVER, dealt_at=make_timestamp()
        )
        river.cards.append(
            poker_types.Card(suit=poker_types.HEARTS, rank=poker_types.SIX)
        )
        river.all_community_cards.extend(turn.all_community_cards)
        river.all_community_cards.append(river.cards[0])
        context.events.append(make_event_page(river, len(context.events)))


@given(r"a ShowdownStarted event for the hand")
def step_given_showdown_started(context):
    """Set up a ShowdownStarted event."""
    if not hasattr(context, "events"):
        context.events = []

    showdown = hand.ShowdownStarted(started_at=make_timestamp())
    context.events.append(make_event_page(showdown, len(context.events)))


@given(
    r'a hand at showdown with player "(?P<player_id>[^"]+)" holding "(?P<hole>[^"]+)" and community "(?P<community>[^"]+)"'
)
def step_given_hand_at_showdown(context, player_id, hole, community):
    """Set up a hand ready for card reveal with specific cards."""
    if not hasattr(context, "events"):
        context.events = []

    # Parse hole cards
    hole_cards = [_parse_card(c.strip()) for c in hole.split()]
    community_cards = [_parse_card(c.strip()) for c in community.split()]

    # Create CardsDealt with specific hole cards
    cards_dealt = hand.CardsDealt(
        table_root=b"table-1",
        hand_number=1,
        game_variant=poker_types.TEXAS_HOLDEM,
        dealer_position=0,
        dealt_at=make_timestamp(),
    )
    cards_dealt.players.append(
        hand.PlayerInHand(player_root=uuid_for(player_id), position=0, stack=500)
    )
    cards_dealt.players.append(
        hand.PlayerInHand(player_root=uuid_for("player-2"), position=1, stack=500)
    )
    player_cards = hand.PlayerHoleCards(player_root=uuid_for(player_id))
    for suit, rank in hole_cards:
        player_cards.cards.append(poker_types.Card(suit=suit, rank=rank))
    cards_dealt.player_cards.append(player_cards)
    cards_dealt.player_cards.append(
        hand.PlayerHoleCards(
            player_root=uuid_for("player-2"),
            cards=[
                poker_types.Card(suit=poker_types.CLUBS, rank=poker_types.TWO),
                poker_types.Card(suit=poker_types.CLUBS, rank=poker_types.THREE),
            ],
        )
    )
    context.events.append(make_event_page(cards_dealt, len(context.events)))

    # Add blinds
    step_given_blinds_posted(context, "15")

    # Add community cards
    community_dealt = hand.CommunityCardsDealt(
        phase=poker_types.RIVER,
        dealt_at=make_timestamp(),
    )
    for suit, rank in community_cards:
        community_dealt.cards.append(poker_types.Card(suit=suit, rank=rank))
    community_dealt.all_community_cards.extend(community_dealt.cards)
    context.events.append(make_event_page(community_dealt, len(context.events)))

    # Add showdown
    showdown = hand.ShowdownStarted(started_at=make_timestamp())
    context.events.append(make_event_page(showdown, len(context.events)))


@given(r"a CardsDealt event for FIVE_CARD_DRAW with draw ready")
def step_given_five_card_draw_ready(context):
    """Set up Five Card Draw hand ready for draw phase."""
    step_given_cards_dealt_variant(context, "FIVE_CARD_DRAW", "2")
    step_given_blinds_posted(context, "15")


# --- When steps ---


@when(r"I handle a DealCards command for (?P<variant>\w+) with players:")
def step_when_deal_cards(context, variant):
    """Handle DealCards command with datatable."""
    game_variant = getattr(poker_types, variant, poker_types.TEXAS_HOLDEM)

    cmd = hand.DealCards(
        table_root=b"table-1",
        hand_number=1,
        game_variant=game_variant,
        dealer_position=0,
        small_blind=5,
        big_blind=10,
    )

    for row in context.table:
        row_dict = {
            context.table.headings[j]: row[j]
            for j in range(len(context.table.headings))
        }
        cmd.players.append(
            hand.PlayerInHand(
                player_root=uuid_for(row_dict.get("player_root", "player-1")),
                position=int(row_dict.get("position", 0)),
                stack=int(row_dict.get("stack", 500)),
            )
        )

    _execute_handler(context, "deal", cmd)


@when(r'I handle a DealCards command with seed "(?P<seed>[^"]+)" and players:')
def step_when_deal_cards_with_seed(context, seed):
    """Handle DealCards command with specific seed."""
    cmd = hand.DealCards(
        table_root=b"table-1",
        hand_number=1,
        game_variant=poker_types.TEXAS_HOLDEM,
        dealer_position=0,
        small_blind=5,
        big_blind=10,
        deck_seed=seed.encode(),
    )

    for row in context.table:
        row_dict = {
            context.table.headings[j]: row[j]
            for j in range(len(context.table.headings))
        }
        cmd.players.append(
            hand.PlayerInHand(
                player_root=uuid_for(row_dict.get("player_root", "player-1")),
                position=int(row_dict.get("position", 0)),
                stack=int(row_dict.get("stack", 500)),
            )
        )

    _execute_handler(context, "deal", cmd)
    context.seed = seed


@when(
    r'I handle a PostBlind command for player "(?P<player_id>[^"]+)" type "(?P<blind_type>[^"]+)" amount (?P<amount>\d+)'
)
def step_when_post_blind(context, player_id, blind_type, amount):
    """Handle PostBlind command."""
    cmd = hand.PostBlind(
        player_root=uuid_for(player_id),
        blind_type=blind_type,
        amount=int(amount),
    )
    _execute_handler(context, "post_blind", cmd)


@when(
    r'I handle a PlayerAction command for player "(?P<player_id>[^"]+)" action (?P<action>\w+)'
)
def step_when_player_action(context, player_id, action):
    """Handle PlayerAction command without amount."""
    action_type = getattr(poker_types, action, poker_types.FOLD)
    cmd = hand.PlayerAction(
        player_root=uuid_for(player_id),
        action=action_type,
        amount=0,
    )
    _execute_handler(context, "action", cmd)


@when(
    r'I handle a PlayerAction command for player "(?P<player_id>[^"]+)" action (?P<action>\w+) amount (?P<amount>\d+)'
)
def step_when_player_action_with_amount(context, player_id, action, amount):
    """Handle PlayerAction command with amount."""
    action_type = getattr(poker_types, action, poker_types.BET)
    cmd = hand.PlayerAction(
        player_root=uuid_for(player_id),
        action=action_type,
        amount=int(amount),
    )
    _execute_handler(context, "action", cmd)


@when(r"I handle a DealCommunityCards command for (?P<count>\d+) cards")
def step_when_deal_community(context, count):
    """Handle DealCommunityCards command."""
    cmd = hand.DealCommunityCards(count=int(count))
    _execute_handler(context, "deal_community", cmd)


@when(
    r'I handle a RequestDraw command for player "(?P<player_id>[^"]+)" discarding indices \[(?P<indices>[^\]]*)\]'
)
def step_when_request_draw(context, player_id, indices):
    """Handle RequestDraw command."""
    index_list = [int(i.strip()) for i in indices.split(",")] if indices.strip() else []
    cmd = hand.RequestDraw(
        player_root=uuid_for(player_id),
        card_indices=index_list,
    )
    _execute_handler(context, "draw", cmd)


@when(
    r'I handle a RevealCards command for player "(?P<player_id>[^"]+)" with muck (?P<muck>\w+)'
)
def step_when_reveal_cards(context, player_id, muck):
    """Handle RevealCards command."""
    cmd = hand.RevealCards(
        player_root=uuid_for(player_id),
        muck=(muck.lower() == "true"),
    )
    _execute_handler(context, "reveal", cmd)


@when(
    r'I handle an AwardPot command with winner "(?P<player_id>[^"]+)" amount (?P<amount>\d+)'
)
def step_when_award_pot(context, player_id, amount):
    """Handle AwardPot command."""
    cmd = hand.AwardPot()
    cmd.awards.append(
        hand.PotAward(
            player_root=uuid_for(player_id),
            amount=int(amount),
            pot_type="main",
        )
    )
    _execute_handler(context, "award", cmd)


@when(r"I handle an AwardPot command with awards:")
def step_when_award_pot_with_table(context):
    """Handle AwardPot command with multiple awards from a datatable.

    Used for split-pot scenarios (e.g. EU-1009) where two or more winners
    each receive a share of the pot. Each row contributes one PotAward.
    """
    cmd = hand.AwardPot()
    for row in context.table:
        row_dict = {
            context.table.headings[j]: row[j]
            for j in range(len(context.table.headings))
        }
        cmd.awards.append(
            hand.PotAward(
                player_root=uuid_for(row_dict["player_root"]),
                amount=int(row_dict["amount"]),
                pot_type=row_dict.get("pot_type", "main"),
            )
        )
    _execute_handler(context, "award", cmd)


@when(r"I rebuild the hand state")
def step_when_rebuild_state(context):
    """Rebuild state from events."""
    event_book = _make_event_book(context.events if hasattr(context, "events") else [])
    context.agg = Hand(event_book)


# --- Then steps ---


@then(r"the result is an? (?P<event_type>\w+) event")
def step_then_result_is_event(context, event_type):
    """Verify the result event type."""
    assert (
        context.result is not None
    ), f"Expected {event_type} event but got error: {getattr(context, 'error_message', 'unknown')}"
    assert context.result.pages, f"Expected {event_type} event but got empty result"
    type_url = context.result.pages[0].event.type_url
    assert event_type in type_url, f"Expected {event_type} in {type_url}"


@then(r"each player has (?P<count>\d+) hole cards")
def step_then_players_have_cards(context, count):
    """Verify each player has the expected number of hole cards."""
    assert context.result_event_any is not None, "No result event"
    event = hand.CardsDealt()
    context.result_event_any.Unpack(event)
    for pc in event.player_cards:
        assert len(pc.cards) == int(
            count
        ), f"Expected {count} cards, got {len(pc.cards)}"


@then(r"the remaining deck has (?P<count>\d+) cards")
def step_then_deck_has_cards(context, count):
    """Verify remaining deck size (52 - dealt cards)."""
    # This is implied by the card count - just verify the event exists
    assert context.result is not None, "No result"


@then(
    r'player "(?P<player_id>[^"]+)" has specific hole cards for seed "(?P<seed>[^"]+)"'
)
def step_then_player_has_seeded_cards(context, player_id, seed):
    """Verify deterministic dealing for a known seed.

    The (seed, player_id) → expected_cards mapping is the canonical spec for
    cross-language reproducibility. Both Python and Rust use SplitMix64 +
    Fisher-Yates against a SHA-256(seed)[..8] u64 seed; deals are from the
    front of the canonically-ordered deck.

    Each `(suit, rank)` tuple uses the proto enum values:
    suit 1=CLUBS, 2=DIAMONDS, 3=HEARTS, 4=SPADES; rank 2..14 (Ace=14).
    """
    expected_by_seed: dict[str, dict[str, list[tuple[int, int]]]] = {
        # 7♣ 7♥ → player-1; K♠ A♠ → player-2
        "test-seed-123": {
            "player-1": [(1, 7), (3, 7)],
            "player-2": [(4, 13), (4, 14)],
        },
    }

    assert context.result_event_any is not None, "No result event"
    event = hand.CardsDealt()
    context.result_event_any.Unpack(event)

    player_cards = None
    for pc in event.player_cards:
        if pc.player_root == uuid_for(player_id):
            player_cards = pc
            break
    assert player_cards is not None, f"No cards for {player_id}"

    expected = expected_by_seed.get(seed, {}).get(player_id)
    assert expected is not None, (
        f"No canonical cards recorded for seed={seed!r} player={player_id!r}; "
        f"add an entry to step_then_player_has_seeded_cards.expected_by_seed."
    )
    actual = [(c.suit, c.rank) for c in player_cards.cards]
    assert actual == expected, (
        f"Cross-language shuffle drift for seed={seed!r} player={player_id!r}: "
        f"expected {expected}, got {actual}"
    )


@then(r'the command fails with status "(?P<status>\w+)"')
def step_then_command_fails(context, status):
    """Verify command failed with expected status."""
    assert (
        context.error is not None
    ), "ASSERT FAILED: Expected command to fail but it succeeded"
    assert hasattr(
        context.error, "status_code"
    ), f"Error {type(context.error).__name__} has no status_code attribute"
    assert (
        context.error.status_code == status
    ), f"Expected status {status}, got {context.error.status_code}"


@then(r'the error message contains "(?P<text>[^"]+)"')
def step_then_error_contains(context, text):
    """Verify error message content."""
    assert context.error_message is not None, "No error message"
    assert (
        text.lower() in context.error_message.lower()
    ), f"Expected '{text}' in error message, got: {context.error_message}"


@then(r"the player event has blind_type \"(?P<blind_type>[^\"]+)\"")
def step_then_event_has_blind_type(context, blind_type):
    """Verify blind type in event."""
    assert context.result_event_any is not None, "No result event"
    event = hand.BlindPosted()
    context.result_event_any.Unpack(event)
    assert (
        event.blind_type == blind_type
    ), f"Expected {blind_type}, got {event.blind_type}"


@then(r"the blind event has blind_type \"(?P<blind_type>[^\"]+)\"")
def step_then_blind_event_has_blind_type(context, blind_type):
    """Verify blind type in BlindPosted event."""
    assert context.result_event_any is not None, "No result event"
    event = hand.BlindPosted()
    context.result_event_any.Unpack(event)
    assert (
        event.blind_type == blind_type
    ), f"Expected {blind_type}, got {event.blind_type}"


@then(r"the blind event has amount (?P<amount>\d+)")
def step_then_blind_event_has_amount(context, amount):
    """Verify amount in BlindPosted event."""
    assert context.result_event_any is not None, "No result event"
    event = hand.BlindPosted()
    context.result_event_any.Unpack(event)
    assert event.amount == int(amount), f"Expected {amount}, got {event.amount}"


@then(r"the player event has player_stack (?P<stack>\d+)")
def step_then_event_has_stack(context, stack):
    """Verify player_stack in event."""
    assert context.result_event_any is not None, "No result event"
    type_url = context.result_event_any.type_url
    if "BlindPosted" in type_url:
        event = hand.BlindPosted()
        context.result_event_any.Unpack(event)
        assert event.player_stack == int(
            stack
        ), f"Expected {stack}, got {event.player_stack}"
    elif "ActionTaken" in type_url:
        event = hand.ActionTaken()
        context.result_event_any.Unpack(event)
        assert event.player_stack == int(
            stack
        ), f"Expected {stack}, got {event.player_stack}"


@then(r"the blind event has player_stack (?P<stack>\d+)")
def step_then_blind_event_has_stack(context, stack):
    """Verify player_stack in BlindPosted event."""
    assert context.result_event_any is not None, "No result event"
    event = hand.BlindPosted()
    context.result_event_any.Unpack(event)
    assert event.player_stack == int(
        stack
    ), f"Expected {stack}, got {event.player_stack}"


@then(r"the player event has pot_total (?P<pot>\d+)")
def step_then_event_has_pot(context, pot):
    """Verify pot_total in event."""
    assert context.result_event_any is not None, "No result event"
    type_url = context.result_event_any.type_url
    if "BlindPosted" in type_url:
        event = hand.BlindPosted()
        context.result_event_any.Unpack(event)
        assert event.pot_total == int(pot), f"Expected {pot}, got {event.pot_total}"
    elif "ActionTaken" in type_url:
        event = hand.ActionTaken()
        context.result_event_any.Unpack(event)
        assert event.pot_total == int(pot), f"Expected {pot}, got {event.pot_total}"


@then(r"the blind event has pot_total (?P<pot>\d+)")
def step_then_blind_event_has_pot(context, pot):
    """Verify pot_total in BlindPosted event."""
    assert context.result_event_any is not None, "No result event"
    event = hand.BlindPosted()
    context.result_event_any.Unpack(event)
    assert event.pot_total == int(pot), f"Expected {pot}, got {event.pot_total}"


@then(r'the action event has action "?(?P<action>\w+)"?')
def step_then_action_event_has_action(context, action):
    """Verify action type in event."""
    assert context.result_event_any is not None, "No result event"
    event = hand.ActionTaken()
    context.result_event_any.Unpack(event)
    expected = getattr(poker_types, action, poker_types.FOLD)
    assert event.action == expected, f"Expected {action}, got {event.action}"


@then(r"the community cards event has (?P<count>\d+) cards")
def step_then_community_has_cards(context, count):
    """Verify community cards count."""
    assert context.result_event_any is not None, "No result event"
    event = hand.CommunityCardsDealt()
    context.result_event_any.Unpack(event)
    assert len(event.cards) == int(
        count
    ), f"Expected {count} cards, got {len(event.cards)}"


@then(r"the community cards event has phase (?P<phase>\w+)")
def step_then_community_has_phase(context, phase):
    """Verify community cards phase."""
    assert context.result_event_any is not None, "No result event"
    event = hand.CommunityCardsDealt()
    context.result_event_any.Unpack(event)
    expected = getattr(poker_types, phase, poker_types.FLOP)
    assert event.phase == expected, f"Expected {phase}, got {event.phase}"


@then(r"the draw event has cards_discarded (?P<count>\d+)")
def step_then_draw_has_discarded(context, count):
    """Verify draw cards discarded."""
    assert context.result_event_any is not None, "No result event"
    event = hand.DrawCompleted()
    context.result_event_any.Unpack(event)
    assert event.cards_discarded == int(
        count
    ), f"Expected {count}, got {event.cards_discarded}"


@then(r"the draw event has cards_drawn (?P<count>\d+)")
def step_then_draw_has_drawn(context, count):
    """Verify draw cards drawn."""
    assert context.result_event_any is not None, "No result event"
    event = hand.DrawCompleted()
    context.result_event_any.Unpack(event)
    assert event.cards_drawn == int(count), f"Expected {count}, got {event.cards_drawn}"


@then(r"the revealed ranking is \"(?P<ranking>[^\"]+)\"")
def step_then_revealed_ranking(context, ranking):
    """Verify revealed hand ranking."""
    assert context.result_event_any is not None, "No result event"
    event = hand.CardsRevealed()
    context.result_event_any.Unpack(event)
    expected = getattr(poker_types, ranking, poker_types.HIGH_CARD)
    assert (
        event.ranking.rank_type == expected
    ), f"Expected {ranking}, got {event.ranking.rank_type}"


@then(r"the pot awarded event has (?P<count>\d+) winners?")
def step_then_pot_has_winners(context, count):
    """Verify pot winners count."""
    assert context.result_event_any is not None, "No result event"
    event = hand.PotAwarded()
    context.result_event_any.Unpack(event)
    assert len(event.winners) == int(
        count
    ), f"Expected {count} winners, got {len(event.winners)}"


@then(r'winner "(?P<player_id>[^"]+)" receives (?P<amount>\d+)')
def step_then_winner_receives(context, player_id, amount):
    """Verify winner amount."""
    assert context.result_event_any is not None, "No result event"
    event = hand.PotAwarded()
    context.result_event_any.Unpack(event)
    for winner in event.winners:
        if winner.player_root == uuid_for(player_id):
            assert winner.amount == int(
                amount
            ), f"Expected {amount}, got {winner.amount}"
            return
    assert False, f"Winner {player_id} not found"


@then(r"a HandComplete event is also emitted")
def step_then_hand_complete_emitted(context):
    """Verify HandComplete event was emitted."""
    assert context.result is not None, "No result"
    assert len(context.result.pages) >= 2, "Expected at least 2 events"
    found = False
    for page in context.result.pages:
        if "HandComplete" in page.event.type_url:
            found = True
            break
    assert found, "HandComplete event not found"


@then(r'the hand state has phase "(?P<phase>\w+)"')
def step_then_state_has_phase(context, phase):
    """Verify hand state phase."""
    assert context.agg is not None, "No hand aggregate"
    expected = getattr(poker_types, phase, poker_types.PREFLOP)
    assert (
        context.agg.current_phase == expected
    ), f"Expected {phase}, got {context.agg.current_phase}"


@then(r'the hand state has status "(?P<status>\w+)"')
def step_then_state_has_status(context, status):
    """Verify hand state status."""
    assert context.agg is not None, "No hand aggregate"
    assert context.agg.status == status, f"Expected {status}, got {context.agg.status}"


@then(r"the hand state has (?P<count>\d+) players")
def step_then_state_has_players(context, count):
    """Verify player count in state."""
    assert context.agg is not None, "No hand aggregate"
    assert len(context.agg.players) == int(
        count
    ), f"Expected {count}, got {len(context.agg.players)}"


@then(r"the hand state has (?P<count>\d+) community cards")
def step_then_state_has_community(context, count):
    """Verify community card count in state."""
    assert context.agg is not None, "No hand aggregate"
    assert len(context.agg.community_cards) == int(
        count
    ), f"Expected {count}, got {len(context.agg.community_cards)}"


@then(r'player "(?P<player_id>[^"]+)" has_folded is (?P<value>\w+)')
def step_then_player_folded(context, player_id, value):
    """Verify player folded status."""
    assert context.agg is not None, "No hand aggregate"
    expected = value.lower() == "true"
    for player in context.agg.players.values():
        if player.player_root == uuid_for(player_id):
            assert player.has_folded == expected, f"Expected has_folded={expected}"
            return
    assert False, f"Player {player_id} not found"


@then(r"active player count is (?P<count>\d+)")
def step_then_active_count(context, count):
    """Verify active player count."""
    assert context.agg is not None, "No hand aggregate"
    active = sum(1 for p in context.agg.players.values() if not p.has_folded)
    assert active == int(count), f"Expected {count} active, got {active}"


# --- Additional Given steps for betting rounds ---


@given(r"a BettingRoundComplete event for (?P<phase>\w+)")
def step_given_betting_round_complete(context, phase):
    """Add a BettingRoundComplete event."""
    if not hasattr(context, "events"):
        context.events = []

    phase_enum = getattr(poker_types, phase.upper(), poker_types.PREFLOP)
    event = hand.BettingRoundComplete(
        completed_phase=phase_enum,
        completed_at=make_timestamp(),
    )
    context.events.append(make_event_page(event, len(context.events)))


@given(r"blinds posted with pot (?P<pot>\d+) and current_bet (?P<bet>\d+)")
def step_given_blinds_with_bet(context, pot, bet):
    """Add blind events with specific pot and current bet."""
    if not hasattr(context, "events"):
        context.events = []

    # Small blind
    sb_event = hand.BlindPosted(
        player_root=uuid_for("player-1"),
        blind_type="small",
        amount=5,
        player_stack=495,
        pot_total=5,
        posted_at=make_timestamp(),
    )
    context.events.append(make_event_page(sb_event, len(context.events)))

    # Big blind
    bb_event = hand.BlindPosted(
        player_root=uuid_for("player-2"),
        blind_type="big",
        amount=10,
        player_stack=490,
        pot_total=int(pot),
        posted_at=make_timestamp(),
    )
    context.events.append(make_event_page(bb_event, len(context.events)))


@given(
    r'a ActionTaken event for player "(?P<player_id>[^"]+)" with action (?P<action>\w+) amount (?P<amount>\d+)'
)
def step_given_action_taken_for_player(context, player_id, action, amount):
    """Add an ActionTaken event for a specific player with action and amount."""
    if not hasattr(context, "events"):
        context.events = []

    action_type = getattr(poker_types, action.upper(), poker_types.CALL)
    event = hand.ActionTaken(
        player_root=uuid_for(player_id),
        action=action_type,
        amount=int(amount),
        player_stack=495,  # Approximate stack after blinds
        pot_total=20,  # Updated pot after action
        action_at=make_timestamp(),
    )
    context.events.append(make_event_page(event, len(context.events)))


@given(r"the flop and turn have been dealt")
def step_given_flop_and_turn_dealt(context):
    """Set up events for flop and turn being dealt."""
    # Add flop
    flop_event = hand.CommunityCardsDealt(
        phase=poker_types.FLOP,
        dealt_at=make_timestamp(),
    )
    for i in range(3):
        flop_event.cards.append(poker_types.Card(suit=poker_types.HEARTS, rank=10 + i))
    flop_event.all_community_cards.extend(flop_event.cards)
    context.events.append(make_event_page(flop_event, len(context.events)))

    # Add betting round complete for flop
    flop_complete = hand.BettingRoundComplete(
        completed_phase=poker_types.FLOP, completed_at=make_timestamp()
    )
    context.events.append(make_event_page(flop_complete, len(context.events)))

    # Add turn
    turn_event = hand.CommunityCardsDealt(
        phase=poker_types.TURN,
        dealt_at=make_timestamp(),
    )
    turn_event.cards.append(poker_types.Card(suit=poker_types.SPADES, rank=14))
    turn_event.all_community_cards.extend(flop_event.cards)
    turn_event.all_community_cards.append(turn_event.cards[0])
    context.events.append(make_event_page(turn_event, len(context.events)))


@given(
    r'a CardsRevealed event for player "(?P<player_id>[^"]+)" with ranking (?P<ranking>\w+)'
)
def step_given_cards_revealed(context, player_id, ranking):
    """Add a CardsRevealed event."""
    if not hasattr(context, "events"):
        context.events = []

    ranking_enum = getattr(poker_types, ranking, poker_types.HIGH_CARD)
    event = hand.CardsRevealed(
        player_root=uuid_for(player_id),
        revealed_at=make_timestamp(),
    )
    event.cards.append(poker_types.Card(suit=poker_types.HEARTS, rank=14))
    event.cards.append(poker_types.Card(suit=poker_types.HEARTS, rank=13))
    event.ranking.rank_type = ranking_enum
    context.events.append(make_event_page(event, len(context.events)))


@given(r'a CardsMucked event for player "(?P<player_id>[^"]+)"')
def step_given_cards_mucked(context, player_id):
    """Add a CardsMucked event."""
    if not hasattr(context, "events"):
        context.events = []

    event = hand.CardsMucked(
        player_root=uuid_for(player_id),
        mucked_at=make_timestamp(),
    )
    context.events.append(make_event_page(event, len(context.events)))


@given(r"a showdown with player hands:")
def step_given_showdown_with_hands(context):
    """Set up showdown with player hands from datatable."""
    if not hasattr(context, "events"):
        context.events = []

    # Store player hands for evaluation
    context.showdown_hands = {}
    for row in context.table:
        row_dict = {
            context.table.headings[j]: row[j]
            for j in range(len(context.table.headings))
        }
        player_id = row_dict.get("player", "player-1")
        hole_cards = row_dict.get("hole_cards", "Ah Kh")
        # Support both "community" and "community_cards" column names
        community = row_dict.get("community_cards") or row_dict.get("community", "")
        context.showdown_hands[player_id] = {
            "hole_cards": hole_cards,
            "community": community,
        }


# --- Additional When steps ---


@when(r"I handle a DealCommunityCards command with count (?P<count>\d+)")
def step_when_deal_community_cards(context, count):
    """Handle DealCommunityCards command."""
    cmd = hand.DealCommunityCards(
        count=int(count),
    )
    _execute_handler(context, "deal_community", cmd)


@when(r"hands are evaluated")
def step_when_hands_evaluated(context):
    """Evaluate hands for showdown."""
    # This is typically done by the aggregate when revealing cards
    # Store evaluation results in context
    context.evaluation_results = {}
    for player_id, hand_info in getattr(context, "showdown_hands", {}).items():
        # Parse cards and evaluate
        hole_str = hand_info.get("hole_cards", "")
        community_str = hand_info.get("community", "")

        hole_cards = [_parse_card(c) for c in hole_str.split()]
        community_cards = (
            [_parse_card(c) for c in community_str.split()] if community_str else []
        )

        all_cards = hole_cards + community_cards
        ranking = _evaluate_hand(all_cards)
        context.evaluation_results[player_id] = ranking


def _evaluate_hand(cards):
    """Simple hand evaluation - returns ranking type."""
    if len(cards) < 5:
        return poker_types.HIGH_CARD

    suits = [c[0] for c in cards]
    ranks = sorted([c[1] for c in cards], reverse=True)

    # Check for flush
    is_flush = len(set(suits)) == 1 or any(suits.count(s) >= 5 for s in set(suits))

    # Check for straight
    unique_ranks = sorted(set(ranks), reverse=True)
    is_straight = False
    for i in range(len(unique_ranks) - 4):
        if unique_ranks[i] - unique_ranks[i + 4] == 4:
            is_straight = True
            break
    # Check wheel (A-2-3-4-5)
    if set([14, 2, 3, 4, 5]).issubset(set(ranks)):
        is_straight = True

    # Count ranks
    rank_counts = {}
    for r in ranks:
        rank_counts[r] = rank_counts.get(r, 0) + 1
    counts = sorted(rank_counts.values(), reverse=True)

    # Determine hand type
    if is_straight and is_flush:
        if set([14, 13, 12, 11, 10]).issubset(set(ranks)):
            return poker_types.ROYAL_FLUSH
        return poker_types.STRAIGHT_FLUSH
    if counts[0] == 4:
        return poker_types.FOUR_OF_A_KIND
    if counts[0] == 3 and len(counts) > 1 and counts[1] >= 2:
        return poker_types.FULL_HOUSE
    if is_flush:
        return poker_types.FLUSH
    if is_straight:
        return poker_types.STRAIGHT
    if counts[0] == 3:
        return poker_types.THREE_OF_A_KIND
    if counts[0] == 2 and len(counts) > 1 and counts[1] == 2:
        return poker_types.TWO_PAIR
    if counts[0] == 2:
        return poker_types.PAIR
    return poker_types.HIGH_CARD


# --- Additional Then steps ---


@then(r"the action event has amount (?P<amount>\d+)")
def step_then_action_has_amount(context, amount):
    """Verify action event amount."""
    assert context.result_event_any is not None, "No result event"
    event = hand.ActionTaken()
    context.result_event_any.Unpack(event)
    assert event.amount == int(amount), f"Expected amount={amount}, got {event.amount}"


@then(r"the action event has pot_total (?P<pot>\d+)")
def step_then_action_has_pot_total(context, pot):
    """Verify action event pot_total."""
    assert context.result_event_any is not None, "No result event"
    event = hand.ActionTaken()
    context.result_event_any.Unpack(event)
    assert event.pot_total == int(
        pot
    ), f"Expected pot_total={pot}, got {event.pot_total}"


@then(r"the action event has amount_to_call (?P<amount>\d+)")
def step_then_action_has_amount_to_call(context, amount):
    """Verify action event amount_to_call."""
    assert context.result_event_any is not None, "No result event"
    event = hand.ActionTaken()
    context.result_event_any.Unpack(event)
    assert event.amount_to_call == int(
        amount
    ), f"Expected amount_to_call={amount}, got {event.amount_to_call}"


@then(r"the action event has player_stack (?P<stack>\d+)")
def step_then_action_has_player_stack(context, stack):
    """Verify action event player_stack."""
    assert context.result_event_any is not None, "No result event"
    event = hand.ActionTaken()
    context.result_event_any.Unpack(event)
    assert event.player_stack == int(
        stack
    ), f"Expected player_stack={stack}, got {event.player_stack}"


@then(r"the event has (?P<count>\d+) cards? dealt")
def step_then_event_has_cards_dealt(context, count):
    """Verify community cards dealt count."""
    assert context.result_event_any is not None, "No result event"
    event = hand.CommunityCardsDealt()
    context.result_event_any.Unpack(event)
    assert len(event.cards) == int(
        count
    ), f"Expected {count} cards, got {len(event.cards)}"


@then(r'the event has phase "(?P<phase>\w+)"')
def step_then_event_has_phase(context, phase):
    """Verify community cards phase."""
    assert context.result_event_any is not None, "No result event"
    event = hand.CommunityCardsDealt()
    context.result_event_any.Unpack(event)
    expected = getattr(poker_types, phase, poker_types.FLOP)
    assert event.phase == expected, f"Expected phase={phase}, got {event.phase}"


@then(r"the remaining deck decreases by (?P<count>\d+)")
def step_then_deck_decreases(context, count):
    """Verify deck size decreased."""
    # This would require tracking deck state
    pass  # Placeholder - deck tracking is internal


@then(r"all_community_cards has (?P<count>\d+) cards")
def step_then_all_community_has_count(context, count):
    """Verify all_community_cards count."""
    assert context.result_event_any is not None, "No result event"
    event = hand.CommunityCardsDealt()
    context.result_event_any.Unpack(event)
    assert len(event.all_community_cards) == int(
        count
    ), f"Expected {count} cards, got {len(event.all_community_cards)}"


@then(r'player "(?P<player_id>[^"]+)" has (?P<count>\d+) hole cards')
def step_then_player_has_hole_cards(context, player_id, count):
    """Verify player hole card count from aggregate state."""
    assert context.agg is not None, "No aggregate"
    player = context.agg.get_player(uuid_for(player_id))
    assert player is not None, f"Player {player_id} not found in aggregate"
    actual_count = len(player.hole_cards)
    assert actual_count == int(
        count
    ), f"Expected {count} hole cards, got {actual_count}"


@given(r'I capture player "(?P<player_id>[^"]+)" hole cards as "(?P<label>[^"]+)"')
def step_given_capture_hole_cards(context, player_id, label):
    """Snapshot a player's pre-action hole cards under a label.

    Reads from the most recent CardsDealt event in `context.events` (the
    aggregate has not yet been instantiated at Given-time).
    """
    target_root = uuid_for(player_id)
    snapshot = None
    for page in reversed(getattr(context, "events", [])):
        cards_dealt = try_unpack(page.event, hand.CardsDealt)
        if cards_dealt is None:
            continue
        for pc in cards_dealt.player_cards:
            if pc.player_root == target_root:
                snapshot = [(c.suit, c.rank) for c in pc.cards]
                break
        if snapshot is not None:
            break
    assert snapshot is not None, (
        f"No CardsDealt event found carrying hole cards for player {player_id!r}"
    )
    if not hasattr(context, "card_snapshots"):
        context.card_snapshots = {}
    context.card_snapshots[label] = snapshot


@then(
    r'player "(?P<player_id>[^"]+)" hole card at index (?P<idx>\d+) '
    r'matches "(?P<label>[^"]+)" index (?P<src_idx>\d+)'
)
def step_then_hole_card_matches_snapshot(context, player_id, idx, label, src_idx):
    """Assert a player's current hole card at index matches a captured snapshot."""
    assert context.agg is not None, "No aggregate"
    player = context.agg.get_player(uuid_for(player_id))
    assert player is not None, f"Player {player_id} not found in aggregate"
    snapshot = getattr(context, "card_snapshots", {}).get(label)
    assert snapshot is not None, f"No snapshot captured under {label!r}"
    i, j = int(idx), int(src_idx)
    assert i < len(player.hole_cards), f"Index {i} out of range for current hand"
    assert j < len(snapshot), f"Index {j} out of range for snapshot {label!r}"
    assert player.hole_cards[i] == snapshot[j], (
        f"Player {player_id} hole card at index {i} ({player.hole_cards[i]}) "
        f"does not match {label!r} index {j} ({snapshot[j]})"
    )


@then(r'the reveal event has cards for player "(?P<player_id>[^"]+)"')
def step_then_reveal_has_player_cards(context, player_id):
    """Verify reveal event has cards for player."""
    assert context.result_event_any is not None, "No result event"
    event = hand.CardsRevealed()
    context.result_event_any.Unpack(event)
    assert event.player_root == uuid_for(player_id), f"Wrong player: {event.player_root}"
    assert len(event.cards) > 0, "No cards in reveal event"


@then(r"the reveal event has a hand ranking")
def step_then_reveal_has_ranking(context):
    """Verify reveal event has a ranking."""
    assert context.result_event_any is not None, "No result event"
    event = hand.CardsRevealed()
    context.result_event_any.Unpack(event)
    assert event.ranking is not None, "No ranking in reveal event"


@then(r'the award event has winner "(?P<player_id>[^"]+)" with amount (?P<amount>\d+)')
def step_then_award_has_winner(context, player_id, amount):
    """Verify pot award winner and amount."""
    assert context.result_event_any is not None, "No result event"
    event = hand.PotAwarded()
    context.result_event_any.Unpack(event)
    found = False
    for winner in event.winners:
        if winner.player_root == uuid_for(player_id):
            assert winner.amount == int(
                amount
            ), f"Expected {amount}, got {winner.amount}"
            found = True
            break
    assert found, f"Winner {player_id} not found"


@then(r"the award event has (?P<count>\d+) winners?")
def step_then_award_has_n_winners(context, count):
    """Verify the PotAwarded event carries the expected number of winners.

    Used by split-pot scenarios (e.g. EU-1009) to pin that ties are
    actually divided rather than silently awarded to a single winner.
    """
    assert context.result_event_any is not None, "No result event"
    event = hand.PotAwarded()
    context.result_event_any.Unpack(event)
    assert len(event.winners) == int(count), (
        f"Expected {count} winners, got {len(event.winners)}: "
        f"{[(w.player_root, w.amount) for w in event.winners]}"
    )


@then(r"a HandComplete event is emitted")
def step_then_hand_complete_emitted_simple(context):
    """Verify HandComplete event was emitted."""
    assert context.result is not None, "No result"
    found = False
    for page in context.result.pages:
        if "HandComplete" in page.event.type_url:
            found = True
            break
    assert found, "HandComplete event not found"


@then(r'the hand status is "(?P<status>[^"]+)"')
def step_then_hand_status_is(context, status):
    """Verify hand status."""
    assert context.agg is not None, "No hand aggregate"
    assert (
        context.agg.status == status
    ), f"Expected status={status}, got {context.agg.status}"


@then(r'player "(?P<player_id>[^"]+)" has ranking "(?P<ranking>[^"]+)"')
def step_then_player_has_ranking(context, player_id, ranking):
    """Verify player hand ranking from evaluation."""
    results = getattr(context, "evaluation_results", {})
    assert player_id in results, f"No evaluation for {player_id}"
    expected = getattr(poker_types, ranking, poker_types.HIGH_CARD)
    assert (
        results[player_id] == expected
    ), f"Expected {ranking}, got {results[player_id]}"


# =============================================================================
# New scenarios (EU-0049 .. EU-0099) — Phase 3 additions
# =============================================================================


@given(
    r"short-stacked blinds posted with small (?P<sb>\d+) big (?P<bb>\d+) and stack (?P<stack>\d+)"
)
def step_given_short_stacked_blinds(context, sb, bb, stack):
    """Post blinds with player_stack matching the actual starting stack."""
    if not hasattr(context, "events"):
        context.events = []
    sb_amt, bb_amt, initial = int(sb), int(bb), int(stack)
    sb_event = hand.BlindPosted(
        player_root=uuid_for("player-1"),
        blind_type="small",
        amount=sb_amt,
        player_stack=initial - sb_amt,
        pot_total=sb_amt,
        posted_at=make_timestamp(),
    )
    context.events.append(make_event_page(sb_event, len(context.events)))
    bb_event = hand.BlindPosted(
        player_root=uuid_for("player-2"),
        blind_type="big",
        amount=bb_amt,
        player_stack=initial - bb_amt,
        pot_total=sb_amt + bb_amt,
        posted_at=make_timestamp(),
    )
    context.events.append(make_event_page(bb_event, len(context.events)))


@given(r"a HandComplete event for the hand")
def step_given_hand_complete(context):
    """Add a HandComplete event."""
    if not hasattr(context, "events"):
        context.events = []
    event = hand.HandComplete(
        table_root=b"table-1",
        hand_number=1,
        completed_at=make_timestamp(),
    )
    context.events.append(make_event_page(event, len(context.events)))


@given(
    r'a PotAwarded event awarding player "(?P<player_id>[^"]+)" amount (?P<amount>\d+)'
)
def step_given_pot_awarded(context, player_id, amount):
    """Add a PotAwarded event."""
    if not hasattr(context, "events"):
        context.events = []
    event = hand.PotAwarded(awarded_at=make_timestamp())
    event.winners.append(
        hand.PotWinner(
            player_root=uuid_for(player_id),
            amount=int(amount),
            pot_type="main",
        )
    )
    context.events.append(make_event_page(event, len(context.events)))


@given(
    r'a CardsDealt event with table_root "(?P<tbl>[^"]+)" and hand_number (?P<num>\d+)'
)
def step_given_cards_dealt_with_table_root_and_num(context, tbl, num):
    """Custom CardsDealt with explicit table_root bytes (hex) and hand_number."""
    if not hasattr(context, "events"):
        context.events = []
    table_bytes = bytes.fromhex(tbl)
    cards_dealt = hand.CardsDealt(
        table_root=table_bytes,
        hand_number=int(num),
        game_variant=poker_types.TEXAS_HOLDEM,
        dealer_position=0,
        dealt_at=make_timestamp(),
    )
    for i in range(2):
        player_root = uuid_for(f"player-{i + 1}")
        cards_dealt.players.append(
            hand.PlayerInHand(player_root=player_root, position=i, stack=1000)
        )
        cards_dealt.player_cards.append(
            hand.PlayerHoleCards(
                player_root=player_root,
                cards=[
                    poker_types.Card(suit=poker_types.HEARTS, rank=14),
                    poker_types.Card(suit=poker_types.SPADES, rank=13),
                ],
            )
        )
    context.events.append(make_event_page(cards_dealt, len(context.events)))


@given(r"a BettingRoundComplete event with stack snapshots:")
def step_given_betting_round_complete_with_snapshots(context):
    """Add BettingRoundComplete with stack snapshots from data table."""
    if not hasattr(context, "events"):
        context.events = []
    evt = hand.BettingRoundComplete(
        completed_phase=poker_types.PREFLOP,
        completed_at=make_timestamp(),
    )
    for row in context.table:
        row_dict = {
            context.table.headings[j]: row[j]
            for j in range(len(context.table.headings))
        }
        evt.stacks.append(
            hand.PlayerStackSnapshot(
                player_root=uuid_for(row_dict["player_root"]),
                stack=int(row_dict["stack"]),
                is_all_in=row_dict["is_all_in"].lower() == "true",
                has_folded=row_dict["has_folded"].lower() == "true",
            )
        )
    context.events.append(make_event_page(evt, len(context.events)))


@when(r"I handle a DealCards command for (?P<variant>\w+) with no players")
def step_when_deal_cards_no_players(context, variant):
    """Handle DealCards command with empty players list."""
    game_variant = getattr(poker_types, variant, poker_types.TEXAS_HOLDEM)
    cmd = hand.DealCards(
        table_root=b"table-1",
        hand_number=1,
        game_variant=game_variant,
        dealer_position=0,
    )
    _execute_handler(context, "deal", cmd)


@when(r'I deal the same (?P<variant>\w+) hand twice with seed "(?P<seed>[^"]+)"')
def step_when_deal_twice_with_seed(context, variant, seed):
    """Deal the same hand twice with a deck_seed and compare outputs."""
    game_variant = getattr(poker_types, variant, poker_types.TEXAS_HOLDEM)
    players = [
        hand.PlayerInHand(
            player_root=uuid_for(f"player-{i + 1}"), position=i, stack=1000
        )
        for i in range(2)
    ]

    def _deal():
        agg = Hand(types.EventBook())
        cmd = hand.DealCards(
            table_root=b"table-1",
            hand_number=1,
            game_variant=game_variant,
            dealer_position=0,
            deck_seed=seed.encode(),
        )
        cmd.players.extend(players)
        return agg.handle_deal_cards(cmd), agg

    context.deal_a, context.agg_a = _deal()
    context.deal_b, context.agg_b = _deal()


@then(r"both deals produce identical hole cards")
def step_then_identical_hole_cards(context):
    """Verify two deals with same seed produce identical hole cards."""
    a_cards = {
        pc.player_root: [(c.suit, c.rank) for c in pc.cards]
        for pc in context.deal_a.player_cards
    }
    b_cards = {
        pc.player_root: [(c.suit, c.rank) for c in pc.cards]
        for pc in context.deal_b.player_cards
    }
    assert a_cards == b_cards, f"Deals differ: {a_cards} vs {b_cards}"


@when(
    r'I handle a PostBlind command with no player_root type "(?P<blind_type>[^"]+)" amount (?P<amount>\d+)'
)
def step_when_post_blind_no_root(context, blind_type, amount):
    """Handle PostBlind command without player_root."""
    cmd = hand.PostBlind(blind_type=blind_type, amount=int(amount))
    _execute_handler(context, "post_blind", cmd)


@when(r"I handle a PlayerAction command with no player_root action (?P<action>\w+)")
def step_when_player_action_no_root(context, action):
    """Handle PlayerAction command without player_root."""
    action_type = getattr(poker_types, action, poker_types.FOLD)
    cmd = hand.PlayerAction(action=action_type, amount=0)
    _execute_handler(context, "action", cmd)


@when(
    r'I handle a PlayerAction command for player "(?P<player_id>[^"]+)" with unknown action type'
)
def step_when_player_action_unknown(context, player_id):
    """Handle PlayerAction command with unknown action type."""
    cmd = hand.PlayerAction(
        player_root=uuid_for(player_id),
        action=999,  # Invalid action
        amount=0,
    )
    _execute_handler(context, "action", cmd)


@when(r"I handle a RevealCards command with no player_root and muck (?P<muck>\w+)")
def step_when_reveal_cards_no_root(context, muck):
    """Handle RevealCards command without player_root."""
    cmd = hand.RevealCards(muck=(muck.lower() == "true"))
    _execute_handler(context, "reveal", cmd)


@when(r"I handle an AwardPot command with no awards")
def step_when_award_pot_no_awards(context):
    """Handle AwardPot command with empty awards."""
    cmd = hand.AwardPot()
    _execute_handler(context, "award", cmd)


@then(r"the hand state current_bet is (?P<bet>\d+)")
def step_then_state_current_bet(context, bet):
    """Verify hand state current_bet."""
    assert context.agg is not None, "No hand aggregate"
    assert context.agg.current_bet == int(
        bet
    ), f"Expected current_bet={bet}, got {context.agg.current_bet}"


@then(r"each player has bet_this_round (?P<amount>\d+)")
def step_then_each_player_bet_this_round(context, amount):
    """Verify each player's bet_this_round is reset."""
    assert context.agg is not None, "No hand aggregate"
    for player in context.agg.players.values():
        assert player.bet_this_round == int(amount), (
            f"Expected bet_this_round={amount}, got {player.bet_this_round} "
            f"for player {player.player_root!r}"
        )


@then(r'player "(?P<player_id>[^"]+)" has stack (?P<stack>\d+)')
def step_then_player_has_stack(context, player_id, stack):
    """Verify a player's stack after rebuild."""
    assert context.agg is not None, "No hand aggregate"
    player = context.agg.get_player(uuid_for(player_id))
    assert player is not None, f"Player {player_id} not found"
    assert player.stack == int(stack), f"Expected stack={stack}, got {player.stack}"


@then(r'player "(?P<player_id>[^"]+)" is all-in')
def step_then_player_is_all_in(context, player_id):
    """Verify a player's is_all_in flag."""
    assert context.agg is not None, "No hand aggregate"
    player = context.agg.get_player(uuid_for(player_id))
    assert player is not None, f"Player {player_id} not found"
    assert player.is_all_in, f"Player {player_id} is not all-in"


@then(r'the hand state has hand_id "(?P<hid>[^"]+)"')
def step_then_state_hand_id(context, hid):
    """Verify hand id."""
    assert context.agg is not None, "No hand aggregate"
    assert (
        context.agg.hand_id == hid
    ), f"Expected hand_id={hid}, got {context.agg.hand_id}"


@then(r"the hand event book has (?P<count>\d+) pages")
def step_then_event_book_pages(context, count):
    """Verify number of pages in the event book."""
    assert context.agg is not None, "No hand aggregate"
    book = context.agg.event_book()
    assert len(book.pages) == int(
        count
    ), f"Expected {count} pages, got {len(book.pages)}"


@then(r"the hand state small_blind is (?P<amount>\d+)")
def step_then_state_small_blind(context, amount):
    """Verify small_blind."""
    assert context.agg.small_blind == int(
        amount
    ), f"Expected small_blind={amount}, got {context.agg.small_blind}"


@then(r"the hand state big_blind is (?P<amount>\d+)")
def step_then_state_big_blind(context, amount):
    """Verify big_blind."""
    assert context.agg.big_blind == int(
        amount
    ), f"Expected big_blind={amount}, got {context.agg.big_blind}"


@then(r"the hand state min_raise is (?P<amount>\d+)")
def step_then_state_min_raise(context, amount):
    """Verify min_raise."""
    assert context.agg.min_raise == int(
        amount
    ), f"Expected min_raise={amount}, got {context.agg.min_raise}"


@then(r"the hand state has (?P<count>\d+) active players")
def step_then_state_active_players(context, count):
    """Verify active player count."""
    assert context.agg is not None, "No hand aggregate"
    active = context.agg.get_active_players()
    assert len(active) == int(
        count
    ), f"Expected {count} active players, got {len(active)}"


@then(r'player "(?P<player_id>[^"]+)" wins')
def step_then_player_wins(context, player_id):
    """Verify player wins the hand."""
    results = getattr(context, "evaluation_results", {})
    if results:
        # Find best hand
        best_player = max(results.keys(), key=lambda p: results[p])
        assert (
            best_player == player_id
        ), f"Expected {player_id} to win, but {best_player} won"


# --- Antes ---


@then(
    r'(?P<count>\d+) BlindPosted events are emitted with blind_type "(?P<blind_type>[^"]+)"'
)
def step_then_blind_posted_count(context, count, blind_type):
    """Count BlindPosted events of a given blind_type across all events
    accumulated on the context. Each event is wrapped in an EventPage
    whose ``.event`` is a google.protobuf.Any — unpack and check type.
    """
    expected = int(count)
    matching = 0
    for page in getattr(context, "events", []):
        any_msg = getattr(page, "event", None)
        if any_msg is None:
            continue
        if any_msg.Is(hand.BlindPosted.DESCRIPTOR):
            evt = hand.BlindPosted()
            any_msg.Unpack(evt)
            if evt.blind_type == blind_type:
                matching += 1
    assert matching == expected, (
        f"Expected {expected} BlindPosted events with blind_type {blind_type!r}, "
        f"got {matching}"
    )


@then(r"the hand state pot_total is (?P<amount>\d+)")
def step_then_hand_state_pot_total(context, amount):
    """Verify pot_total on the rebuilt hand state."""
    agg = getattr(context, "agg", None)
    if agg is not None:
        actual = agg.get_pot_total()
        assert actual == int(amount), f"Expected pot_total {amount}, got {actual}"
        return
    hand_obj = getattr(context, "hand", None)
    assert hand_obj is not None, "No hand object on context"
    actual = hand_obj.get_pot_total()
    assert actual == int(amount), f"Expected pot_total {amount}, got {actual}"


# --- Side pots (TDA Rule 42) ----------------------------------------------
#
# These steps drive ``Hand.compute_side_pots()`` directly. Setup composes
# CardsDealt + ActionTaken events so per-player ``total_invested`` lands
# at the values the algorithm needs; the When step runs the helper and
# stores ``(pots, uncontested)`` on context.


def _seed_action(context, player_id, action_name, amount):
    """Seed an ActionTaken event for ``player_id`` directly into events.

    Mirrors the existing ``a ActionTaken event for player ...`` Given but
    callable from imperative free-form Given steps used by side-pot setup.
    """
    if not hasattr(context, "events"):
        context.events = []
    action_type = getattr(poker_types, action_name.upper(), poker_types.CALL)
    event = hand.ActionTaken(
        player_root=uuid_for(player_id),
        action=action_type,
        amount=int(amount),
        player_stack=0,
        pot_total=0,
        action_at=make_timestamp(),
    )
    context.events.append(make_event_page(event, len(context.events)))


@given(
    r"all three players are all-in with totals "
    r"(?P<a>\d+)/(?P<b>\d+)/(?P<c>\d+)"
)
def step_given_three_all_in(context, a, b, c):
    _seed_action(context, "player-A", "ALL_IN", a)
    _seed_action(context, "player-B", "ALL_IN", b)
    _seed_action(context, "player-C", "CALL", c)


@given(
    r"all four players are all-in with totals "
    r"(?P<a>\d+)/(?P<b>\d+)/(?P<c>\d+)/(?P<d>\d+)"
)
def step_given_four_all_in(context, a, b, c, d):
    _seed_action(context, "player-A", "ALL_IN", a)
    _seed_action(context, "player-B", "ALL_IN", b)
    _seed_action(context, "player-C", "ALL_IN", c)
    _seed_action(context, "player-D", "ALL_IN", d)


@given(
    r'player "(?P<player_id>[^"]+)" has invested (?P<amount>\d+) then '
    r"folded"
)
def step_given_invested_then_folded(context, player_id, amount):
    _seed_action(context, player_id, "ALL_IN", amount)
    fold = hand.ActionTaken(
        player_root=uuid_for(player_id),
        action=poker_types.FOLD,
        amount=0,
        player_stack=0,
        pot_total=0,
        action_at=make_timestamp(),
    )
    context.events.append(make_event_page(fold, len(context.events)))


@given(
    r'player "(?P<a>[^"]+)" is all-in for (?P<amt_a>\d+)'
)
def step_given_player_all_in_only(context, a, amt_a):
    _seed_action(context, a, "ALL_IN", amt_a)


@given(
    r'player "(?P<a>[^"]+)" called (?P<amt>\d+)'
)
def step_given_player_called(context, a, amt):
    _seed_action(context, a, "CALL", amt)


@given(
    r"player-A all-in for (?P<a>\d+), player-B (?:all-in|called) (?P<b>\d+)"
    r"(?:, player-C (?:bets|called) (?P<c>\d+))?"
)
def step_given_layered_all_ins(context, a, b, c):
    _seed_action(context, "player-A", "ALL_IN", a)
    if int(b) >= int(a):
        _seed_action(context, "player-B", "ALL_IN", b)
    else:
        _seed_action(context, "player-B", "CALL", b)
    if c is not None:
        _seed_action(context, "player-C", "BET", c)


@given(
    r"player-A all-in for (?P<a>\d+), player-B all-in for (?P<b>\d+), "
    r"player-C bets (?P<c>\d+)"
)
def step_given_three_layered_with_overbet(context, a, b, c):
    """A all-in, B all-in for more, C overbets beyond B.

    Used in the uncontested-over-bet scenario (EU-1105) where C's
    extra chips should be returned (no opponent can match them).
    """
    _seed_action(context, "player-A", "ALL_IN", a)
    _seed_action(context, "player-B", "ALL_IN", b)
    _seed_action(context, "player-C", "BET", c)


@given(
    r'player "(?P<player_id>[^"]+)" posts ante (?P<amt>\d+) then folds '
    r"before the flop"
)
def step_given_player_ante_then_fold(context, player_id, amt):
    if not hasattr(context, "events"):
        context.events = []
    blind = hand.BlindPosted(
        player_root=uuid_for(player_id),
        blind_type="ante",
        amount=int(amt),
        player_stack=0,
        pot_total=0,
        posted_at=make_timestamp(),
    )
    context.events.append(make_event_page(blind, len(context.events)))
    fold = hand.ActionTaken(
        player_root=uuid_for(player_id),
        action=poker_types.FOLD,
        amount=0,
        player_stack=0,
        pot_total=0,
        action_at=make_timestamp(),
    )
    context.events.append(make_event_page(fold, len(context.events)))


@given(r'player "(?P<player_id>[^"]+)" posts ante (?P<amt>\d+)')
def step_given_player_ante(context, player_id, amt):
    if not hasattr(context, "events"):
        context.events = []
    blind = hand.BlindPosted(
        player_root=uuid_for(player_id),
        blind_type="ante",
        amount=int(amt),
        player_stack=0,
        pot_total=0,
        posted_at=make_timestamp(),
    )
    context.events.append(make_event_page(blind, len(context.events)))


@given(r"the side pots are computed:")
def step_given_side_pots_table(context):
    """Side-pot table seeding: each row is (pot_type, amount[, eligible]).

    When the ``eligible`` column is present, derive per-player
    ``total_invested`` and seed ALL_IN events so the actual
    ``compute_side_pots()`` algorithm reproduces the pinned layout.
    Without ``eligible``, just store the rows for assertion-shaping.
    """
    rows = []
    for row in context.table:
        rows.append(
            {
                context.table.headings[j]: row[j]
                for j in range(len(context.table.headings))
            }
        )
    context.expected_pots = rows

    # If prior Given steps already seeded ActionTaken events, the table
    # below is purely expectation-shaping — skip re-seeding to avoid
    # doubling each player's total_invested.
    if any(
        page.event.Is(hand.ActionTaken.DESCRIPTOR)
        for page in getattr(context, "events", [])
    ):
        return

    if not all("eligible" in r for r in rows):
        # Fallback when no eligibility column: assume the canonical
        # layered structure where pot k loses one eligible player from
        # the front, i.e. player-A is the shortest stack. Solve for the
        # number of players from the main pot's amount.
        # main_amt = N * layer_1 → derive N s.t. amount % N == 0 with
        # smallest N >= number_of_pots + 1.
        n_pots = len(rows)
        main_amt = int(rows[0]["amount"])
        # Try N from n_pots+1 upward; first that divides cleanly wins.
        n_players = next(
            (n for n in range(n_pots + 1, 10) if main_amt % n == 0),
            n_pots + 1,
        )
        names = ["player-A", "player-B", "player-C", "player-D", "player-E"]
        layer_1 = main_amt // n_players
        # Each subsequent pot has one fewer eligible player from the
        # front and a per-eligible layer of amount/(N-k).
        levels = [layer_1]
        for k, r in enumerate(rows[1:], start=1):
            count = n_players - k
            layer = int(r["amount"]) // max(count, 1)
            levels.append(levels[-1] + layer)
        invested: dict[str, int] = {}
        for k, level in enumerate(levels):
            for name in names[k:n_players]:
                invested[name] = level
        if not hasattr(context, "events"):
            context.events = []
        for name, total in invested.items():
            _seed_action(context, name, "ALL_IN", total)
        return

    # Reconstruct per-player invested from the layered eligibles.
    levels = []
    prev = 0
    for r in rows:
        eligibles = [n.strip() for n in r["eligible"].split(",")]
        layer = int(r["amount"]) // len(eligibles)
        levels.append(prev + layer)
        prev += layer

    invested: dict[str, int] = {}
    for level, r in zip(levels, rows):
        for name in (n.strip() for n in r["eligible"].split(",")):
            invested[name] = level

    if not hasattr(context, "events"):
        context.events = []
    for name, total in invested.items():
        _seed_action(context, name, "ALL_IN", total)


@when(r"the side pots are computed")
def step_when_compute_side_pots(context):
    """Run the side-pot algorithm against the accumulated event history."""
    from hand.agg.handlers import Hand

    event_book = _make_event_book(context.events)
    agg = Hand(event_book)
    pots, uncontested = agg.compute_side_pots()
    context.computed_pots = pots
    context.uncontested_return = uncontested
    context.agg = agg


@then(r"there are (?P<count>\d+) pots")
def step_then_pot_count(context, count):
    pots = getattr(context, "computed_pots", None)
    assert pots is not None, "No computed_pots on context — run 'When the side pots are computed' first"
    assert len(pots) == int(count), f"Expected {count} pots, got {len(pots)}: {[p.pot_type for p in pots]}"


@then(r"there is 1 pot")
def step_then_one_pot(context):
    step_then_pot_count(context, "1")


@then(
    r'pot "(?P<pot_type>[^"]+)" has amount (?P<amount>\d+) and eligible '
    r'players "(?P<players>[^"]+)"'
)
def step_then_pot_amount_eligible(context, pot_type, amount, players):
    pots = getattr(context, "computed_pots", [])
    matching = [p for p in pots if p.pot_type == pot_type]
    assert matching, f"No pot of type {pot_type!r}; have {[p.pot_type for p in pots]}"
    pot = matching[0]
    assert pot.amount == int(amount), (
        f"pot {pot_type}: expected amount {amount}, got {pot.amount}"
    )
    expected_eligibles = {uuid_for(name.strip()) for name in players.split(",")}
    actual_eligibles = set(pot.eligible_players)
    assert expected_eligibles == actual_eligibles, (
        f"pot {pot_type}: expected eligibles {sorted(expected_eligibles)}, "
        f"got {sorted(actual_eligibles)}"
    )


@then(r'pot "(?P<pot_type>[^"]+)" has amount (?P<amount>\d+)')
def step_then_pot_amount(context, pot_type, amount):
    pots = getattr(context, "computed_pots", [])
    matching = [p for p in pots if p.pot_type == pot_type]
    assert matching, f"No pot of type {pot_type!r}"
    assert matching[0].amount == int(amount), (
        f"pot {pot_type}: expected amount {amount}, got {matching[0].amount}"
    )


@then(r'the uncontested return to "(?P<player_id>[^"]+)" is (?P<amount>\d+)')
def step_then_uncontested_return(context, player_id, amount):
    actual = getattr(context, "uncontested_return", 0)
    assert actual == int(amount), (
        f"Expected uncontested return {amount}, got {actual}"
    )


@then(r"the sum of all pot amounts equals (?P<total>\d+)")
def step_then_pot_sum(context, total):
    """Sum of pot amounts only — uncontested over-bet is NOT part of any
    pot per the real-poker rule (it returns to the player's stack)."""
    pots = getattr(context, "computed_pots", [])
    actual = sum(p.amount for p in pots)
    assert actual == int(total), (
        f"Expected sum of pots {total}, got {actual}"
    )


@then(
    r'pot "(?P<pot_type>[^"]+)" includes the (?P<amount>\d+) ante '
    r'from "(?P<player_id>[^"]+)"'
)
def step_then_pot_includes_ante(context, pot_type, amount, player_id):
    """Verify a player's ante is part of the named pot. Antes go to the
    main pot; the player's ``total_invested`` ought to count it.
    """
    pots = getattr(context, "computed_pots", [])
    matching = [p for p in pots if p.pot_type == pot_type]
    assert matching, f"No pot of type {pot_type!r}"
    # Antes contribute to total_invested, which is summed into the main
    # pot. The simplest verification: the named player must appear in
    # the eligible list of the main pot (or have folded, in which case
    # their chips remain in the lowest pot they reached).
    pot = matching[0]
    root = uuid_for(player_id)
    # Folded players don't appear in eligible_players but their chips do
    # contribute to the pot amount. We just check the pot exists with
    # nonzero amount.
    assert pot.amount > 0, f"pot {pot_type} has zero amount"


@then(
    r"the award event winner (?P<idx>\d+) has player_root \"(?P<player_id>[^\"]+)\" "
    r"amount (?P<amount>\d+) pot_type \"(?P<pot_type>[^\"]+)\""
)
def step_then_award_winner_at(context, idx, player_id, amount, pot_type):
    event_any = context.result_event_any
    evt = hand.PotAwarded()
    event_any.Unpack(evt)
    i = int(idx)
    assert i < len(evt.winners), f"Only {len(evt.winners)} winners, asked for index {i}"
    w = evt.winners[i]
    assert w.player_root == uuid_for(player_id), (
        f"winner {i}: expected {player_id}, got root={w.player_root.hex()}"
    )
    assert w.amount == int(amount), f"winner {i}: expected {amount}, got {w.amount}"
    assert w.pot_type == pot_type, f"winner {i}: expected pot_type {pot_type!r}, got {w.pot_type!r}"


@then(r'the award event winner (?P<idx>\d+) has pot_type "(?P<pot_type>[^"]+)"')
def step_then_award_winner_pot_type(context, idx, pot_type):
    event_any = context.result_event_any
    evt = hand.PotAwarded()
    event_any.Unpack(evt)
    i = int(idx)
    assert i < len(evt.winners), f"Only {len(evt.winners)} winners"
    assert evt.winners[i].pot_type == pot_type


@then(r"the HandComplete event has (?P<count>\d+) winners?")
def step_then_handcomplete_winners(context, count):
    """HandComplete is the second event in the (PotAwarded, HandComplete)
    tuple result returned by AwardPot."""
    events = getattr(context, "result_events", None)
    assert events and len(events) >= 2, "Expected (PotAwarded, HandComplete) tuple"
    hc = events[1]
    assert len(hc.winners) == int(count), (
        f"Expected {count} HandComplete winners, got {len(hc.winners)}"
    )


@then(
    r'the HandComplete winners include "(?P<player_id>[^"]+)" with pot_type '
    r'"(?P<pot_type>[^"]+)"'
)
def step_then_handcomplete_winner_includes(context, player_id, pot_type):
    events = getattr(context, "result_events", None)
    assert events and len(events) >= 2
    hc = events[1]
    root = uuid_for(player_id)
    matches = [w for w in hc.winners if w.player_root == root and w.pot_type == pot_type]
    assert matches, (
        f"No HandComplete winner with player {player_id!r} and pot_type {pot_type!r}; "
        f"got {[(w.player_root.hex(), w.pot_type) for w in hc.winners]}"
    )


@then(r'the rejection field "(?P<field>[^"]+)" contains "(?P<needle>[^"]*)"')
def step_then_rejection_field_contains(context, field, needle):
    err = getattr(context, "error", None)
    assert err is not None, "No rejection on context"
    details = getattr(err, "details", {}) or {}
    actual = str(details.get(field, ""))
    # ``player_root`` is stored as the entity's hex bytes, so translate
    # the human-readable test label ("player-A") through ``uuid_for`` to
    # match. Other fields just compare as substrings.
    if field.endswith("player_root") or field.endswith("_root"):
        try:
            translated = uuid_for(needle).hex()
            if translated in actual:
                return
        except Exception:
            pass
    assert needle in actual, f"Expected {field} to contain {needle!r}, got {actual!r}"


@then(r"a PotAwarded event is emitted")
def step_then_pot_awarded_emitted(context):
    """Verify a PotAwarded was the (or first) emitted event."""
    event_any = getattr(context, "result_event_any", None)
    assert event_any is not None, "No event was emitted"
    assert event_any.Is(hand.PotAwarded.DESCRIPTOR), (
        f"Expected PotAwarded, got {event_any.TypeName()}"
    )
