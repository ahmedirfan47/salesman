import uuid
from decimal import Decimal

from sqlalchemy import Boolean, ForeignKey, Integer, Numeric, String, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models.mixins import TimestampMixin, UUIDPKMixin


class AgentSettings(UUIDPKMixin, TimestampMixin, Base):
    """How cautious the WhatsApp AI is with orders, per business.

    An order the AI is not sure about is held for the team (an 'ai_review'
    escalation) instead of being confirmed:
    - a line whose product match scores below `review_min_confidence` (0-1),
      i.e. the customer's words don't clearly name the product chosen;
    - a quantity more than `review_quantity_multiple` times the largest
      quantity this customer has ordered of that product before (catches
      "100" typed for "10"). 0 switches this check off.
    `learn_aliases`: remember the words a customer used for a product once
    they confirm an order, and when staff correct an order.
    `review_all_ai_orders`: hold every AI order for approval (useful in the
    first week of a pilot, "shadow mode").
    """

    __tablename__ = "agent_settings"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    review_min_confidence: Mapped[Decimal] = mapped_column(Numeric(3, 2), default=Decimal("0.60"), nullable=False)
    review_quantity_multiple: Mapped[int] = mapped_column(Integer, default=4, nullable=False)
    learn_aliases: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    review_all_ai_orders: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Reorder agent (app.modules.reorder): message a customer their usual
    # order when they are `reorder_factor` x later than their usual gap
    # between orders, once they have at least `reorder_min_orders` orders.
    reorder_enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"), nullable=False)
    reorder_factor: Mapped[Decimal] = mapped_column(Numeric(4, 2), default=Decimal("1.25"), server_default="1.25",
                                                    nullable=False)
    reorder_min_orders: Mapped[int] = mapped_column(Integer, default=3, server_default="3", nullable=False)
    reorder_template: Mapped[str | None] = mapped_column(String(120), nullable=True)

    # Data protection: delete WhatsApp message text older than this many days
    # (orders and invoices are kept). NULL keeps messages.
    message_retention_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
