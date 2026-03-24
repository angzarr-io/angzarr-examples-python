"""Encode game state to neural network input tensor."""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from numpy.typing import NDArray
    from ai_player.proto.examples import ai_sidecar_pb2, poker_types_pb2
    from ai_player.state.session import SessionState


class ActionContextEncoder:
    """Encode ActionRequest proto to fixed-size tensor.

    Features encoded:
    - Card representations (52-dim one-hot per card)
    - Betting context (normalized pot, stack, bet amounts)
    - Position features
    - Opponent statistics
    - Action history encoding
    """

    # Feature dimensions
    CARD_DIM = 52  # One-hot encoding for each card
    MAX_HOLE_CARDS = 4  # For Omaha support
    MAX_COMMUNITY_CARDS = 5
    BETTING_FEATURES = 10
    POSITION_FEATURES = 5
    OPPONENT_FEATURES = 8  # Per opponent stats (OpponentStats proto)
    MAX_OPPONENTS = 9
    ACTION_HISTORY_DIM = 32

    OUTPUT_DIM = 256

    def __init__(self) -> None:
        """Initialize encoder."""
        pass

    def encode(
        self,
        request: ai_sidecar_pb2.ActionRequest,
        session: SessionState | None = None,
        opponent_profiles: dict[bytes, dict] | None = None,
    ) -> NDArray[np.float32]:
        """Encode full context to tensor.

        Args:
            request: ActionRequest with game state.
            session: Optional session state for additional context.
            opponent_profiles: Optional persistent opponent profiles from DB.

        Returns:
            Feature tensor of shape (OUTPUT_DIM,).
        """
        features = []

        # Encode hole cards
        hole_card_features = self._encode_cards(
            list(request.hole_cards),
            self.MAX_HOLE_CARDS,
        )
        features.extend(hole_card_features)

        # Encode community cards
        community_features = self._encode_cards(
            list(request.community_cards),
            self.MAX_COMMUNITY_CARDS,
        )
        features.extend(community_features)

        # Encode betting context
        betting_features = self._encode_betting(request)
        features.extend(betting_features)

        # Encode position
        position_features = self._encode_position(request)
        features.extend(position_features)

        # Encode betting phase
        phase_features = self._encode_phase(request.phase)
        features.extend(phase_features)

        # Encode opponent info
        opponent_features = self._encode_opponents(
            list(request.opponents),
            opponent_profiles or {},
        )
        features.extend(opponent_features)

        # Convert to numpy and pad/truncate to OUTPUT_DIM
        feature_array = np.array(features, dtype=np.float32)

        if len(feature_array) < self.OUTPUT_DIM:
            # Pad with zeros
            feature_array = np.pad(
                feature_array,
                (0, self.OUTPUT_DIM - len(feature_array)),
            )
        elif len(feature_array) > self.OUTPUT_DIM:
            # Truncate (should not happen with proper sizing)
            feature_array = feature_array[: self.OUTPUT_DIM]

        return feature_array

    def _encode_cards(
        self,
        cards: list[poker_types_pb2.Card],
        max_cards: int,
    ) -> list[float]:
        """Encode cards to one-hot representation.

        Args:
            cards: List of Card proto messages.
            max_cards: Maximum number of cards to encode.

        Returns:
            Flattened one-hot features.
        """
        features = []

        for i in range(max_cards):
            if i < len(cards):
                card = cards[i]
                # Card index: (suit - 1) * 13 + (rank - 2)
                # Suit: 1-4 (CLUBS to SPADES)
                # Rank: 2-14 (TWO to ACE)
                suit_idx = max(0, card.suit - 1)
                rank_idx = max(0, card.rank - 2)
                card_idx = suit_idx * 13 + rank_idx

                # One-hot encoding
                one_hot = [0.0] * self.CARD_DIM
                if 0 <= card_idx < self.CARD_DIM:
                    one_hot[card_idx] = 1.0
                features.extend(one_hot)
            else:
                # No card - all zeros
                features.extend([0.0] * self.CARD_DIM)

        return features

    def _encode_betting(
        self,
        request: ai_sidecar_pb2.ActionRequest,
    ) -> list[float]:
        """Encode betting context features.

        Args:
            request: ActionRequest with game state.

        Returns:
            Normalized betting features.
        """
        # Normalize by big blind (assume 100 for now)
        bb = 100.0

        # Calculate pot odds
        pot_odds = 0.0
        if request.pot_size > 0 and request.amount_to_call > 0:
            pot_odds = request.amount_to_call / (
                request.pot_size + request.amount_to_call
            )

        # Stack-to-pot ratio
        spr = 0.0
        if request.pot_size > 0:
            spr = min(10.0, request.stack_size / request.pot_size)

        return [
            request.pot_size / bb / 100.0,  # Normalized pot
            request.stack_size / bb / 100.0,  # Normalized stack
            request.amount_to_call / bb / 10.0,  # Normalized call amount
            request.min_raise / bb / 10.0,  # Normalized min raise
            request.max_raise / bb / 100.0,  # Normalized max raise
            pot_odds,  # Pot odds [0, 1]
            spr / 10.0,  # Normalized SPR
            1.0 if request.amount_to_call == 0 else 0.0,  # Check available
            1.0 if request.amount_to_call > 0 else 0.0,  # Facing bet
            1.0 if request.stack_size <= request.amount_to_call else 0.0,  # All-in required
        ]

    def _encode_position(
        self,
        request: ai_sidecar_pb2.ActionRequest,
    ) -> list[float]:
        """Encode position features.

        Args:
            request: ActionRequest with game state.

        Returns:
            Position features.
        """
        max_positions = 10

        return [
            request.position / max_positions,  # Normalized position
            1.0 if request.position == 0 else 0.0,  # Is button
            1.0 if request.position == 1 else 0.0,  # Is small blind
            1.0 if request.position == 2 else 0.0,  # Is big blind
            request.players_remaining / max_positions,  # Players remaining
            request.players_to_act / max_positions,  # Players to act
        ]

    def _encode_phase(self, phase: int) -> list[float]:
        """Encode betting phase as one-hot.

        Args:
            phase: BettingPhase enum value.

        Returns:
            One-hot encoded phase.
        """
        # Phases: PREFLOP=1, FLOP=2, TURN=3, RIVER=4
        phases = [0.0] * 5
        if 1 <= phase <= 4:
            phases[phase] = 1.0
        return phases

    def _encode_opponents(
        self,
        opponents: list[ai_sidecar_pb2.OpponentStats],
        profiles: dict[bytes, dict],
    ) -> list[float]:
        """Encode opponent information.

        Args:
            opponents: List of OpponentStats from request.
            profiles: Persistent opponent profiles from DB.

        Returns:
            Encoded opponent features.
        """
        features = []

        for i in range(self.MAX_OPPONENTS):
            if i < len(opponents):
                opp = opponents[i]
                # Merge proto stats with DB profiles
                db_profile = profiles.get(opp.player_root, {})

                features.extend([
                    opp.position / 10.0,  # Position
                    opp.stack / 10000.0,  # Normalized stack
                    # Use proto stats (from request) or fall back to DB
                    opp.vpip if opp.vpip > 0 else db_profile.get("vpip", 0.5),
                    opp.pfr if opp.pfr > 0 else db_profile.get("pfr", 0.2),
                    opp.aggression if opp.aggression > 0 else db_profile.get("af", 1.0),
                    # Hands played (confidence indicator)
                    min(1.0, opp.hands_played / 100.0) if opp.hands_played > 0 else min(1.0, db_profile.get("total_hands", 0) / 100.0),
                    # DB-only stats
                    db_profile.get("wtsd", 0.3),
                    1.0,  # Opponent present flag
                ])
            else:
                # No opponent in this slot
                features.extend([0.0] * self.OPPONENT_FEATURES)

        return features
