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
            from angzarr_client.proto.examples import (
                ai_sidecar_pb2,
                ai_sidecar_pb2_grpc,
            )

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

    def start_session(self, ai_player_root: bytes, model_id: str = "") -> bool:
        """Start a session on the sidecar. Returns True on success."""
        if not self._stub:
            return False
        pb = self._ai_player_pb2
        try:
            resp = self._stub.StartSession(
                pb.StartSessionRequest(
                    session_id=self._config.session_id,
                    ai_player_root=ai_player_root,
                    model_id=model_id,
                ),
                timeout=5.0,
            )
            return resp.success
        except grpc.RpcError as e:
            logger.error("start_session_failed", error=str(e))
            return False

    def end_session(self, persist_stats: bool = True) -> tuple[int, int]:
        """End the session on the sidecar. Returns (hands_played, total_result)."""
        if not self._stub:
            return (0, 0)
        pb = self._ai_player_pb2
        try:
            resp = self._stub.EndSession(
                pb.EndSessionRequest(
                    session_id=self._config.session_id,
                    persist_stats=persist_stats,
                ),
                timeout=5.0,
            )
            return (resp.hands_played, resp.total_result)
        except grpc.RpcError as e:
            logger.error("end_session_failed", error=str(e))
            return (0, 0)

    def record_experience(
        self,
        snapshot: dict,
        hand_id: bytes,
        action: int,
        amount: int,
        reward: float,
        log_prob: float = 0.0,
        value_estimate: float = 0.0,
        terminal: bool = True,
    ) -> int:
        """Record one experience tuple for replay/training.

        Returns the experience_id assigned by the server, or 0 on failure.
        """
        if not self._stub:
            return 0

        pb = self._ai_player_pb2
        context = pb.ActionContext(
            session_id=self._config.session_id,
            player_root=self._config.player_root,
            hand_id=hand_id,
            snapshot=self._build_action_request(snapshot),
        )
        experience = pb.Experience(
            context=context,
            action_taken=action,
            amount=amount,
            log_prob=log_prob,
            value_estimate=value_estimate,
            reward=reward,
            terminal=terminal,
        )
        try:
            resp = self._stub.RecordExperience(experience, timeout=5.0)
            if not resp.success:
                logger.warning("record_experience_rejected", message=resp.message)
                return 0
            return resp.experience_id
        except grpc.RpcError as e:
            logger.error("record_experience_failed", error=str(e))
            return 0

    def get_opponent_stats(self, player_roots: list[bytes]) -> dict[bytes, dict]:
        """Query persistent opponent profiles by player_root."""
        if not self._stub or not player_roots:
            return {}
        pb = self._ai_player_pb2
        try:
            resp = self._stub.GetOpponentStats(
                pb.OpponentQuery(player_roots=player_roots),
                timeout=5.0,
            )
        except grpc.RpcError as e:
            logger.error("get_opponent_stats_failed", error=str(e))
            return {}

        out: dict[bytes, dict] = {}
        for p in resp.profiles:
            out[p.player_root] = {
                "total_hands": p.total_hands,
                "vpip": p.vpip,
                "pfr": p.pfr,
                "af": p.af,
                "wtsd": p.wtsd,
                "w_sd": p.w_sd,
                "avg_decision_time_ms": p.avg_decision_time_ms,
                "hands_since_update": p.hands_since_update,
            }
        return out

    def reload_model(self, model_path: str, model_id: str = "") -> str:
        """Hot-reload sidecar model weights. Returns new model_version or empty string on failure."""
        if not self._stub:
            return ""
        pb = self._ai_player_pb2
        try:
            resp = self._stub.ReloadModel(
                pb.ReloadModelRequest(model_id=model_id, model_path=model_path),
                timeout=30.0,
            )
            return resp.model_version if resp.success else ""
        except grpc.RpcError as e:
            logger.error("reload_model_failed", error=str(e))
            return ""

    def _build_action_request(self, snapshot: dict):
        """Build an ActionRequest proto from a snapshot dict (shared by get_action and record_experience)."""
        pb = self._ai_player_pb2
        return pb.ActionRequest(
            model_id=self._config.session_id,
            game_variant=snapshot.get("game_variant", 1),
            phase=snapshot.get("phase", 1),
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
        )

    def close(self) -> None:
        """Close the gRPC channel."""
        if self._channel:
            self._channel.close()
