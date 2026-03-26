"""Unit tests for Notification-based compensation flow."""

from google.protobuf.any_pb2 import Any as ProtoAny

from angzarr_client import CommandHandler, rejected
from angzarr_client.proto.angzarr import types_pb2 as types


# Test fixtures
class PlayerState:
    def __init__(self):
        self.reserved_amount = 0


class TestPlayerAggregate(CommandHandler[PlayerState]):
    domain = "player"

    def _create_empty_state(self) -> PlayerState:
        return PlayerState()

    def _apply_event(self, state, event_any):
        pass

    @rejected(domain="payment", command="ProcessPayment")
    def handle_payment_rejected(self, notification: types.Notification):
        self._rejection_handled = True
        self._rejection_context = notification
        return None


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
    # Build command page with source info in header
    header = types.PageHeader()
    if source_domain:
        header.angzarr_deferred.CopyFrom(types.AngzarrDeferredSequence(
            source=types.Cover(domain=source_domain, root=types.UUID(value=source_root)),
            source_seq=0,
        ))

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
        """Aggregate routes Notification to @rejected handler."""
        event_book = types.EventBook()
        agg = TestPlayerAggregate(event_book)

        notif = make_notification(
            rejection_reason="insufficient_funds",
            rejected_domain="payment",
            rejected_command="ProcessPayment",
            source_domain="saga-payment",
        )

        agg.handle_revocation(notif)

        assert hasattr(agg, "_rejection_handled")
        assert agg._rejection_handled is True
        assert agg._rejection_context == notif

    def test_aggregate_delegates_when_no_handler(self):
        """Aggregate delegates to framework when no @rejected handler matches."""

        class PlayerNoHandlers(CommandHandler[PlayerState]):
            domain = "player"

            def _create_empty_state(self):
                return PlayerState()

            def _apply_event(self, state, event):
                pass

        event_book = types.EventBook()
        agg = PlayerNoHandlers(event_book)

        notif = make_notification(
            rejection_reason="error",
            rejected_domain="unknown",
            rejected_command="UnknownCommand",
            source_domain="saga-unknown",
        )

        response = agg.handle_revocation(notif)

        assert response.HasField("revocation")
        assert response.revocation.emit_system_revocation is True
        assert "no custom compensation" in response.revocation.reason.lower()

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
