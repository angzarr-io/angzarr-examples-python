"""Unit tests for Notification-based compensation flow."""

from google.protobuf.any_pb2 import Any as ProtoAny

from angzarr_client import Router, command_handler, rejected
from angzarr_client.helpers import TYPE_URL_PREFIX
from angzarr_client.proto.angzarr import types_pb2 as types


# Test fixtures
class PlayerState:
    def __init__(self):
        self.reserved_amount = 0


@command_handler(domain="player", state=PlayerState)
class TestPlayerAggregate:
    @rejected("payment", "ProcessPayment")
    def handle_payment_rejected(
        self, notification: types.Notification, state: PlayerState
    ):
        return None


def _build_rejection_request(
    rejected_domain: str,
    rejected_command: str,
    rejection_reason: str,
    source_domain: str = "",
    source_root: bytes = b"",
    aggregate_domain: str = "player",
) -> types.ContextualCommand:
    """Build a ContextualCommand whose page command is a Notification."""
    cmd_any = ProtoAny(
        type_url=f"type.googleapis.com/test.{rejected_command}",
        value=b"",
    )
    header = types.PageHeader()
    if source_domain:
        header.angzarr_deferred.CopyFrom(
            types.AngzarrDeferredSequence(
                source=types.Cover(
                    domain=source_domain, root=types.UUID(value=source_root)
                ),
                source_seq=0,
            )
        )

    rejected_cmd = types.CommandBook(
        cover=types.Cover(domain=rejected_domain),
        pages=[types.CommandPage(header=header, command=cmd_any)],
    )
    rejection = types.RejectionNotification(
        rejection_reason=rejection_reason,
        rejected_command=rejected_cmd,
    )
    payload = ProtoAny()
    payload.type_url = TYPE_URL_PREFIX + rejection.DESCRIPTOR.full_name
    payload.value = rejection.SerializeToString()

    notification = types.Notification(payload=payload)
    notif_any = ProtoAny()
    notif_any.type_url = TYPE_URL_PREFIX + notification.DESCRIPTOR.full_name
    notif_any.value = notification.SerializeToString()

    cpage = types.CommandPage()
    cpage.header.CopyFrom(types.PageHeader(sequence=0))
    cpage.command.CopyFrom(notif_any)

    cbook = types.CommandBook(
        cover=types.Cover(domain=aggregate_domain),
        pages=[cpage],
    )
    return types.ContextualCommand(command=cbook)


def make_notification(
    rejection_reason: str,
    rejected_domain: str,
    rejected_command: str,
    source_domain: str = "",
    source_root: bytes = b"",
) -> types.Notification:
    """Create a Notification with RejectionNotification payload.

    Note: issuer_name and issuer_type were removed from RejectionNotification.
    Source info is now encoded in the command page header's angzarr_deferred field.
    """
    cmd_any = ProtoAny(
        type_url=f"type.googleapis.com/test.{rejected_command}",
        value=b"",
    )
    header = types.PageHeader()
    if source_domain:
        header.angzarr_deferred.CopyFrom(
            types.AngzarrDeferredSequence(
                source=types.Cover(
                    domain=source_domain, root=types.UUID(value=source_root)
                ),
                source_seq=0,
            )
        )

    rejected_cmd = types.CommandBook(
        cover=types.Cover(domain=rejected_domain),
        pages=[types.CommandPage(header=header, command=cmd_any)],
    )
    rejection = types.RejectionNotification(
        rejection_reason=rejection_reason,
        rejected_command=rejected_cmd,
    )
    payload = ProtoAny()
    payload.Pack(rejection, type_url_prefix="type.googleapis.com/")
    return types.Notification(payload=payload)


class TestNotificationCompensation:
    """Test Notification-based compensation flow."""

    def test_notification_created_with_rejection_payload(self):
        """Notification contains RejectionNotification payload."""
        notif = make_notification(
            rejection_reason="card_declined",
            rejected_domain="payment",
            rejected_command="ProcessPayment",
            source_domain="saga-payment",
        )

        assert notif.HasField("payload")
        assert "RejectionNotification" in notif.payload.type_url

        rejection = types.RejectionNotification()
        notif.payload.Unpack(rejection)
        assert rejection.rejection_reason == "card_declined"
        assert rejection.rejected_command.cover.domain == "payment"

    def test_aggregate_dispatches_to_rejected_handler(self):
        """Router dispatches a Notification to a @rejected handler."""
        captured = {}

        @command_handler(domain="player", state=PlayerState)
        class Player:
            @rejected("payment", "ProcessPayment")
            def handle_payment_rejected(
                self, notification: types.Notification, state: PlayerState
            ):
                captured["called"] = True
                captured["notification"] = notification
                return None

        router = Router("agg").with_handler(Player()).build()

        request = _build_rejection_request(
            rejected_domain="payment",
            rejected_command="ProcessPayment",
            rejection_reason="insufficient_funds",
            source_domain="saga-payment",
        )

        router.dispatch(request)

        assert captured.get("called") is True
        assert captured["notification"].HasField("payload")

    def test_aggregate_delegates_when_no_handler(self):
        """Router yields no compensation events when no @rejected handler matches."""

        @command_handler(domain="player", state=PlayerState)
        class PlayerNoHandlers:
            pass

        router = Router("agg").with_handler(PlayerNoHandlers()).build()

        request = _build_rejection_request(
            rejected_domain="unknown",
            rejected_command="UnknownCommand",
            rejection_reason="error",
            source_domain="saga-unknown",
        )

        response = router.dispatch(request)

        # No matching handler → empty events (framework fallback)
        assert response.HasField("events")
        assert len(response.events.pages) == 0

    def test_rejection_notification_fields(self):
        """RejectionNotification has all expected fields."""
        notif = make_notification(
            rejection_reason="out_of_stock",
            rejected_domain="inventory",
            rejected_command="ReserveInventory",
            source_domain="pmg-order-workflow",
        )

        rejection = types.RejectionNotification()
        notif.payload.Unpack(rejection)

        assert rejection.rejection_reason == "out_of_stock"
        assert rejection.rejected_command.cover.domain == "inventory"
        assert (
            "ReserveInventory" in rejection.rejected_command.pages[0].command.type_url
        )
        # Source info is now in the command page header's angzarr_deferred field
        header = rejection.rejected_command.pages[0].header
        assert header.HasField("angzarr_deferred")
        assert header.angzarr_deferred.source.domain == "pmg-order-workflow"
