"""customer accounts: invoices, payments, credit notes, the customer ledger and credit terms

Existing customers get no limit and the business's default payment terms;
nothing is invoiced retroactively. Invoices start with the next confirmed or
delivered order.

Revision ID: 13934f8b8e78
Revises: 4189cd2a7dc2
Create Date: 2026-10-26 23:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '13934f8b8e78'
down_revision: Union[str, None] = '4189cd2a7dc2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('account_settings',
    sa.Column('tenant_id', sa.UUID(), nullable=False),
    sa.Column('currency', sa.String(length=3), nullable=False),
    sa.Column('vat_rate', sa.Numeric(precision=5, scale=2), nullable=False),
    sa.Column('prices_include_vat', sa.Boolean(), nullable=False),
    sa.Column('invoice_on', sa.String(length=16), nullable=False),
    sa.Column('default_payment_terms_days', sa.Integer(), nullable=False),
    sa.Column('default_credit_limit', sa.Numeric(precision=14, scale=2), nullable=True),
    sa.Column('hold_over_limit', sa.Boolean(), nullable=False),
    sa.Column('hold_when_overdue', sa.Boolean(), nullable=False),
    sa.Column('overdue_grace_days', sa.Integer(), nullable=False),
    sa.Column('seller_name', sa.String(length=255), nullable=True),
    sa.Column('seller_name_ar', sa.String(length=255), nullable=True),
    sa.Column('seller_vat_number', sa.String(length=20), nullable=True),
    sa.Column('seller_cr_number', sa.String(length=20), nullable=True),
    sa.Column('seller_address', sa.String(length=500), nullable=True),
    sa.Column('invoice_footer', sa.Text(), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('tenant_id')
    )
    op.create_table('document_counters',
    sa.Column('tenant_id', sa.UUID(), nullable=False),
    sa.Column('kind', sa.String(length=20), nullable=False),
    sa.Column('last_value', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('tenant_id', 'kind')
    )
    op.create_table('customer_payments',
    sa.Column('tenant_id', sa.UUID(), nullable=False),
    sa.Column('branch_id', sa.UUID(), nullable=False),
    sa.Column('customer_id', sa.UUID(), nullable=True),
    sa.Column('number', sa.String(length=32), nullable=False),
    sa.Column('amount', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('currency', sa.String(length=3), nullable=False),
    sa.Column('method', sa.String(length=20), nullable=False),
    sa.Column('reference', sa.String(length=120), nullable=True),
    sa.Column('paid_on', sa.Date(), nullable=False),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('unallocated', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('voided_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('void_reason', sa.String(length=255), nullable=True),
    sa.Column('created_by', sa.UUID(), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['branch_id'], ['branches.id'], ),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['customer_id'], ['customers.id'], ),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('tenant_id', 'number', name='uq_customer_payment_number')
    )
    op.create_index(op.f('ix_customer_payments_branch_id'), 'customer_payments', ['branch_id'], unique=False)
    op.create_index(op.f('ix_customer_payments_customer_id'), 'customer_payments', ['customer_id'], unique=False)
    op.create_index(op.f('ix_customer_payments_tenant_id'), 'customer_payments', ['tenant_id'], unique=False)
    op.create_table('sales_invoices',
    sa.Column('tenant_id', sa.UUID(), nullable=False),
    sa.Column('branch_id', sa.UUID(), nullable=False),
    sa.Column('customer_id', sa.UUID(), nullable=True),
    sa.Column('order_id', sa.UUID(), nullable=True),
    sa.Column('kind', sa.String(length=20), nullable=False),
    sa.Column('number', sa.String(length=32), nullable=False),
    sa.Column('original_invoice_id', sa.UUID(), nullable=True),
    sa.Column('issue_date', sa.Date(), nullable=False),
    sa.Column('issued_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('due_date', sa.Date(), nullable=False),
    sa.Column('currency', sa.String(length=3), nullable=False),
    sa.Column('lines', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('subtotal', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('vat_amount', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('total', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('amount_paid', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('amount_credited', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('seller', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('buyer', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('reason', sa.String(length=255), nullable=True),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('created_by', sa.UUID(), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['branch_id'], ['branches.id'], ),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['customer_id'], ['customers.id'], ),
    sa.ForeignKeyConstraint(['order_id'], ['orders.id'], ),
    sa.ForeignKeyConstraint(['original_invoice_id'], ['sales_invoices.id'], ),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('tenant_id', 'number', name='uq_sales_invoice_number')
    )
    op.create_index(op.f('ix_sales_invoices_branch_id'), 'sales_invoices', ['branch_id'], unique=False)
    op.create_index(op.f('ix_sales_invoices_customer_id'), 'sales_invoices', ['customer_id'], unique=False)
    op.create_index('ix_sales_invoices_open', 'sales_invoices', ['tenant_id', 'customer_id', 'status'], unique=False)
    op.create_index(op.f('ix_sales_invoices_order_id'), 'sales_invoices', ['order_id'], unique=False)
    op.create_index(op.f('ix_sales_invoices_tenant_id'), 'sales_invoices', ['tenant_id'], unique=False)
    op.create_index('uq_sales_invoice_order', 'sales_invoices', ['order_id'], unique=True, postgresql_where="kind = 'invoice' AND order_id IS NOT NULL")
    op.create_table('account_entries',
    sa.Column('tenant_id', sa.UUID(), nullable=False),
    sa.Column('branch_id', sa.UUID(), nullable=False),
    sa.Column('customer_id', sa.UUID(), nullable=False),
    sa.Column('entry_date', sa.Date(), nullable=False),
    sa.Column('kind', sa.String(length=20), nullable=False),
    sa.Column('document_number', sa.String(length=32), nullable=False),
    sa.Column('invoice_id', sa.UUID(), nullable=True),
    sa.Column('payment_id', sa.UUID(), nullable=True),
    sa.Column('description', sa.String(length=255), nullable=False),
    sa.Column('debit', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('credit', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['branch_id'], ['branches.id'], ),
    sa.ForeignKeyConstraint(['customer_id'], ['customers.id'], ),
    sa.ForeignKeyConstraint(['invoice_id'], ['sales_invoices.id'], ),
    sa.ForeignKeyConstraint(['payment_id'], ['customer_payments.id'], ),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_account_entries_customer_date', 'account_entries', ['tenant_id', 'customer_id', 'entry_date'], unique=False)
    op.create_index(op.f('ix_account_entries_tenant_id'), 'account_entries', ['tenant_id'], unique=False)
    op.create_table('payment_allocations',
    sa.Column('tenant_id', sa.UUID(), nullable=False),
    sa.Column('payment_id', sa.UUID(), nullable=False),
    sa.Column('invoice_id', sa.UUID(), nullable=False),
    sa.Column('amount', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['invoice_id'], ['sales_invoices.id'], ),
    sa.ForeignKeyConstraint(['payment_id'], ['customer_payments.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_payment_allocations_invoice_id'), 'payment_allocations', ['invoice_id'], unique=False)
    op.create_index(op.f('ix_payment_allocations_payment_id'), 'payment_allocations', ['payment_id'], unique=False)
    op.create_index(op.f('ix_payment_allocations_tenant_id'), 'payment_allocations', ['tenant_id'], unique=False)
    op.add_column('customers', sa.Column('vat_number', sa.String(length=20), nullable=True))
    op.add_column('customers', sa.Column('credit_limit', sa.Numeric(precision=14, scale=2), nullable=True))
    op.add_column('customers', sa.Column('payment_terms_days', sa.Integer(), nullable=True))
    op.add_column('customers', sa.Column('on_hold', sa.Boolean(), server_default='false', nullable=False))


def downgrade() -> None:
    op.drop_column('customers', 'on_hold')
    op.drop_column('customers', 'payment_terms_days')
    op.drop_column('customers', 'credit_limit')
    op.drop_column('customers', 'vat_number')
    op.drop_index(op.f('ix_payment_allocations_tenant_id'), table_name='payment_allocations')
    op.drop_index(op.f('ix_payment_allocations_payment_id'), table_name='payment_allocations')
    op.drop_index(op.f('ix_payment_allocations_invoice_id'), table_name='payment_allocations')
    op.drop_table('payment_allocations')
    op.drop_index(op.f('ix_account_entries_tenant_id'), table_name='account_entries')
    op.drop_index('ix_account_entries_customer_date', table_name='account_entries')
    op.drop_table('account_entries')
    op.drop_index('uq_sales_invoice_order', table_name='sales_invoices', postgresql_where="kind = 'invoice' AND order_id IS NOT NULL")
    op.drop_index(op.f('ix_sales_invoices_tenant_id'), table_name='sales_invoices')
    op.drop_index(op.f('ix_sales_invoices_order_id'), table_name='sales_invoices')
    op.drop_index('ix_sales_invoices_open', table_name='sales_invoices')
    op.drop_index(op.f('ix_sales_invoices_customer_id'), table_name='sales_invoices')
    op.drop_index(op.f('ix_sales_invoices_branch_id'), table_name='sales_invoices')
    op.drop_table('sales_invoices')
    op.drop_index(op.f('ix_customer_payments_tenant_id'), table_name='customer_payments')
    op.drop_index(op.f('ix_customer_payments_customer_id'), table_name='customer_payments')
    op.drop_index(op.f('ix_customer_payments_branch_id'), table_name='customer_payments')
    op.drop_table('customer_payments')
    op.drop_table('document_counters')
    op.drop_table('account_settings')
    # ### end Alembic commands ###