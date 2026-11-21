"""customer prices, promotions and free goods; order source; reorder agent; print agents; data-protection log

Revision ID: 8d3f6a1c2b90
Revises: 5b7e2c9d4a11
Create Date: 2026-11-21
"""
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "8d3f6a1c2b90"
down_revision = "5b7e2c9d4a11"
branch_labels = None
depends_on = None

UUID = postgresql.UUID(as_uuid=True)
JSONB = postgresql.JSONB(astext_type=sa.Text())


def _stamps():
    return [sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False)]


def upgrade() -> None:
    op.create_table(
        "customer_prices",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("tenant_id", UUID, sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("customer_id", UUID, sa.ForeignKey("customers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("product_id", UUID, sa.ForeignKey("products.id", ondelete="CASCADE"), nullable=False),
        sa.Column("branch_id", UUID, sa.ForeignKey("branches.id", ondelete="CASCADE"), nullable=True),
        sa.Column("unit_price", sa.Numeric(14, 2), nullable=False),
        sa.Column("min_quantity", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("valid_from", sa.Date(), nullable=True),
        sa.Column("valid_to", sa.Date(), nullable=True),
        sa.Column("note", sa.String(255), nullable=True),
        *_stamps(),
        sa.UniqueConstraint("tenant_id", "customer_id", "product_id", "branch_id", "min_quantity",
                            name="uq_customer_price", postgresql_nulls_not_distinct=True),
    )
    op.create_index("ix_customer_prices_tenant_id", "customer_prices", ["tenant_id"])
    op.create_index("ix_customer_prices_customer_id", "customer_prices", ["customer_id"])

    op.create_table(
        "promotions",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("tenant_id", UUID, sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("product_id", UUID, sa.ForeignKey("products.id", ondelete="CASCADE"), nullable=False),
        sa.Column("branch_id", UUID, sa.ForeignKey("branches.id", ondelete="CASCADE"), nullable=True),
        sa.Column("customer_id", UUID, sa.ForeignKey("customers.id", ondelete="CASCADE"), nullable=True),
        sa.Column("min_quantity", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("percent_off", sa.Numeric(5, 2), nullable=True),
        sa.Column("fixed_price", sa.Numeric(14, 2), nullable=True),
        sa.Column("buy_quantity", sa.Integer(), nullable=True),
        sa.Column("free_quantity", sa.Integer(), nullable=True),
        sa.Column("free_product_id", UUID, sa.ForeignKey("products.id", ondelete="CASCADE"), nullable=True),
        sa.Column("starts_on", sa.Date(), nullable=True),
        sa.Column("ends_on", sa.Date(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        *_stamps(),
    )
    op.create_index("ix_promotions_tenant_id", "promotions", ["tenant_id"])
    op.create_index("ix_promotions_product_id", "promotions", ["product_id"])

    op.add_column("orders", sa.Column("source", sa.String(16), nullable=False, server_default="manual"))
    op.add_column("order_items", sa.Column("list_price", sa.Numeric(14, 2), nullable=True))
    op.add_column("order_items", sa.Column("price_source", sa.String(16), nullable=True))
    op.add_column("order_items", sa.Column("promotion_id", UUID, sa.ForeignKey("promotions.id", ondelete="SET NULL"),
                                           nullable=True))
    op.add_column("order_items", sa.Column("is_free", sa.Boolean(), nullable=False, server_default=sa.text("false")))

    op.add_column("agent_settings", sa.Column("reorder_enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    op.add_column("agent_settings", sa.Column("reorder_factor", sa.Numeric(4, 2), nullable=False, server_default="1.25"))
    op.add_column("agent_settings", sa.Column("reorder_min_orders", sa.Integer(), nullable=False, server_default="3"))
    op.add_column("agent_settings", sa.Column("reorder_template", sa.String(120), nullable=True))
    op.add_column("agent_settings", sa.Column("message_retention_days", sa.Integer(), nullable=True))

    op.create_table(
        "reorder_nudges",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("tenant_id", UUID, sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("customer_id", UUID, sa.ForeignKey("customers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("last_order_id", UUID, sa.ForeignKey("orders.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="queued"),
        sa.Column("due_on", sa.Date(), nullable=False),
        sa.Column("typical_days", sa.Integer(), nullable=False),
        sa.Column("suggested", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("error", sa.String(500), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("converted_order_id", UUID, sa.ForeignKey("orders.id", ondelete="SET NULL"), nullable=True),
        sa.Column("converted_at", sa.DateTime(timezone=True), nullable=True),
        *_stamps(),
        sa.UniqueConstraint("tenant_id", "customer_id", "last_order_id", name="uq_reorder_nudge"),
    )
    op.create_index("ix_reorder_nudges_tenant_id", "reorder_nudges", ["tenant_id"])
    op.create_index("ix_reorder_nudges_customer_id", "reorder_nudges", ["customer_id"])

    op.create_table(
        "print_agents",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("tenant_id", UUID, sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("branch_id", UUID, sa.ForeignKey("branches.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("key_prefix", sa.String(16), nullable=False),
        sa.Column("key_hash", sa.String(128), nullable=False),
        sa.Column("printer", sa.String(120), nullable=True),
        sa.Column("version", sa.String(32), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", UUID, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        *_stamps(),
    )
    op.create_index("ix_print_agents_tenant_id", "print_agents", ["tenant_id"])
    op.create_index("ix_print_agents_branch_id", "print_agents", ["branch_id"])
    op.create_index("ix_print_agents_key_prefix", "print_agents", ["key_prefix"])
    op.add_column("print_jobs", sa.Column("agent_id", UUID, sa.ForeignKey("print_agents.id", ondelete="SET NULL"),
                                          nullable=True))
    op.add_column("print_jobs", sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("print_jobs", sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"))

    op.create_table(
        "data_requests",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("tenant_id", UUID, sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.String(24), nullable=False),
        sa.Column("subject_id", UUID, nullable=True),
        sa.Column("requested_by", UUID, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("detail", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        *_stamps(),
    )
    op.create_index("ix_data_requests_tenant_id", "data_requests", ["tenant_id"])


def downgrade() -> None:
    op.drop_table("data_requests")
    op.drop_column("print_jobs", "attempts")
    op.drop_column("print_jobs", "claimed_at")
    op.drop_column("print_jobs", "agent_id")
    op.drop_table("print_agents")
    op.drop_table("reorder_nudges")
    for col in ("message_retention_days", "reorder_template", "reorder_min_orders", "reorder_factor", "reorder_enabled"):
        op.drop_column("agent_settings", col)
    for col in ("is_free", "promotion_id", "price_source", "list_price"):
        op.drop_column("order_items", col)
    op.drop_column("orders", "source")
    op.drop_table("promotions")
    op.drop_table("customer_prices")
