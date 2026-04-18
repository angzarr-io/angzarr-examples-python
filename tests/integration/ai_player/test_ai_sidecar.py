"""Integration tests: AiSidecar RPC contract on the running container.

Every test hits the real production image via gRPC. These verify both the
Python client path and the language-agnostic claim — the same set of RPCs
and messages a C++/C#/Go client would see.
"""

from __future__ import annotations

import grpc
import pytest
from google.protobuf import descriptor_pb2
from grpc_health.v1 import health_pb2, health_pb2_grpc
from grpc_reflection.v1alpha import reflection_pb2, reflection_pb2_grpc


EXPECTED_RPCS = {
    "GetAction",
    "GetActionsBatch",
    "Health",
    "StartSession",
    "EndSession",
    "RecordExperience",
    "GetOpponentStats",
    "ReloadModel",
}


def _reflection_list(channel) -> set[str]:
    reflect_stub = reflection_pb2_grpc.ServerReflectionStub(channel)
    req = reflection_pb2.ServerReflectionRequest(list_services="")
    responses = reflect_stub.ServerReflectionInfo(iter([req]))
    out: set[str] = set()
    for resp in responses:
        for svc in resp.list_services_response.service:
            out.add(svc.name)
    return out


def _reflection_describe_methods(channel, symbol: str) -> set[str]:
    reflect_stub = reflection_pb2_grpc.ServerReflectionStub(channel)
    req = reflection_pb2.ServerReflectionRequest(file_containing_symbol=symbol)
    responses = reflect_stub.ServerReflectionInfo(iter([req]))
    methods: set[str] = set()
    for resp in responses:
        for raw in resp.file_descriptor_response.file_descriptor_proto:
            fd = descriptor_pb2.FileDescriptorProto()
            fd.ParseFromString(raw)
            for svc in fd.service:
                if f"{fd.package}.{svc.name}" == symbol:
                    methods.update(m.name for m in svc.method)
    return methods


class TestReflection:
    def test_lists_aisidecar_and_health_services(self, channel):
        services = _reflection_list(channel)
        assert "examples.AiSidecar" in services
        assert "grpc.health.v1.Health" in services
        assert "grpc.reflection.v1alpha.ServerReflection" in services

    def test_aisidecar_exposes_all_eight_rpcs(self, channel):
        methods = _reflection_describe_methods(channel, "examples.AiSidecar")
        assert methods == EXPECTED_RPCS, (
            f"missing: {EXPECTED_RPCS - methods}, extra: {methods - EXPECTED_RPCS}"
        )


class TestHealth:
    def test_standard_grpc_health_serving(self, channel):
        health_stub = health_pb2_grpc.HealthStub(channel)
        resp = health_stub.Check(
            health_pb2.HealthCheckRequest(service="examples.AiSidecar")
        )
        assert resp.status == health_pb2.HealthCheckResponse.SERVING

    def test_aisidecar_health_rpc_populates_metadata(self, stub, pb):
        resp = stub.Health(pb.HealthRequest())
        assert resp.healthy is True
        assert resp.model_id  # some non-empty id
        assert resp.model_version
        assert resp.uptime_seconds >= 0


class TestSessions:
    def test_start_end_session_roundtrip(self, stub, pb):
        start = stub.StartSession(
            pb.StartSessionRequest(
                session_id="it-session-1",
                ai_player_root=b"\x01\x02\x03",
                model_id="m1",
            )
        )
        assert start.success is True
        assert start.session_id == "it-session-1"

        end = stub.EndSession(
            pb.EndSessionRequest(session_id="it-session-1", persist_stats=False)
        )
        assert end.success is True

    def test_end_missing_session_returns_failure(self, stub, pb):
        end = stub.EndSession(
            pb.EndSessionRequest(session_id="nope-never-started")
        )
        assert end.success is False


class TestDecisioning:
    def test_get_action_returns_valid_response(self, stub, pb):
        req = pb.ActionRequest(
            model_id="default",
            game_variant=1,  # TEXAS_HOLDEM
            phase=1,         # PREFLOP
            pot_size=30,
            stack_size=1000,
            amount_to_call=10,
            min_raise=10,
            max_raise=1000,
            position=3,
            players_remaining=6,
            players_to_act=4,
        )
        resp = stub.GetAction(req)
        # Action is a valid proto enum (non-UNSPECIFIED).
        assert resp.recommended_action != 0
        # Probabilities are well-formed floats in [0,1] and roughly normalized.
        for p in (
            resp.fold_probability,
            resp.check_call_probability,
            resp.bet_raise_probability,
        ):
            assert 0.0 <= p <= 1.0
        total = (
            resp.fold_probability
            + resp.check_call_probability
            + resp.bet_raise_probability
        )
        assert 0.99 <= total <= 1.01
        assert resp.model_version

    def test_get_actions_batch_matches_input_size(self, stub, pb):
        req_one = pb.ActionRequest(
            model_id="default", game_variant=1, phase=1,
            pot_size=20, stack_size=1000, amount_to_call=10,
        )
        req_two = pb.ActionRequest(
            model_id="default", game_variant=1, phase=2,
            pot_size=100, stack_size=950, amount_to_call=0,
        )
        resp = stub.GetActionsBatch(pb.BatchActionRequest(requests=[req_one, req_two]))
        assert len(resp.responses) == 2


class TestOpponentStats:
    def test_returns_empty_without_persistent_storage(self, stub, pb):
        # The default production container boots without DATABASE_URL set,
        # so the profile store is unconfigured and queries return empty.
        resp = stub.GetOpponentStats(
            pb.OpponentQuery(player_roots=[b"\xaa" * 32])
        )
        assert list(resp.profiles) == []


class TestExperienceRecording:
    def test_without_db_reports_failure_with_message(self, stub, pb):
        # No DATABASE_URL → experience store unconfigured. The server must
        # return a clean success=False rather than crashing or 500-ing.
        resp = stub.RecordExperience(
            pb.Experience(action_taken=1, amount=10, reward=0.5, terminal=True)
        )
        assert resp.success is False
        assert "database" in resp.message.lower()


class TestModelReload:
    def test_missing_path_returns_invalid_argument(self, stub, pb):
        with pytest.raises(grpc.RpcError) as excinfo:
            stub.ReloadModel(pb.ReloadModelRequest(model_path=""))
        assert excinfo.value.code() == grpc.StatusCode.INVALID_ARGUMENT

    def test_nonexistent_path_returns_not_found(self, stub, pb):
        with pytest.raises(grpc.RpcError) as excinfo:
            stub.ReloadModel(
                pb.ReloadModelRequest(model_path="/no/such/checkpoint.pt")
            )
        assert excinfo.value.code() == grpc.StatusCode.NOT_FOUND
