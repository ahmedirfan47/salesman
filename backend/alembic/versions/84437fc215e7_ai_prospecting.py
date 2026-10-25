"""ai prospecting: prospects and their activity timeline

Revision ID: 84437fc215e7
Revises: c4a1f2e9b7d3
Create Date: 2026-10-25 21:30:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '84437fc215e7'
down_revision: Union[str, None] = 'c4a1f2e9b7d3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('prospects',
    sa.Column('tenant_id', sa.UUID(), nullable=False),
    sa.Column('kind', sa.String(length=16), nullable=False),
    sa.Column('source', sa.String(length=16), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('contact_name', sa.String(length=255), nullable=True),
    sa.Column('phone', sa.String(length=32), nullable=True),
    sa.Column('address', sa.String(length=500), nullable=True),
    sa.Column('area', sa.String(length=120), nullable=True),
    sa.Column('category', sa.String(length=64), nullable=True),
    sa.Column('zone_id', sa.UUID(), nullable=True),
    sa.Column('google_place_id', sa.String(length=255), nullable=True),
    sa.Column('google_maps_uri', sa.String(length=500), nullable=True),
    sa.Column('insight', sa.String(length=500), nullable=True),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('lost_reason', sa.String(length=255), nullable=True),
    sa.Column('assigned_to_id', sa.UUID(), nullable=True),
    sa.Column('created_by_id', sa.UUID(), nullable=True),
    sa.Column('customer_id', sa.UUID(), nullable=True),
    sa.Column('last_contacted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('closed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['assigned_to_id'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['created_by_id'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['customer_id'], ['customers.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['zone_id'], ['zones.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('tenant_id', 'google_place_id', name='uq_prospect_tenant_place')
    )
    op.create_index(op.f('ix_prospects_assigned_to_id'), 'prospects', ['assigned_to_id'], unique=False)
    op.create_index(op.f('ix_prospects_customer_id'), 'prospects', ['customer_id'], unique=False)
    op.create_index(op.f('ix_prospects_phone'), 'prospects', ['phone'], unique=False)
    op.create_index(op.f('ix_prospects_tenant_id'), 'prospects', ['tenant_id'], unique=False)
    op.create_index('ix_prospects_tenant_status', 'prospects', ['tenant_id', 'status'], unique=False)
    op.create_index(op.f('ix_prospects_zone_id'), 'prospects', ['zone_id'], unique=False)
    op.create_table('prospect_activities',
    sa.Column('tenant_id', sa.UUID(), nullable=False),
    sa.Column('prospect_id', sa.UUID(), nullable=False),
    sa.Column('kind', sa.String(length=16), nullable=False),
    sa.Column('body', sa.Text(), nullable=True),
    sa.Column('actor_id', sa.UUID(), nullable=True),
    sa.Column('actor_name', sa.String(length=255), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['actor_id'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['prospect_id'], ['prospects.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_prospect_activities_prospect_id'), 'prospect_activities', ['prospect_id'], unique=False)
    op.create_index(op.f('ix_prospect_activities_tenant_id'), 'prospect_activities', ['tenant_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_prospect_activities_tenant_id'), table_name='prospect_activities')
    op.drop_index(op.f('ix_prospect_activities_prospect_id'), table_name='prospect_activities')
    op.drop_table('prospect_activities')
    op.drop_index(op.f('ix_prospects_zone_id'), table_name='prospects')
    op.drop_index('ix_prospects_tenant_status', table_name='prospects')
    op.drop_index(op.f('ix_prospects_tenant_id'), table_name='prospects')
    op.drop_index(op.f('ix_prospects_phone'), table_name='prospects')
    op.drop_index(op.f('ix_prospects_customer_id'), table_name='prospects')
    op.drop_index(op.f('ix_prospects_assigned_to_id'), table_name='prospects')
    op.drop_table('prospects')