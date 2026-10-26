"""billing: subscriptions, invoices and the invoice number sequence

No existing business gets a subscription automatically: until Stonic sets one
up in the admin console, nothing is invoiced and nothing is restricted.

Revision ID: 4189cd2a7dc2
Revises: 4da8cbf8f3d8
Create Date: 2026-10-26 12:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = '4189cd2a7dc2'
down_revision: Union[str, None] = '4da8cbf8f3d8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE SEQUENCE IF NOT EXISTS invoice_number_seq")

    op.create_table(
        'subscriptions',
        sa.Column('tenant_id', sa.UUID(), nullable=False),
        sa.Column('status', sa.String(length=16), nullable=False),
        sa.Column('currency', sa.String(length=3), nullable=False),
        sa.Column('setup_fee_per_branch', sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column('monthly_fee_per_branch', sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column('tax_percent', sa.Numeric(precision=5, scale=2), nullable=False),
        sa.Column('payment_terms_days', sa.Integer(), nullable=False),
        sa.Column('grace_days', sa.Integer(), nullable=False),
        sa.Column('next_invoice_on', sa.Date(), nullable=False),
        sa.Column('setup_billed_branches', sa.Integer(), nullable=False),
        sa.Column('billing_name', sa.String(length=255), nullable=True),
        sa.Column('billing_address', sa.String(length=500), nullable=True),
        sa.Column('billing_tax_id', sa.String(length=64), nullable=True),
        sa.Column('billing_email', sa.String(length=255), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('cancelled_on', sa.Date(), nullable=True),
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('tenant_id'),
    )

    op.create_table(
        'invoices',
        sa.Column('tenant_id', sa.UUID(), nullable=False),
        sa.Column('subscription_id', sa.UUID(), nullable=True),
        sa.Column('number', sa.String(length=32), nullable=False),
        sa.Column('kind', sa.String(length=16), nullable=False),
        sa.Column('status', sa.String(length=16), nullable=False),
        sa.Column('currency', sa.String(length=3), nullable=False),
        sa.Column('lines', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('subtotal', sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column('tax_percent', sa.Numeric(precision=5, scale=2), nullable=False),
        sa.Column('tax_amount', sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column('total', sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column('bill_to', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('issued_on', sa.Date(), nullable=False),
        sa.Column('due_on', sa.Date(), nullable=False),
        sa.Column('period_start', sa.Date(), nullable=True),
        sa.Column('period_end', sa.Date(), nullable=True),
        sa.Column('paid_on', sa.Date(), nullable=True),
        sa.Column('payment_reference', sa.String(length=120), nullable=True),
        sa.Column('voided_on', sa.Date(), nullable=True),
        sa.Column('void_reason', sa.String(length=255), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['subscription_id'], ['subscriptions.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('number'),
    )
    op.create_index('ix_invoices_tenant_status', 'invoices', ['tenant_id', 'status'], unique=False)
    op.create_index(
        'uq_invoice_subscription_period', 'invoices', ['subscription_id', 'period_start'], unique=True,
        postgresql_where=sa.text("kind = 'subscription' AND status <> 'void'"),
    )


def downgrade() -> None:
    op.drop_index('uq_invoice_subscription_period', table_name='invoices',
                  postgresql_where=sa.text("kind = 'subscription' AND status <> 'void'"))
    op.drop_index('ix_invoices_tenant_status', table_name='invoices')
    op.drop_table('invoices')
    op.drop_table('subscriptions')
    op.execute("DROP SEQUENCE IF EXISTS invoice_number_seq")