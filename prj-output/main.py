"""Projector: Output (OO Pattern)

Subscribes to player, table, and hand domain events.
Writes formatted game logs to a file.

This is the OO-style implementation using the new Router API with
@projector and @handles decorators.
"""

import os
from datetime import datetime

from angzarr_client import (
    ProjectorGrpc,
    Router,
    handles,
    projector,
    run_server,
)
from angzarr_client.proto.angzarr import projector_pb2_grpc
from angzarr_client.proto.examples import hand_pb2 as hand
from angzarr_client.proto.examples import player_pb2 as player
from angzarr_client.proto.examples import table_pb2 as table

_log_file = None


def get_log_file():
    """Get or create log file handle."""
    global _log_file
    if _log_file is None:
        path = os.environ.get("HAND_LOG_FILE", "hand_log_oo.txt")
        _log_file = open(path, "a")
    return _log_file


def write_log(msg: str) -> None:
    """Write timestamped message to log file."""
    f = get_log_file()
    timestamp = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3]
    f.write(f"[{timestamp}] {msg}\n")
    f.flush()


def truncate_id(player_root: bytes) -> str:
    """Truncate player root to first 8 hex chars."""
    return player_root[:4].hex() if len(player_root) >= 4 else player_root.hex()


# region projector_oo
@projector(name="prj-output", domains=["player", "table", "hand"])
class OutputProjector:
    """Output projector using OO-style decorators with multi-domain support."""

    @handles(player.PlayerRegistered)
    def project_player_registered(self, event: player.PlayerRegistered) -> None:
        write_log(f"PLAYER registered: {event.display_name} ({event.email})")

    @handles(player.FundsDeposited)
    def project_funds_deposited(self, event: player.FundsDeposited) -> None:
        amount = event.amount.amount if event.HasField("amount") else 0
        new_balance = event.new_balance.amount if event.HasField("new_balance") else 0
        write_log(f"PLAYER deposited {amount}, balance: {new_balance}")

    @handles(table.TableCreated)
    def project_table_created(self, event: table.TableCreated) -> None:
        write_log(f"TABLE created: {event.table_name} ({event.game_variant})")

    @handles(table.PlayerJoined)
    def project_player_joined(self, event: table.PlayerJoined) -> None:
        player_id = truncate_id(event.player_root)
        write_log(f"TABLE player {player_id} joined with {event.stack} chips")

    @handles(table.HandStarted)
    def project_hand_started(self, event: table.HandStarted) -> None:
        write_log(
            f"TABLE hand #{event.hand_number} started, "
            f"{len(event.active_players)} players, dealer at position {event.dealer_position}"
        )

    @handles(hand.CardsDealt)
    def project_cards_dealt(self, event: hand.CardsDealt) -> None:
        write_log(f"HAND cards dealt to {len(event.player_cards)} players")

    @handles(hand.BlindPosted)
    def project_blind_posted(self, event: hand.BlindPosted) -> None:
        player_id = truncate_id(event.player_root)
        write_log(
            f"HAND player {player_id} posted {event.blind_type} blind: {event.amount}"
        )

    @handles(hand.ActionTaken)
    def project_action_taken(self, event: hand.ActionTaken) -> None:
        player_id = truncate_id(event.player_root)
        write_log(f"HAND player {player_id}: {event.action} {event.amount}")

    @handles(hand.PotAwarded)
    def project_pot_awarded(self, event: hand.PotAwarded) -> None:
        winners = [
            f"{truncate_id(w.player_root)} wins {w.amount}" for w in event.winners
        ]
        write_log(f"HAND pot awarded: {', '.join(winners)}")

    @handles(hand.HandComplete)
    def project_hand_complete(self, event: hand.HandComplete) -> None:
        write_log(f"HAND #{event.hand_number} complete")


# endregion


def main():
    """Run the output projector server."""
    # Clear log file at startup
    path = os.environ.get("HAND_LOG_FILE", "hand_log_oo.txt")
    if os.path.exists(path):
        os.remove(path)

    print("Starting Output projector (OO pattern)")

    router = Router("prj-output").with_handler(OutputProjector()).build()
    servicer = ProjectorGrpc(router)
    run_server(
        projector_pb2_grpc.add_ProjectorServiceServicer_to_server,
        servicer,
        service_name="prj-output",
        domain="player",
        default_port="50391",
    )


if __name__ == "__main__":
    main()
