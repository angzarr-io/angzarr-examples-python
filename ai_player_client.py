"""AI Player gRPC client for run_game.py integration."""

from __future__ import annotations

import grpc
import structlog
from dataclasses import dataclass

# Import proto modules (from buf registry via angzarr_client)
try:
    from angzarr_client.proto.examples import poker_types_pb2 as types_pb2
except ImportError:
    from ai_player.proto.examples import poker_types_pb2 as types_pb2

logger = structlog.get_logger()


@dataclass
class AiPlayerConfig:
    """Configuration for AI Player client."""

    address: str
    session_id: str
    player_root: bytes


class AiPlayerClient:
    """gRPC client for AI Player service."""

    def __init__(self, config: AiPlayerConfig) -> None:
        """Initialize AI Player client.

        Args:
            config: Client configuration including service address.
        """
        self._config = config
        self._channel = grpc.insecure_channel(config.address)
        self._stub = None
        self._action_history: list = []  # Action history for context

        # Lazy import proto modules
        self._import_protos()

    def _import_protos(self) -> None:
        """Import AI Player proto modules."""
        try:
            # Try importing from angzarr_client proto package
            from angzarr_client.proto.examples import ai_sidecar_pb2, ai_sidecar_pb2_grpc

            self._ai_player_pb2 = ai_sidecar_pb2
            self._stub = ai_sidecar_pb2_grpc.AiSidecarStub(self._channel)
            logger.info("ai_player_client_connected", address=self._config.address)
        except ImportError:
            try:
                # Fallback to ai_player proto package
                from ai_player.proto.examples import ai_sidecar_pb2, ai_sidecar_pb2_grpc

                self._ai_player_pb2 = ai_sidecar_pb2
                self._stub = ai_sidecar_pb2_grpc.AiSidecarStub(self._channel)
                logger.info("ai_player_client_connected", address=self._config.address)
            except ImportError:
                logger.warning(
                    "ai_player_proto_not_found",
                    msg="AI Player protos not available",
                )
                self._stub = None

    def is_connected(self) -> bool:
        """Check if client is connected to AI Player service."""
        return self._stub is not None

    def get_action(
        self,
        snapshot: dict,
        hand_id: bytes,
    ) -> tuple[int, int]:
        """Get action recommendation from AI Player.

        Args:
            snapshot: Current game state as dict.
            hand_id: Current hand identifier.

        Returns:
            Tuple of (action_type, amount).
        """
        if not self._stub:
            # Fallback to random if not connected
            return self._random_action(snapshot)

        pb2 = self._ai_player_pb2

        # Build ActionRequest directly (matches ai_sidecar.proto)
        request = pb2.ActionRequest(
            model_id=self._config.session_id,
            game_variant=snapshot.get("game_variant", 1),  # TEXAS_HOLDEM
            phase=snapshot.get("phase", 1),  # PREFLOP
            hole_cards=[
                types_pb2.Card(suit=c["suit"], rank=c["rank"])
                for c in snapshot.get("hole_cards", [])
            ],
            community_cards=[
                types_pb2.Card(suit=c["suit"], rank=c["rank"])
                for c in snapshot.get("community_cards", [])
            ],
            pot_size=snapshot.get("pot_size", 0),
            stack_size=snapshot.get("stack_size", 0),
            amount_to_call=snapshot.get("amount_to_call", 0),
            min_raise=snapshot.get("min_raise", 0),
            max_raise=snapshot.get("max_raise", 0),
            position=snapshot.get("position", 0),
            players_remaining=snapshot.get("players_remaining", 0),
            players_to_act=snapshot.get("players_to_act", 0),
            # Action history for recurrent models
            action_history=self._action_history,
            # Opponent stats
            opponents=[
                pb2.OpponentStats(
                    player_root=opp.get("player_root", b""),
                    position=opp.get("position", 0),
                    stack=opp.get("stack", 0),
                    vpip=0.0,  # Will be populated from AI Player's database
                    pfr=0.0,
                    aggression=0.0,
                    hands_played=0,
                )
                for opp in snapshot.get("opponents", [])
            ],
        )

        try:
            response = self._stub.GetAction(request, timeout=5.0)
            logger.debug(
                "ai_action_received",
                action=response.recommended_action,
                amount=response.amount,
                inference_ms=response.inference_time_ms,
            )
            return response.recommended_action, response.amount
        except grpc.RpcError as e:
            logger.error("ai_player_rpc_error", error=str(e))
            return self._random_action(snapshot)

    def _random_action(self, snapshot: dict) -> tuple[int, int]:
        """Fallback random action when AI Player unavailable."""
        import random

        to_call = snapshot.get("amount_to_call", 0)
        stack = snapshot.get("stack_size", 0)

        if to_call == 0:
            # Check
            return types_pb2.CHECK, 0
        elif random.random() < 0.7:
            # Call
            return types_pb2.CALL, min(to_call, stack)
        else:
            # Fold
            return types_pb2.FOLD, 0

    def add_action(
        self,
        player_root: bytes,
        action: int,
        amount: int,
        phase: int,
    ) -> None:
        """Add an action to history for context tracking.

        Args:
            player_root: Player who took the action.
            action: ActionType enum value.
            amount: Bet/raise amount.
            phase: BettingPhase enum value.
        """
        if not self._stub:
            return

        pb2 = self._ai_player_pb2

        action_hist = pb2.ActionHistory(
            player_root=player_root,
            action=action,
            amount=amount,
            phase=phase,
        )
        self._action_history.append(action_hist)

    def clear_history(self) -> None:
        """Clear action history (call at hand start)."""
        self._action_history = []

    def record_experience(
        self,
        context: dict,
        action: int,
        amount: int,
        reward: float,
        terminal: bool = True,
    ) -> bool:
        """Record experience for training.

        Args:
            context: Game state context.
            action: Action taken.
            amount: Bet/raise amount.
            reward: Chips won/lost.
            terminal: Whether hand is complete.

        Returns:
            True if recorded successfully.
        """
        if not self._stub:
            return False

        # TODO: Build Experience proto and call RecordExperience
        return True

    def close(self) -> None:
        """Close the gRPC channel."""
        if self._channel:
            self._channel.close()
