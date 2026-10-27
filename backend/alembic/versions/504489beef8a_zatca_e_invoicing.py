"""zatca e-invoicing: one device (EGS unit) per branch, signed e-invoices, national addresses

Nothing changes for existing invoices: e-invoicing starts for a branch once
it is connected to ZATCA from Accounts > E-invoicing.

Revision ID: 504489beef8a
Revises: 13934f8b8e78
Create Date: 2026-10-27 22:19:03.790435
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '504489beef8a'
down_revision: Union[str, None] = '13934f8b8e78'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('zatca_units',
    sa.Column('tenant_id', sa.UUID(), nullable=False),
    sa.Column('branch_id', sa.UUID(), nullable=False),
    sa.Column('environment', sa.String(length=16), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('common_name', sa.String(length=64), nullable=False),
    sa.Column('egs_serial', sa.String(length=128), nullable=False),
    sa.Column('organization_unit', sa.String(length=64), nullable=False),
    sa.Column('invoice_types', sa.String(length=4), nullable=False),
    sa.Column('location', sa.String(length=255), nullable=False),
    sa.Column('industry', sa.String(length=120), nullable=False),
    sa.Column('private_key', sa.Text(), nullable=False),
    sa.Column('csr', sa.Text(), nullable=False),
    sa.Column('compliance_token', sa.Text(), nullable=True),
    sa.Column('compliance_secret', sa.Text(), nullable=True),
    sa.Column('compliance_request_id', sa.String(length=64), nullable=True),
    sa.Column('compliance_results', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('production_token', sa.Text(), nullable=True),
    sa.Column('production_secret', sa.Text(), nullable=True),
    sa.Column('certificate', sa.Text(), nullable=True),
    sa.Column('certificate_expires_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('icv', sa.Integer(), nullable=False),
    sa.Column('last_hash', sa.String(length=128), nullable=False),
    sa.Column('onboarded_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_error', sa.Text(), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['branch_id'], ['branches.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('branch_id')
    )
    op.create_index(op.f('ix_zatca_units_tenant_id'), 'zatca_units', ['tenant_id'], unique=False)
    op.create_table('zatca_documents',
    sa.Column('tenant_id', sa.UUID(), nullable=False),
    sa.Column('branch_id', sa.UUID(), nullable=False),
    sa.Column('unit_id', sa.UUID(), nullable=True),
    sa.Column('invoice_id', sa.UUID(), nullable=False),
    sa.Column('flow', sa.String(length=16), nullable=False),
    sa.Column('kind', sa.String(length=16), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('icv', sa.Integer(), nullable=True),
    sa.Column('document_uuid', sa.String(length=36), nullable=True),
    sa.Column('invoice_hash', sa.String(length=128), nullable=True),
    sa.Column('pih', sa.String(length=128), nullable=True),
    sa.Column('xml', sa.Text(), nullable=True),
    sa.Column('qr', sa.Text(), nullable=True),
    sa.Column('cleared_xml', sa.Text(), nullable=True),
    sa.Column('signed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('submitted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('attempts', sa.Integer(), nullable=False),
    sa.Column('zatca_status', sa.String(length=32), nullable=True),
    sa.Column('errors', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('warnings', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('last_error', sa.Text(), nullable=True),
    sa.Column('replaced_by_id', sa.UUID(), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['branch_id'], ['branches.id'], ),
    sa.ForeignKeyConstraint(['invoice_id'], ['sales_invoices.id'], ),
    sa.ForeignKeyConstraint(['replaced_by_id'], ['zatca_documents.id'], ),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['unit_id'], ['zatca_units.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_zatca_documents_branch_id'), 'zatca_documents', ['branch_id'], unique=False)
    op.create_index(op.f('ix_zatca_documents_invoice_id'), 'zatca_documents', ['invoice_id'], unique=False)
    op.create_index(op.f('ix_zatca_documents_tenant_id'), 'zatca_documents', ['tenant_id'], unique=False)
    op.create_index('ix_zatca_documents_tenant_status', 'zatca_documents', ['tenant_id', 'status'], unique=False)
    op.add_column('account_settings', sa.Column('seller_street', sa.String(length=255), nullable=True))
    op.add_column('account_settings', sa.Column('seller_building_number', sa.String(length=8), nullable=True))
    op.add_column('account_settings', sa.Column('seller_district', sa.String(length=127), nullable=True))
    op.add_column('account_settings', sa.Column('seller_city', sa.String(length=127), nullable=True))
    op.add_column('account_settings', sa.Column('seller_postal_code', sa.String(length=10), nullable=True))
    op.add_column('customers', sa.Column('cr_number', sa.String(length=20), nullable=True))
    op.add_column('customers', sa.Column('street', sa.String(length=255), nullable=True))
    op.add_column('customers', sa.Column('building_number', sa.String(length=8), nullable=True))
    op.add_column('customers', sa.Column('district', sa.String(length=127), nullable=True))
    op.add_column('customers', sa.Column('city', sa.String(length=127), nullable=True))
    op.add_column('customers', sa.Column('postal_code', sa.String(length=10), nullable=True))


def downgrade() -> None:
    op.drop_column('customers', 'postal_code')
    op.drop_column('customers', 'city')
    op.drop_column('customers', 'district')
    op.drop_column('customers', 'building_number')
    op.drop_column('customers', 'street')
    op.drop_column('customers', 'cr_number')
    op.drop_column('account_settings', 'seller_postal_code')
    op.drop_column('account_settings', 'seller_city')
    op.drop_column('account_settings', 'seller_district')
    op.drop_column('account_settings', 'seller_building_number')
    op.drop_column('account_settings', 'seller_street')
    op.drop_index('ix_zatca_documents_tenant_status', table_name='zatca_documents')
    op.drop_index(op.f('ix_zatca_documents_tenant_id'), table_name='zatca_documents')
    op.drop_index(op.f('ix_zatca_documents_invoice_id'), table_name='zatca_documents')
    op.drop_index(op.f('ix_zatca_documents_branch_id'), table_name='zatca_documents')
    op.drop_table('zatca_documents')
    op.drop_index(op.f('ix_zatca_units_tenant_id'), table_name='zatca_units')
    op.drop_table('zatca_units')