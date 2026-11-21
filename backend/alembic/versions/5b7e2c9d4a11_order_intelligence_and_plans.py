"""order intelligence: product aliases, AI order review settings, payment reminders, plans

Revision ID: 5b7e2c9d4a11
Revises: 126cf29e6d17
Create Date: 2026-11-21 17:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '5b7e2c9d4a11'
down_revision: Union[str, None] = '126cf29e6d17'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # what customers call each product (needs Postgres 15+ for NULLS NOT DISTINCT)
    op.create_table(
        'product_aliases',
        sa.Column('tenant_id', sa.UUID(), nullable=False),
        sa.Column('product_id', sa.UUID(), nullable=False),
        sa.Column('customer_id', sa.UUID(), nullable=True),
        sa.Column('alias', sa.String(length=200), nullable=False),
        sa.Column('alias_norm', sa.String(length=200), nullable=False),
        sa.Column('source', sa.String(length=16), nullable=False),
        sa.Column('hits', sa.Integer(), nullable=False),
        sa.Column('last_used_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_by', sa.UUID(), nullable=True),
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['product_id'], ['products.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['customer_id'], ['customers.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['created_by'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('tenant_id', 'customer_id', 'alias_norm', name='uq_product_alias',
                            postgresql_nulls_not_distinct=True),
    )
    op.create_index(op.f('ix_product_aliases_tenant_id'), 'product_aliases', ['tenant_id'], unique=False)
    op.create_index(op.f('ix_product_aliases_product_id'), 'product_aliases', ['product_id'], unique=False)
    op.create_index(op.f('ix_product_aliases_customer_id'), 'product_aliases', ['customer_id'], unique=False)

    # how cautious the AI is with orders
    op.create_table(
        'agent_settings',
        sa.Column('tenant_id', sa.UUID(), nullable=False),
        sa.Column('review_min_confidence', sa.Numeric(precision=3, scale=2), nullable=False),
        sa.Column('review_quantity_multiple', sa.Integer(), nullable=False),
        sa.Column('learn_aliases', sa.Boolean(), nullable=False),
        sa.Column('review_all_ai_orders', sa.Boolean(), nullable=False),
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('tenant_id'),
    )

    # payment reminders
    op.add_column('account_settings', sa.Column('reminders_enabled', sa.Boolean(), server_default='false', nullable=False))
    op.add_column('account_settings', sa.Column('reminder_days_before_due', sa.Integer(), server_default='3', nullable=False))
    op.add_column('account_settings', sa.Column('reminder_repeat_days', sa.Integer(), server_default='7', nullable=False))
    op.add_column('account_settings', sa.Column('reminder_max_overdue', sa.Integer(), server_default='3', nullable=False))
    op.add_column('account_settings', sa.Column('reminder_template', sa.String(length=120), nullable=True))
    op.create_table(
        'collection_reminders',
        sa.Column('tenant_id', sa.UUID(), nullable=False),
        sa.Column('invoice_id', sa.UUID(), nullable=False),
        sa.Column('customer_id', sa.UUID(), nullable=True),
        sa.Column('stage', sa.String(length=16), nullable=False),
        sa.Column('status', sa.String(length=16), nullable=False),
        sa.Column('detail', sa.String(length=255), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('sent_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('id', sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['invoice_id'], ['sales_invoices.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['customer_id'], ['customers.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_collection_reminders_tenant_id'), 'collection_reminders', ['tenant_id'], unique=False)
    op.create_index(op.f('ix_collection_reminders_customer_id'), 'collection_reminders', ['customer_id'], unique=False)
    op.create_index('uq_collection_reminder_stage', 'collection_reminders', ['invoice_id', 'stage'], unique=True)

    # plans: existing subscriptions keep their hand-set prices ("custom")
    op.add_column('subscriptions', sa.Column('plan', sa.String(length=16), server_default='custom', nullable=False))
    op.add_column('subscriptions', sa.Column('included_orders_per_branch', sa.Integer(), nullable=True))
    op.add_column('subscriptions', sa.Column('overage_per_order', sa.Numeric(precision=12, scale=2), nullable=True))


def downgrade() -> None:
    op.drop_column('subscriptions', 'overage_per_order')
    op.drop_column('subscriptions', 'included_orders_per_branch')
    op.drop_column('subscriptions', 'plan')
    op.drop_index('uq_collection_reminder_stage', table_name='collection_reminders')
    op.drop_index(op.f('ix_collection_reminders_customer_id'), table_name='collection_reminders')
    op.drop_index(op.f('ix_collection_reminders_tenant_id'), table_name='collection_reminders')
    op.drop_table('collection_reminders')
    op.drop_column('account_settings', 'reminder_template')
    op.drop_column('account_settings', 'reminder_max_overdue')
    op.drop_column('account_settings', 'reminder_repeat_days')
    op.drop_column('account_settings', 'reminder_days_before_due')
    op.drop_column('account_settings', 'reminders_enabled')
    op.drop_table('agent_settings')
    op.drop_index(op.f('ix_product_aliases_customer_id'), table_name='product_aliases')
    op.drop_index(op.f('ix_product_aliases_product_id'), table_name='product_aliases')
    op.drop_index(op.f('ix_product_aliases_tenant_id'), table_name='product_aliases')
    op.drop_table('product_aliases')
