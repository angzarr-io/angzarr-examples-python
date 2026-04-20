"""Order Workflow Process Manager (OO Pattern, unified Router).

Demonstrates the unified Router's ``@process_manager`` / ``@handles`` /
``@rejected`` decorators coordinating an order workflow across order,
inventory, and payment domains.
"""

import sys
from dataclasses import dataclass
from pathlib import Path

import structlog

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "client" / "python"))

from angzarr_client import (
    Destinations,
    ProcessManagerGrpc,
    ProcessManagerResponse,
    Router,
    handles,
    process_manager,
    rejected,
    run_server,
)
from angzarr_client.proto.angzarr import process_manager_pb2_grpc
from angzarr_client.proto.angzarr import types_pb2 as types

structlog.configure(
    processors=[
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer(),
    ],
    wrapper_class=structlog.make_filtering_bound_logger(0),
    context_class=dict,
    logger_factory=structlog.PrintLoggerFactory(),
)

logger = structlog.get_logger()


# =============================================================================
# Stub proto messages (would come from generated proto in real implementation)
# =============================================================================


@dataclass
class OrderCreated:
    """Event from order domain."""

    order_id: str = ""
    customer_id: str = ""
    amount: int = 0


@dataclass
class InventoryReserved:
    """Event from inventory domain."""

    order_id: str = ""
    sku: str = ""


@dataclass
class PaymentReceived:
    """Event from payment domain."""

    order_id: str = ""
    amount: int = 0


@dataclass
class ReserveInventory:
    """Command to inventory domain."""

    order_id: str = ""
    sku: str = ""


@dataclass
class ProcessPayment:
    """Command to payment domain."""

    order_id: str = ""
    amount: int = 0


@dataclass
class WorkflowCompleted:
    """Process manager internal event."""

    order_id: str = ""


@dataclass
class WorkflowFailed:
    """Process manager internal event for failures."""

    order_id: str = ""
    reason: str = ""


# =============================================================================
# Process Manager State
# =============================================================================


@dataclass
class OrderWorkflowState:
    """State for order workflow process manager."""

    order_id: str = ""
    customer_id: str = ""
    amount: int = 0
    inventory_reserved: bool = False
    payment_received: bool = False
    failed: bool = False
    failure_reason: str = ""


# =============================================================================
# Process Manager Implementation
# =============================================================================


@process_manager(
    name="pmg-order-workflow",
    pm_domain="order-workflow",
    sources=["order", "inventory", "payment"],
    targets=["inventory", "payment"],
    state=OrderWorkflowState,
)
class OrderWorkflowPM:
    """Order workflow process manager using the unified Router pattern.

    Coordinates:
    1. OrderCreated (order) -> ReserveInventory (inventory)
    2. InventoryReserved (inventory) -> ProcessPayment (payment)
    3. PaymentReceived (payment) -> workflow complete

    Handles rejections:
    - ReserveInventory rejected -> WorkflowFailed event
    - ProcessPayment rejected -> WorkflowFailed event
    """

    @handles(OrderCreated)
    def on_order_created(
        self,
        event: OrderCreated,
        state: OrderWorkflowState,
        destinations: Destinations,
    ) -> ProcessManagerResponse:
        """React to OrderCreated by issuing ReserveInventory."""
        state.order_id = event.order_id
        state.customer_id = event.customer_id
        state.amount = event.amount
        # Stub dataclasses aren't proto messages, so we log the intent.
        logger.info("would_emit_reserve_inventory", order_id=event.order_id)
        return ProcessManagerResponse()

    @handles(InventoryReserved)
    def on_inventory_reserved(
        self,
        event: InventoryReserved,
        state: OrderWorkflowState,
        destinations: Destinations,
    ) -> ProcessManagerResponse:
        """React to InventoryReserved by issuing ProcessPayment."""
        state.inventory_reserved = True
        logger.info("would_emit_process_payment", order_id=event.order_id)
        return ProcessManagerResponse()

    @handles(PaymentReceived)
    def on_payment_received(
        self,
        event: PaymentReceived,
        state: OrderWorkflowState,
        destinations: Destinations,
    ) -> ProcessManagerResponse:
        """React to PaymentReceived by marking workflow complete."""
        state.payment_received = True
        logger.info("workflow_completed", order_id=event.order_id)
        return ProcessManagerResponse()

    @rejected("inventory", "ReserveInventory")
    def handle_inventory_rejection(
        self, notification: types.Notification, state: OrderWorkflowState
    ) -> None:
        """Handle when ReserveInventory is rejected."""
        state.failed = True
        state.failure_reason = "Inventory reservation failed"
        logger.info("inventory_rejected", order_id=state.order_id)

    @rejected("payment", "ProcessPayment")
    def handle_payment_rejection(
        self, notification: types.Notification, state: OrderWorkflowState
    ) -> None:
        """Handle when ProcessPayment is rejected."""
        state.failed = True
        state.failure_reason = "Payment processing failed"
        logger.info("payment_rejected", order_id=state.order_id)


if __name__ == "__main__":
    router = Router("pmg-order-workflow").with_handler(OrderWorkflowPM, lambda: OrderWorkflowPM()).build()
    servicer = ProcessManagerGrpc(router)
    run_server(
        process_manager_pb2_grpc.add_ProcessManagerServiceServicer_to_server,
        servicer,
        service_name="pmg-order-workflow",
        domain="order-workflow",
        default_port="50420",
        logger=logger,
    )
