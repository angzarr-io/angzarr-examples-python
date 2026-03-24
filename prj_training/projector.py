"""Training data projector - materializes hand events into training states.

This projector subscribes to hand domain events and builds a denormalized
training_states table optimized for ML training. It maintains in-memory
state for each hand and persists training examples when actions occur.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import structlog
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from angzarr_client.proto.angzarr import types_pb2 as types
from angzarr_client.proto.examples import hand_pb2 as hand
from angzarr_client.proto.examples import poker_types_pb2 as poker_types

from .schema import Base, ProjectorCheckpoint, TrainingState

if TYPE_CHECKING:
    from sqlalchemy.engine import Engine

logger = structlog.get_logger()


# Event type URL prefix
TYPE_PREFIX = "type.poker/examples."


@dataclass
class PlayerState:
    """In-memory state for a player within a hand."""

    player_root: bytes
    position: int = 0
    hole_cards: list[int] = field(default_factory=list)  # Encoded cards
    stack: int = 0
    bet_this_round: int = 0
    total_invested: int = 0
    folded: bool = False
    acted_this_round: bool = False


@dataclass
class HandState:
    """In-memory state for a hand being projected."""

    hand_root: str
    players: dict[bytes, PlayerState] = field(default_factory=dict)
    community_cards: list[int] = field(default_factory=list)
    pot_size: int = 0
    current_bet: int = 0
    phase: int = 1  # 1=preflop, 2=flop, 3=turn, 4=river
    dealer_position: int = 0
    big_blind: int = 100
    game_variant: str = "TEXAS_HOLDEM"
    pending_states: list[TrainingState] = field(default_factory=list)
    outcomes: dict[bytes, int] = field(default_factory=dict)


class TrainingProjector:
    """Projects hand events into training_states table.

    Maintains per-hand state in memory and writes TrainingState rows
    when ActionTaken events occur. Outcomes are assigned when HandComplete
    events arrive, then all pending states for that hand are persisted.
    """

    PROJECTOR_NAME = "prj-training"

    def __init__(self, database_url: str) -> None:
        """Initialize projector with database connection.

        Args:
            database_url: PostgreSQL connection string.
        """
        # Handle postgres:// vs postgresql:// URL scheme
        if database_url.startswith("postgres://"):
            database_url = database_url.replace("postgres://", "postgresql://", 1)
        self._engine = create_engine(database_url)
        self._hands: dict[str, HandState] = {}  # hand_root → HandState

        # Create tables if needed
        Base.metadata.create_all(self._engine)

        logger.info("training_projector_initialized", database=database_url.split("@")[-1])

    def handle(self, event_book: types.EventBook) -> types.Projection:
        """Handle an EventBook from the projector coordinator.

        Args:
            event_book: Events to process.

        Returns:
            Projection result with sequence info.
        """
        last_seq = 0

        # Get hand_root from cover (shared across all pages in the book)
        # Cover.root is a UUID message with a 'value' field containing bytes
        hand_root = ""
        if event_book.cover and event_book.cover.root and event_book.cover.root.value:
            hand_root = event_book.cover.root.value.hex()

        try:
            for page in event_book.pages:
                # Check if this page has an event payload
                if page.WhichOneof("payload") != "event":
                    continue

                event_any = page.event
                type_url = event_any.type_url

                # Track sequence from header
                if page.header and page.header.WhichOneof("sequence_type") == "sequence":
                    last_seq = page.header.sequence

                logger.debug(
                    "processing_event",
                    type_url=type_url,
                    hand_root=hand_root[:16] if hand_root else "none",
                    sequence=last_seq,
                )

                # Dispatch by event type
                try:
                    if type_url.endswith("CardsDealt"):
                        self._handle_cards_dealt(hand_root, event_any)

                    elif type_url.endswith("BlindPosted"):
                        self._handle_blind_posted(hand_root, event_any)

                    elif type_url.endswith("ActionTaken"):
                        self._handle_action_taken(hand_root, event_any, last_seq)

                    elif type_url.endswith("CommunityCardsDealt"):
                        self._handle_community_dealt(hand_root, event_any)

                    elif type_url.endswith("BettingRoundComplete"):
                        self._handle_betting_complete(hand_root, event_any)

                    elif type_url.endswith("PotAwarded"):
                        self._handle_pot_awarded(hand_root, event_any)

                    elif type_url.endswith("HandComplete"):
                        self._handle_hand_complete(hand_root, event_any)
                except Exception as e:
                    logger.error(
                        "event_handler_error",
                        type_url=type_url,
                        hand_root=hand_root[:16] if hand_root else "none",
                        error=str(e),
                        exc_info=True,
                    )
                    # Continue processing other events

        except Exception as e:
            logger.error("handle_error", error=str(e), exc_info=True)

        return types.Projection(
            cover=event_book.cover,
            projector=self.PROJECTOR_NAME,
            sequence=last_seq,
        )

    def _get_hand(self, hand_root: str) -> HandState:
        """Get or create hand state."""
        if hand_root not in self._hands:
            self._hands[hand_root] = HandState(hand_root=hand_root)
        return self._hands[hand_root]

    def _handle_cards_dealt(self, hand_root: str, event_any: types.Any) -> None:
        """Handle CardsDealt event - initialize hand state."""
        event = hand.CardsDealt()
        event_any.Unpack(event)

        state = self._get_hand(hand_root)
        state.dealer_position = event.dealer_position
        state.game_variant = poker_types.GameVariant.Name(event.game_variant)

        # Initialize players with hole cards
        for pc in event.player_cards:
            player_root = pc.player_root
            cards = [self._encode_card(c) for c in pc.cards]
            state.players[player_root] = PlayerState(
                player_root=player_root,
                hole_cards=cards,
            )

        # Set stacks and positions
        for p in event.players:
            if p.player_root in state.players:
                ps = state.players[p.player_root]
                ps.stack = p.stack
                ps.position = p.position

    def _handle_blind_posted(self, hand_root: str, event_any: types.Any) -> None:
        """Handle BlindPosted event - track blinds."""
        event = hand.BlindPosted()
        event_any.Unpack(event)

        state = self._get_hand(hand_root)
        state.pot_size = event.pot_total

        if event.player_root in state.players:
            ps = state.players[event.player_root]
            ps.stack = event.player_stack
            ps.bet_this_round = event.amount
            ps.total_invested += event.amount

        if event.blind_type == "big":
            state.current_bet = event.amount
            state.big_blind = event.amount

    def _handle_action_taken(
        self,
        hand_root: str,
        event_any: types.Any,
        sequence: int,
    ) -> None:
        """Handle ActionTaken event - capture training state then apply action."""
        event = hand.ActionTaken()
        event_any.Unpack(event)

        state = self._get_hand(hand_root)
        player_root = event.player_root

        if player_root not in state.players:
            return

        ps = state.players[player_root]

        # Count active players
        active = [p for p in state.players.values() if not p.folded]
        to_act = len([p for p in active if not p.acted_this_round])

        # Capture training state BEFORE applying action
        ts = TrainingState(
            hand_root=hand_root,
            sequence=sequence,
            player_root=player_root,
            # Hole cards
            hole_card_1=ps.hole_cards[0] if len(ps.hole_cards) > 0 else None,
            hole_card_2=ps.hole_cards[1] if len(ps.hole_cards) > 1 else None,
            # Community cards
            community_1=state.community_cards[0] if len(state.community_cards) > 0 else None,
            community_2=state.community_cards[1] if len(state.community_cards) > 1 else None,
            community_3=state.community_cards[2] if len(state.community_cards) > 2 else None,
            community_4=state.community_cards[3] if len(state.community_cards) > 3 else None,
            community_5=state.community_cards[4] if len(state.community_cards) > 4 else None,
            # Betting state
            pot_size=state.pot_size,
            stack_size=ps.stack,
            amount_to_call=max(0, state.current_bet - ps.bet_this_round),
            current_bet=state.current_bet,
            min_raise=state.current_bet + state.big_blind,
            # Position and phase
            position=ps.position,
            phase=state.phase,
            players_remaining=len(active),
            players_to_act=to_act,
            # Action taken
            action=event.action,
            amount=event.amount,
            # Metadata
            game_variant=state.game_variant,
            big_blind=state.big_blind,
        )
        state.pending_states.append(ts)

        # Apply action to state
        state.pot_size = event.pot_total
        ps.stack = event.player_stack
        ps.acted_this_round = True

        if event.action == poker_types.ActionType.FOLD:
            ps.folded = True
        elif event.action in (poker_types.ActionType.BET, poker_types.ActionType.RAISE):
            invested = event.amount - ps.bet_this_round
            ps.total_invested += invested
            ps.bet_this_round = event.amount
            state.current_bet = event.amount
        elif event.action == poker_types.ActionType.CALL:
            invested = state.current_bet - ps.bet_this_round
            ps.total_invested += invested
            ps.bet_this_round = state.current_bet

    def _handle_community_dealt(self, hand_root: str, event_any: types.Any) -> None:
        """Handle CommunityCardsDealt event."""
        event = hand.CommunityCardsDealt()
        event_any.Unpack(event)

        state = self._get_hand(hand_root)

        # Phase from enum
        state.phase = event.phase  # Already an int from proto enum

        # Update community cards from all_community_cards
        state.community_cards = [self._encode_card(c) for c in event.all_community_cards]

    def _handle_betting_complete(self, hand_root: str, event_any: types.Any) -> None:
        """Handle BettingRoundComplete event - reset round state."""
        event = hand.BettingRoundComplete()
        event_any.Unpack(event)

        state = self._get_hand(hand_root)

        # Reset for new betting round
        for ps in state.players.values():
            ps.bet_this_round = 0
            ps.acted_this_round = False
        state.current_bet = 0

    def _handle_pot_awarded(self, hand_root: str, event_any: types.Any) -> None:
        """Handle PotAwarded event - record winnings."""
        event = hand.PotAwarded()
        event_any.Unpack(event)

        state = self._get_hand(hand_root)

        for winner in event.winners:
            pr = winner.player_root
            state.outcomes[pr] = state.outcomes.get(pr, 0) + winner.amount

    def _handle_hand_complete(self, hand_root: str, event_any: types.Any) -> None:
        """Handle HandComplete event - finalize and persist training states."""
        event = hand.HandComplete()
        event_any.Unpack(event)

        state = self._get_hand(hand_root)

        # Compute net outcome for each player (winnings - invested)
        for player_root, ps in state.players.items():
            won = state.outcomes.get(player_root, 0)
            net = won - ps.total_invested
            state.outcomes[player_root] = net

        # Mark last action as terminal
        if state.pending_states:
            state.pending_states[-1].terminal = True

        # Assign rewards to all pending states
        for ts in state.pending_states:
            pr = ts.player_root
            if pr in state.outcomes:
                # Normalize reward by big blind
                ts.reward = state.outcomes[pr] / float(state.big_blind)

        # Persist to database
        self._persist_training_states(hand_root, state.pending_states)

        # Clean up hand state
        del self._hands[hand_root]

        logger.debug(
            "hand_projected",
            hand_root=hand_root[:8],
            states=len(state.pending_states),
        )

    def _persist_training_states(
        self,
        hand_root: str,
        states: list[TrainingState],
    ) -> None:
        """Persist training states to database (idempotent)."""
        if not states:
            return

        with Session(self._engine) as session:
            # Delete any existing states for this hand (idempotent replay)
            session.execute(
                text("DELETE FROM training_states WHERE hand_root = :root"),
                {"root": hand_root},
            )

            for ts in states:
                session.add(ts)

            # Update checkpoint
            checkpoint = session.get(ProjectorCheckpoint, self.PROJECTOR_NAME)
            if checkpoint is None:
                checkpoint = ProjectorCheckpoint(
                    projector_name=self.PROJECTOR_NAME,
                    domain="hand",
                )
                session.add(checkpoint)

            checkpoint.last_hand_root = hand_root
            checkpoint.hands_projected = (checkpoint.hands_projected or 0) + 1
            checkpoint.states_created = (checkpoint.states_created or 0) + len(states)

            session.commit()

    @staticmethod
    def _encode_card(card: hand.Card) -> int:
        """Encode card as single integer (0-51)."""
        return card.rank * 4 + card.suit
