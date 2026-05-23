"""Step definitions for the game-display projector tests.

The step regexes match the business-language phrasing in
``features/example/unit/projector.feature``: things like
"When Alice registers" rather than "a PlayerRegistered event with
display_name 'Alice'". Under the hood, each business action still
synthesises the underlying protobuf event and feeds it through the
production OutputProjector so the rendering itself is genuinely
exercised.
"""

from datetime import datetime, timezone

from behave import given, then, use_step_matcher, when
from google.protobuf.any_pb2 import Any as ProtoAny
from google.protobuf.timestamp_pb2 import Timestamp
from projector import OutputProjector
from renderer import format_card
from tests.helpers import uuid_for

from angzarr_client.proto.angzarr.v1 import types_pb2 as types
from angzarr_client.proto.examples.v1 import hand_pb2 as hand
from angzarr_client.proto.examples.v1 import player_pb2 as player
from angzarr_client.proto.examples.v1 import poker_types_pb2 as poker_types
from angzarr_client.proto.examples.v1 import table_pb2 as table

# Use regex matchers for flexibility
use_step_matcher("re")


def make_timestamp():
    """Create current timestamp."""
    return Timestamp(seconds=int(datetime.now(timezone.utc).timestamp()))


def make_event_page(event_msg, time_str: str = None) -> types.EventPage:
    """Create EventPage with packed event."""
    event_any = ProtoAny()
    event_any.Pack(event_msg, type_url_prefix="type.googleapis.com/")

    if time_str:
        h, m, s = map(int, time_str.split(":"))
        dt = datetime(2024, 1, 1, h, m, s, tzinfo=timezone.utc)
        created_at = Timestamp(seconds=int(dt.timestamp()))
    else:
        created_at = make_timestamp()

    return types.EventPage(
        header=types.PageHeader(sequence=0),
        event=event_any,
        created_at=created_at,
    )


def make_card(rank: int, suit: int):
    """Create a card proto."""
    return poker_types.Card(rank=rank, suit=suit)


def parse_card(card_str: str):
    """Parse card string like 'As', 'Kh', '7s' into rank and suit."""
    rank_map = {
        "2": 2,
        "3": 3,
        "4": 4,
        "5": 5,
        "6": 6,
        "7": 7,
        "8": 8,
        "9": 9,
        "T": 10,
        "10": 10,
        "J": 11,
        "Q": 12,
        "K": 13,
        "A": 14,
    }
    suit_map = {
        "s": poker_types.SPADES,
        "h": poker_types.HEARTS,
        "d": poker_types.DIAMONDS,
        "c": poker_types.CLUBS,
    }
    # Handle both "As" and "10s" formats
    rank_char = card_str[:-1] if len(card_str) > 2 else card_str[0]
    suit_char = card_str[-1].lower()
    rank = rank_map.get(rank_char)
    if rank is None:
        try:
            rank = int(rank_char)
        except ValueError:
            rank = 2  # Default
    return make_card(rank, suit_map.get(suit_char, poker_types.SPADES))


# =============================================================================
# Helpers shared by the new business-language steps
# =============================================================================


def _make_projector(context, *, show_timestamps: bool = False) -> None:
    """Create a fresh display/projector on the context."""
    context.output_lines = []
    context.projector = OutputProjector(
        output_fn=lambda text: context.output_lines.append(text),
        show_timestamps=show_timestamps,
    )


def _handle(context, event_msg, time_str: str | None = None) -> None:
    """Feed a single event through the projector."""
    page = make_event_page(event_msg, time_str)
    context.projector.handle_event(page)


# =============================================================================
# Given steps — display setup
# =============================================================================


@given(r"the game display")
def step_given_game_display(context):
    """Create a fresh game display (OutputProjector)."""
    _make_projector(context)


@given(r"the game display knows (?P<name>\w+)")
def step_given_display_knows_one(context, name):
    """Create a display and pre-register one player under player-1."""
    _make_projector(context)
    context.projector.set_player_name(b"player-1", name)


@given(r"the game display knows (?P<name1>\w+) and (?P<name2>\w+)")
def step_given_display_knows_two(context, name1, name2):
    """Create a display and pre-register two players (player-1, player-2)."""
    _make_projector(context)
    context.projector.set_player_name(b"player-1", name1)
    context.projector.set_player_name(b"player-2", name2)


@given(r"the game display with timestamps enabled")
def step_given_display_with_timestamps(context):
    """Game display with show_timestamps enabled."""
    _make_projector(context, show_timestamps=True)


@given(r"the game display with timestamps disabled")
def step_given_display_without_timestamps(context):
    """Game display with show_timestamps disabled."""
    _make_projector(context, show_timestamps=False)


@given(r'player "(?P<player_id>[^"]+)" is registered as "(?P<name>[^"]+)"')
def step_given_player_registered_as(context, player_id, name):
    """Pre-register a player→name mapping in the display's cache."""
    context.projector.set_player_name(uuid_for(player_id), name)


# =============================================================================
# When steps — player domain actions translating to events
# =============================================================================


@when(r"(?P<name>\w+) registers")
def step_when_player_registers(context, name):
    """Translate the registration into a PlayerRegistered event."""
    event = player.PlayerRegistered(
        display_name=name,
        email=f"{name.lower()}@example.com",
        player_type=poker_types.HUMAN,
    )
    _handle(context, event)


@when(
    r"(?P<name>\w+) deposits (?P<amount>\d+) chips? bringing (?:her|his|their) "
    r"balance to (?P<balance>\d+)"
)
def step_when_player_deposits(context, name, amount, balance):
    """A deposit event with the resulting balance."""
    event = player.FundsDeposited(
        amount=poker_types.Currency(amount=int(amount)),
        new_balance=poker_types.Currency(amount=int(balance)),
    )
    _handle(context, event)


@when(
    r"(?P<name>\w+) withdraws (?P<amount>\d+) chips? bringing (?:her|his|their) "
    r"balance to (?P<balance>\d+)"
)
def step_when_player_withdraws(context, name, amount, balance):
    """A withdrawal event with the resulting balance."""
    event = player.FundsWithdrawn(
        amount=poker_types.Currency(amount=int(amount)),
        new_balance=poker_types.Currency(amount=int(balance)),
    )
    _handle(context, event)


@when(r"(?P<name>\w+) reserves (?P<amount>\d+) chips?")
def step_when_player_reserves(context, name, amount):
    """A reservation event."""
    event = player.FundsReserved(
        amount=poker_types.Currency(amount=int(amount)),
        key=b"table-1",
    )
    _handle(context, event)


# =============================================================================
# When steps — table domain actions
# =============================================================================


@when(r"a table is created with:")
def step_when_table_created(context):
    """Translate the data table row into a TableCreated event."""
    row = {
        context.table.headings[i]: context.table[0][i]
        for i in range(len(context.table.headings))
    }
    variant = getattr(poker_types, row.get("game_variant", "TEXAS_HOLDEM"))
    event = table.TableCreated(
        table_name=row["table_name"],
        game_variant=variant,
        small_blind=int(row["small_blind"]),
        big_blind=int(row["big_blind"]),
        min_buy_in=int(row.get("min_buy_in", 200)),
        max_buy_in=int(row.get("max_buy_in", 1000)),
        max_players=int(row.get("max_players", 9)),
        created_at=make_timestamp(),
    )
    _handle(context, event)


@when(r"(?P<name>\w+) joins at seat (?P<seat>\d+) with a buy-in of (?P<buy_in>\d+)")
def step_when_player_joins(context, name, seat, buy_in):
    """A PlayerJoined event at the named seat."""
    event = table.PlayerJoined(
        player_root=b"player-1",
        seat_position=int(seat),
        stack=int(buy_in),
        buy_in_amount=int(buy_in),
        joined_at=make_timestamp(),
    )
    _handle(context, event)


@when(r"(?P<name>\w+) leaves cashing out (?P<amount>\d+) chips?")
def step_when_player_leaves(context, name, amount):
    """A PlayerLeft event with the cashed-out amount."""
    event = table.PlayerLeft(
        player_root=b"player-1",
        chips_cashed_out=int(amount),
        left_at=make_timestamp(),
    )
    _handle(context, event)


@when(
    r"hand (?P<num>\d+) starts with dealer at seat (?P<dealer>\d+) and "
    r"blinds (?P<sb>\d+)/(?P<bb>\d+)"
)
def step_when_hand_starts(context, num, dealer, sb, bb):
    """Stage the HandStarted event; a follow-up active-players step adds players."""
    context.hand_started = table.HandStarted(
        hand_root=b"hand-1",
        hand_number=int(num),
        dealer_position=int(dealer),
        game_variant=poker_types.TEXAS_HOLDEM,
        small_blind=int(sb),
        big_blind=int(bb),
        started_at=make_timestamp(),
    )


@when(
    r'the active players are "(?P<p1>\w+)", "(?P<p2>\w+)", "(?P<p3>\w+)" at seats '
    r"(?P<seats>\d+(?:,\s*\d+){2})"
)
def step_when_active_players_three(context, p1, p2, p3, seats):
    """Attach three active players and dispatch the pending HandStarted event."""
    seat_nums = [int(s.strip()) for s in seats.split(",")]
    for i, (name, seat) in enumerate(zip([p1, p2, p3], seat_nums)):
        root = uuid_for(f"player-{i + 1}")
        context.hand_started.active_players.append(
            table.SeatSnapshot(player_root=root, position=seat, stack=500)
        )
        context.projector.set_player_name(root, name)
    _handle(context, context.hand_started)


@when(r"the hand ends with (?P<name>\w+) winning (?P<amount>\d+)")
def step_when_hand_ends_with_winner(context, name, amount):
    """Translate the end-of-hand into a HandEnded event with a single PotResult."""
    event = table.HandEnded(hand_root=b"hand-1", ended_at=make_timestamp())
    event.results.append(
        table.PotResult(
            winner_root=b"player-1",
            amount=int(amount),
            pot_type="main",
        )
    )
    context.projector.set_player_name(b"player-1", name)
    _handle(context, event)


@when(r"the hand finishes with final stacks:")
def step_when_hand_finishes_with_stacks(context):
    """A HandComplete event populated from the data table's final stacks."""
    event = hand.HandComplete(table_root=b"table-1")
    for i, row in enumerate(context.table):
        row_dict = {
            context.table.headings[j]: row[j]
            for j in range(len(context.table.headings))
        }
        player_name = row_dict.get("player", f"Player{i + 1}")
        player_root = uuid_for(f"player-{i + 1}")
        has_folded_str = row_dict.get("has_folded", "false").lower()
        has_folded = has_folded_str in ("true", "yes", "1")
        event.final_stacks.append(
            hand.PlayerStackSnapshot(
                player_root=player_root,
                stack=int(row_dict.get("stack", 500)),
                has_folded=has_folded,
            )
        )
        context.projector.set_player_name(player_root, player_name)
    _handle(context, event)


# =============================================================================
# When steps — hand domain actions
# =============================================================================


@when(r"(?P<name>\w+) is dealt (?P<cards>\w+ \w+)")
def step_when_player_dealt(context, name, cards):
    """A CardsDealt event with the named player's hole cards."""
    event = hand.CardsDealt(
        table_root=b"table-1",
        hand_number=1,
        game_variant=poker_types.TEXAS_HOLDEM,
    )
    card_list = [parse_card(c.strip()) for c in cards.split()]
    event.player_cards.append(
        hand.PlayerHoleCards(player_root=b"player-1", cards=card_list)
    )
    _handle(context, event)


@when(r"(?P<name>\w+) posts the (?P<blind_type>small|big) blind of (?P<amount>\d+)")
def step_when_player_posts_blind(context, name, blind_type, amount):
    """A BlindPosted event."""
    event = hand.BlindPosted(
        player_root=b"player-1",
        blind_type=blind_type,
        amount=int(amount),
        pot_total=int(amount),
        player_stack=500 - int(amount),
    )
    _handle(context, event)


@when(r"(?P<name>\w+) folds")
def step_when_player_folds(context, name):
    """An ActionTaken event with action FOLD."""
    event = hand.ActionTaken(
        player_root=b"player-1",
        action=poker_types.FOLD,
        amount=0,
        pot_total=0,
        player_stack=500,
    )
    _handle(context, event)


@when(r"(?P<name>\w+) calls (?P<amount>\d+) making the pot (?P<pot>\d+)")
def step_when_player_calls(context, name, amount, pot):
    """An ActionTaken event with action CALL."""
    event = hand.ActionTaken(
        player_root=b"player-1",
        action=poker_types.CALL,
        amount=int(amount),
        pot_total=int(pot),
        player_stack=500 - int(amount),
    )
    _handle(context, event)


@when(r"(?P<name>\w+) raises to (?P<amount>\d+) making the pot (?P<pot>\d+)")
def step_when_player_raises(context, name, amount, pot):
    """An ActionTaken event with action RAISE."""
    event = hand.ActionTaken(
        player_root=b"player-1",
        action=poker_types.RAISE,
        amount=int(amount),
        pot_total=int(pot),
        player_stack=500 - int(amount),
    )
    _handle(context, event)


@when(r"(?P<name>\w+) goes all-in for (?P<amount>\d+) making the pot (?P<pot>\d+)")
def step_when_player_all_in(context, name, amount, pot):
    """An ActionTaken event with action ALL_IN."""
    event = hand.ActionTaken(
        player_root=b"player-1",
        action=poker_types.ALL_IN,
        amount=int(amount),
        pot_total=int(pot),
        player_stack=500 - int(amount),
    )
    _handle(context, event)


@when(r"the flop is dealt (?P<cards>\w+ \w+ \w+)")
def step_when_flop_dealt(context, cards):
    """A CommunityCardsDealt event for the FLOP phase."""
    event = hand.CommunityCardsDealt(phase=poker_types.FLOP)
    for card_str in cards.split():
        event.cards.append(parse_card(card_str.strip()))
    _handle(context, event)


@when(r"the turn is dealt (?P<card>\w+)")
def step_when_turn_dealt(context, card):
    """A CommunityCardsDealt event for the TURN phase."""
    event = hand.CommunityCardsDealt(phase=poker_types.TURN)
    event.cards.append(parse_card(card.strip()))
    _handle(context, event)


@when(r"the showdown begins")
def step_when_showdown_begins(context):
    """A ShowdownStarted event."""
    _handle(context, hand.ShowdownStarted())


@when(r"(?P<name>\w+) reveals (?P<cards>\w+ \w+) with a (?P<ranking>\w+)")
def step_when_player_reveals(context, name, cards, ranking):
    """A CardsRevealed event with the named hand ranking."""
    card_list = [parse_card(c.strip()) for c in cards.split()]
    ranking_enum = getattr(poker_types, ranking.upper(), poker_types.HIGH_CARD)
    event = hand.CardsRevealed(
        player_root=b"player-1",
        cards=card_list,
        ranking=poker_types.HandRanking(rank_type=ranking_enum),
        revealed_at=make_timestamp(),
    )
    _handle(context, event)


@when(r"(?P<name>\w+) mucks (?:her|his|their) cards")
def step_when_player_mucks(context, name):
    """A CardsMucked event."""
    _handle(context, hand.CardsMucked(player_root=b"player-1"))


@when(r"(?P<name>\w+) wins a pot of (?P<amount>\d+)")
def step_when_player_wins_pot(context, name, amount):
    """A PotAwarded event with the named winner + amount."""
    event = hand.PotAwarded()
    event.winners.append(
        hand.PotWinner(
            player_root=b"player-1",
            amount=int(amount),
            pot_type="main",
        )
    )
    _handle(context, event)


@when(r"(?P<name>\w+) times out and is auto-folded")
def step_when_player_times_out(context, name):
    """A PlayerTimedOut event with default_action FOLD."""
    event = hand.PlayerTimedOut(
        player_root=b"player-1",
        default_action=poker_types.FOLD,
        timed_out_at=make_timestamp(),
    )
    _handle(context, event)


# =============================================================================
# When steps — card formatting and player resolution
# =============================================================================


@when(r"cards are shown for each suit:")
def step_when_cards_shown_per_suit(context):
    """Format one card per suit row."""
    context.cards_output = ""
    for row in context.table:
        row_dict = {
            context.table.headings[i]: row[i]
            for i in range(len(context.table.headings))
        }
        rank = int(row_dict.get("rank", 2))
        suit_name = row_dict.get("suit", "SPADES")
        suit = getattr(poker_types, suit_name)
        card = make_card(rank, suit)
        context.cards_output += format_card(card) + " "
    context.cards_output = context.cards_output.rstrip()


@when(r'an event references "(?P<player_id>[^"]+)"')
def step_when_event_references(context, player_id):
    """Translate the reference into a PlayerJoined event (renders the player name)."""
    player_root = uuid_for(player_id)
    event = table.PlayerJoined(
        player_root=player_root,
        seat_position=1,
        stack=500,
        buy_in_amount=500,
        joined_at=make_timestamp(),
    )
    event_book = types.EventBook(
        cover=types.Cover(root=types.UUID(value=b"table-1"), domain="table"),
        pages=[make_event_page(event)],
    )
    context.projector.handle_event_book(event_book)


@when(r'an event references an unknown player "(?P<player_id>[^"]+)"')
def step_when_event_references_unknown_player(context, player_id):
    """A PlayerJoined event whose player_root was never registered."""
    player_root = uuid_for(player_id)
    event = table.PlayerJoined(
        player_root=player_root,
        seat_position=1,
        stack=500,
        buy_in_amount=500,
        joined_at=make_timestamp(),
    )
    event_book = types.EventBook(
        cover=types.Cover(root=types.UUID(value=b"table-1"), domain="table"),
        pages=[make_event_page(event)],
    )
    context.projector.handle_event_book(event_book)


# =============================================================================
# When steps — timestamp + batch + unknown event
# =============================================================================


@when(r"an event happens at (?P<time>\d+:\d+:\d+)")
def step_when_event_happens_at(context, time):
    """A simple PlayerRegistered event with a specific created_at timestamp."""
    event = player.PlayerRegistered(
        display_name="Test",
        email="test@example.com",
        player_type=poker_types.HUMAN,
    )
    _handle(context, event, time_str=time)


@when(r"an event happens")
def step_when_event_happens(context):
    """A simple PlayerRegistered event with the default timestamp."""
    event = player.PlayerRegistered(
        display_name="Test",
        email="test@example.com",
        player_type=poker_types.HUMAN,
    )
    _handle(context, event)


@when(r"a batch of a PlayerJoined and a BlindPosted event is rendered")
def step_when_batch_of_two_events(context):
    """An event book carrying a PlayerJoined and a BlindPosted, processed as a batch."""
    event_book = types.EventBook(
        cover=types.Cover(root=types.UUID(value=b"player-1"), domain="table"),
        pages=[
            make_event_page(
                table.PlayerJoined(
                    player_root=b"player-1",
                    seat_position=1,
                    stack=500,
                    buy_in_amount=500,
                    joined_at=make_timestamp(),
                )
            ),
            make_event_page(
                hand.BlindPosted(
                    player_root=b"player-1",
                    blind_type="small",
                    amount=5,
                    pot_total=5,
                    player_stack=495,
                )
            ),
        ],
    )
    context.projector.handle_event_book(event_book)


@when(r"the display encounters an unfamiliar event")
def step_when_unfamiliar_event(context):
    """An event with an unknown type_url is fed to the projector."""
    page = types.EventPage(
        header=types.PageHeader(sequence=0),
        event=ProtoAny(
            type_url="type.poker/angzarr_client.proto.examples.v1.UnknownEvent"
        ),
        created_at=make_timestamp(),
    )
    context.projector.handle_event(page)


# =============================================================================
# Then steps — display assertions
# =============================================================================


@then(r'the display shows "(?P<text>[^"]+)"')
def step_then_display_shows(context, text):
    """Verify the display output contains the expected substring."""
    combined = "\n".join(context.output_lines)
    if hasattr(context, "cards_output"):
        combined += "\n" + context.cards_output
    assert text in combined, f"Expected '{text}' in:\n{combined}"


@then(r'the display line starts with "(?P<prefix>[^"]+)"')
def step_then_display_line_starts_with(context, prefix):
    """Verify the first display line starts with the expected prefix."""
    assert context.output_lines, "No output produced"
    assert context.output_lines[0].startswith(prefix), (
        f"Expected start '{prefix}' in:\n{context.output_lines[0]}"
    )


@then(r'the display line does not start with "(?P<prefix>[^"]+)"')
def step_then_display_line_not_starts_with(context, prefix):
    """Verify the first display line does NOT start with the prefix."""
    if context.output_lines:
        assert not context.output_lines[0].startswith(prefix), (
            f"Did not expect start '{prefix}' in:\n{context.output_lines[0]}"
        )


@then(r"both events appear in the display in order")
def step_then_both_events_in_order(context):
    """Verify two lines were rendered."""
    assert len(context.output_lines) == 2, (
        f"Expected 2 output lines, got {len(context.output_lines)}:\n"
        f"{context.output_lines}"
    )


@then(r'the display uses "(?P<name>[^"]+)"')
def step_then_display_uses(context, name):
    """Verify the display includes the named string (typically a player's display name)."""
    combined = "\n".join(context.output_lines)
    assert name in combined, f"Expected '{name}' in:\n{combined}"


@then(r'the display falls back to a short label starting with "(?P<prefix>[^"]+)"')
def step_then_display_falls_back(context, prefix):
    """Verify the unknown-player fallback label is used (typically Player_<hex>)."""
    combined = "\n".join(context.output_lines)
    # The renderer uses 'Player_' + hex; accept any 'Player_'-prefixed string.
    if prefix.startswith("Player_"):
        assert "Player_" in combined, f"Expected 'Player_' prefix in:\n{combined}"
    else:
        assert prefix in combined, f"Expected '{prefix}' in:\n{combined}"


# =============================================================================
# Then steps — card formatting
# =============================================================================


@then(r"ranks 2-9 display as digits")
def step_then_ranks_2_9_display_as_digits(context):
    """Verify every digit 2..9 appears in the formatted output."""
    for digit in "23456789":
        assert digit in context.cards_output, (
            f"Expected '{digit}' in:\n{context.cards_output}"
        )


@then(r'rank (?P<rank>\d+) displays as "(?P<symbol>[^"]+)"')
def step_then_rank_displays_as(context, rank, symbol):
    """Verify a specific rank's symbol appears in the formatted output."""
    if not hasattr(context, "cards_output"):
        # The display.shows "X" path doesn't populate cards_output; fall back
        # to the regular display assertions.
        combined = "\n".join(context.output_lines)
        assert symbol in combined, f"Expected '{symbol}' in:\n{combined}"
        return
    assert symbol in context.cards_output, (
        f"Expected '{symbol}' in:\n{context.cards_output}"
    )


@then(r"a (?P<rank>\d+) displays as \"(?P<symbol>[^\"]+)\"")
def step_then_a_rank_displays_as(context, rank, symbol):
    """Render a single card and verify its rank symbol appears."""
    rank_n = int(rank)
    if not hasattr(context, "cards_output"):
        context.cards_output = ""
    card = make_card(rank_n, poker_types.SPADES)
    context.cards_output += format_card(card) + " "
    assert symbol in context.cards_output, (
        f"Expected '{symbol}' in:\n{context.cards_output}"
    )


@then(r"a (?P<face>Jack|Queen|King) displays as \"(?P<symbol>[^\"]+)\"")
def step_then_face_card_displays_as(context, face, symbol):
    """Render a face card and verify its symbol."""
    if not hasattr(context, "cards_output"):
        context.cards_output = ""
    rank = {"Jack": 11, "Queen": 12, "King": 13}[face]
    card = make_card(rank, poker_types.SPADES)
    context.cards_output += format_card(card) + " "
    assert symbol in context.cards_output, (
        f"Expected '{symbol}' in:\n{context.cards_output}"
    )


@then(r"an Ace displays as \"(?P<symbol>[^\"]+)\"")
def step_then_ace_displays_as(context, symbol):
    """Render an Ace and verify the symbol."""
    if not hasattr(context, "cards_output"):
        context.cards_output = ""
    card = make_card(14, poker_types.SPADES)
    context.cards_output += format_card(card) + " "
    assert symbol in context.cards_output, (
        f"Expected '{symbol}' in:\n{context.cards_output}"
    )
