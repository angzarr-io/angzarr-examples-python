"""AI Player gRPC service implementation."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import grpc
import structlog

from ai_player.state.session import SessionManager
from ai_player.models.poker_net import PokerNet
from ai_player.models.encoder import ActionContextEncoder
from ai_player.state.persistence import ExperienceStore, OpponentProfileStore

if TYPE_CHECKING:
    from ai_player.proto.examples import ai_sidecar_pb2 as ai_player_pb2
    from ai_player.proto.examples import ai_sidecar_pb2_grpc as ai_player_pb2_grpc
    from ai_player.proto.examples import poker_types_pb2

logger = structlog.get_logger()


@dataclass
class ServiceConfig:
    """Configuration for AI Player service."""

    model_path: str | None = None
    database_url: str | None = None
    device: str = "cpu"


class AiPlayerServicer:
    """gRPC servicer for AI Player inference and state management."""

    def __init__(self, config: ServiceConfig) -> None:
        """Initialize the AI Player servicer.

        Args:
            config: Service configuration including model path and database URL.
        """
        self._config = config
        self._session_manager = SessionManager()
        self._model: PokerNet | None = None
        self._encoder = ActionContextEncoder()
        self._experience_store: ExperienceStore | None = None
        self._opponent_store: OpponentProfileStore | None = None
        self._requests_served = 0
        self._start_time = time.time()

        self._load_model()
        self._connect_database()

    def _load_model(self) -> None:
        """Load the PyTorch model from disk."""
        if self._config.model_path:
            try:
                self._model = PokerNet.load(
                    self._config.model_path,
                    device=self._config.device,
                )
                logger.info(
                    "model_loaded",
                    path=self._config.model_path,
                    device=self._config.device,
                )
            except FileNotFoundError:
                logger.warning(
                    "model_not_found",
                    path=self._config.model_path,
                )
                self._model = PokerNet(device=self._config.device)
        else:
            logger.info("using_random_model")
            self._model = PokerNet(device=self._config.device)

    def _connect_database(self) -> None:
        """Connect to the database for state persistence."""
        if self._config.database_url:
            try:
                self._experience_store = ExperienceStore(self._config.database_url)
                self._opponent_store = OpponentProfileStore(self._config.database_url)
                logger.info("database_connected", url=self._config.database_url)
            except Exception as e:
                logger.error("database_connection_failed", error=str(e))
        else:
            logger.info("no_database_configured")

    def GetAction(
        self,
        request: ai_player_pb2.ActionRequest,
        context: grpc.ServicerContext,
    ) -> ai_player_pb2.ActionResponse:
        """Get recommended action for the current game state.

        Args:
            request: ActionRequest with game state and history.
            context: gRPC context.

        Returns:
            ActionResponse with recommended action and probabilities.
        """
        from ai_player.proto.examples import ai_sidecar_pb2 as ai_player_pb2, poker_types_pb2

        start_time = time.time()
        self._requests_served += 1

        # Get or create session using model_id as session identifier
        session_id = request.model_id or "default"
        session = self._session_manager.get_or_create(
            session_id=session_id,
            player_root=b"",  # ActionRequest doesn't include player_root
        )

        # Update session with action history
        session.update_from_action_history(request.action_history)

        # Load opponent profiles from database
        opponent_profiles = {}
        if self._opponent_store:
            opponent_roots = [opp.player_root for opp in request.opponents]
            opponent_profiles = self._opponent_store.get_profiles(opponent_roots)

        # Encode context to tensor (passing ActionRequest directly)
        state_tensor = self._encoder.encode(
            request=request,
            session=session,
            opponent_profiles=opponent_profiles,
        )

        # Run model inference
        action, amount, probabilities, value = self._model.predict(state_tensor)

        inference_time_ms = int((time.time() - start_time) * 1000)

        return ai_player_pb2.ActionResponse(
            recommended_action=action,
            amount=amount,
            fold_probability=probabilities[0],
            check_call_probability=probabilities[1],
            bet_raise_probability=probabilities[2],
            model_version=self._model.version if self._model else "random",
            inference_time_ms=inference_time_ms,
        )

    def RecordExperience(
        self,
        request: ai_player_pb2.Experience,
        context: grpc.ServicerContext,
    ) -> ai_player_pb2.RecordResponse:
        """Record experience for training.

        Args:
            request: Experience with context, action, and reward.
            context: gRPC context.

        Returns:
            RecordResponse indicating success.
        """
        from ai_player.proto.examples import ai_sidecar_pb2 as ai_player_pb2

        if not self._experience_store:
            return ai_player_pb2.RecordResponse(
                success=False,
                message="No database configured for experience storage",
            )

        try:
            experience_id = self._experience_store.store(request)
            return ai_player_pb2.RecordResponse(
                success=True,
                message="Experience recorded",
                experience_id=experience_id,
            )
        except Exception as e:
            logger.error("experience_store_failed", error=str(e))
            return ai_player_pb2.RecordResponse(
                success=False,
                message=f"Failed to store experience: {e}",
            )

    def GetOpponentStats(
        self,
        request: ai_player_pb2.OpponentQuery,
        context: grpc.ServicerContext,
    ) -> ai_player_pb2.OpponentStatsResponse:
        """Query opponent statistics from persistent storage.

        Args:
            request: Query with player roots to look up.
            context: gRPC context.

        Returns:
            OpponentStatsResponse with profiles for requested players.
        """
        from ai_player.proto.examples import ai_sidecar_pb2 as ai_player_pb2

        if not self._opponent_store:
            return ai_player_pb2.OpponentStatsResponse(profiles=[])

        profiles = self._opponent_store.get_profiles(list(request.player_roots))
        return ai_player_pb2.OpponentStatsResponse(
            profiles=[
                self._convert_profile_to_proto(root, profile)
                for root, profile in profiles.items()
            ]
        )

    def _convert_profile_to_proto(
        self,
        player_root: bytes,
        profile: dict,
    ) -> ai_player_pb2.OpponentProfile:
        """Convert internal profile dict to proto message."""
        from ai_player.proto.examples import ai_sidecar_pb2 as ai_player_pb2

        return ai_player_pb2.OpponentProfile(
            player_root=player_root,
            total_hands=profile.get("total_hands", 0),
            vpip=profile.get("vpip", 0.0),
            pfr=profile.get("pfr", 0.0),
            af=profile.get("af", 0.0),
            wtsd=profile.get("wtsd", 0.0),
            w_sd=profile.get("w_sd", 0.0),
            avg_decision_time_ms=profile.get("avg_decision_time_ms", 0.0),
            hands_since_update=profile.get("hands_since_update", 0),
        )

    def StartSession(
        self,
        request: ai_player_pb2.StartSessionRequest,
        context: grpc.ServicerContext,
    ) -> ai_player_pb2.StartSessionResponse:
        """Start a new session explicitly.

        Args:
            request: Session configuration.
            context: gRPC context.

        Returns:
            StartSessionResponse with session details.
        """
        from ai_player.proto.examples import ai_sidecar_pb2 as ai_player_pb2

        session = self._session_manager.create(
            session_id=request.session_id,
            player_root=request.ai_player_root,
            model_id=request.model_id,
        )

        return ai_player_pb2.StartSessionResponse(
            success=True,
            session_id=session.session_id,
            model_version=self._model.version if self._model else "random",
        )

    def EndSession(
        self,
        request: ai_player_pb2.EndSessionRequest,
        context: grpc.ServicerContext,
    ) -> ai_player_pb2.EndSessionResponse:
        """End session and optionally persist state.

        Args:
            request: Session to end.
            context: gRPC context.

        Returns:
            EndSessionResponse with session summary.
        """
        from ai_player.proto.examples import ai_sidecar_pb2 as ai_player_pb2

        session = self._session_manager.get(request.session_id)
        if not session:
            return ai_player_pb2.EndSessionResponse(
                success=False,
                hands_played=0,
                total_result=0,
            )

        # Persist opponent stats if requested
        if request.persist_stats and self._opponent_store:
            self._opponent_store.update_from_session(session)

        # Get session summary before removing
        hands_played = session.hands_played
        total_result = session.total_result

        # Remove session
        self._session_manager.remove(request.session_id)

        return ai_player_pb2.EndSessionResponse(
            success=True,
            hands_played=hands_played,
            total_result=total_result,
        )

    def Health(
        self,
        request: ai_player_pb2.HealthRequest,
        context: grpc.ServicerContext,
    ) -> ai_player_pb2.HealthResponse:
        """Health check endpoint.

        Args:
            request: Empty health request.
            context: gRPC context.

        Returns:
            HealthResponse with service status.
        """
        from ai_player.proto.examples import ai_sidecar_pb2 as ai_player_pb2

        db_connected = self._experience_store is not None
        experience_count = 0
        profile_count = 0

        if self._experience_store:
            experience_count = self._experience_store.count()
        if self._opponent_store:
            profile_count = self._opponent_store.count()

        # Note: ai_sidecar_pb2.HealthResponse only has these fields
        return ai_player_pb2.HealthResponse(
            healthy=True,
            model_id=self._config.model_path or "random",
            model_version=self._model.version if self._model else "random",
            uptime_seconds=int(time.time() - self._start_time),
            requests_served=self._requests_served,
        )

    def GetActionsBatch(
        self,
        request: ai_player_pb2.BatchActionRequest,
        context: grpc.ServicerContext,
    ) -> ai_player_pb2.BatchActionResponse:
        """Batch inference for training/simulation.

        Args:
            request: Batch of action requests.
            context: gRPC context.

        Returns:
            BatchActionResponse with responses for each request.
        """
        from ai_player.proto.examples import ai_sidecar_pb2 as ai_player_pb2

        responses = []
        for req in request.requests:
            response = self.GetAction(req, context)
            responses.append(response)

        return ai_player_pb2.BatchActionResponse(responses=responses)
