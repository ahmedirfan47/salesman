"""erp integrations: one ERP connection per business, links to ERP records, and a sync log

Nothing changes until a business connects an ERP under Integrations.

Revision ID: 67f9d9a5cc81
Revises: 504489beef8a
Create Date: 2026-10-28 18:35:59.440349
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '67f9d9a5cc81'
down_revision: Union[str, None] = '504489beef8a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('integration_connections',
    sa.Column('tenant_id', sa.UUID(), nullable=False),
    sa.Column('provider', sa.String(length=20), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('base_url', sa.String(length=255), nullable=False),
    sa.Column('database', sa.String(length=120), nullable=True),
    sa.Column('username', sa.String(length=255), nullable=True),
    sa.Column('secret', sa.Text(), nullable=False),
    sa.Column('api', sa.String(length=16), nullable=True),
    sa.Column('server_version', sa.String(length=32), nullable=True),
    sa.Column('settings', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('connected_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_pull_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('next_pull_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_error', sa.Text(), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('tenant_id', name='uq_integration_connection_tenant')
    )
    op.create_index(op.f('ix_integration_connections_tenant_id'), 'integration_connections', ['tenant_id'], unique=False)
    op.create_table('integration_events',
    sa.Column('tenant_id', sa.UUID(), nullable=False),
    sa.Column('connection_id', sa.UUID(), nullable=False),
    sa.Column('direction', sa.String(length=8), nullable=False),
    sa.Column('action', sa.String(length=24), nullable=False),
    sa.Column('local_key', sa.String(length=80), nullable=False),
    sa.Column('label', sa.String(length=120), nullable=False),
    sa.Column('status', sa.String(length=12), nullable=False),
    sa.Column('message', sa.Text(), nullable=True),
    sa.Column('external_ref', sa.String(length=120), nullable=True),
    sa.Column('attempts', sa.Integer(), nullable=False),
    sa.Column('details', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['connection_id'], ['integration_connections.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('connection_id', 'action', 'local_key', name='uq_integration_event_item')
    )
    op.create_index('ix_integration_events_recent', 'integration_events', ['connection_id', 'updated_at'], unique=False)
    op.create_index(op.f('ix_integration_events_tenant_id'), 'integration_events', ['tenant_id'], unique=False)
    op.create_table('integration_links',
    sa.Column('tenant_id', sa.UUID(), nullable=False),
    sa.Column('connection_id', sa.UUID(), nullable=False),
    sa.Column('entity', sa.String(length=20), nullable=False),
    sa.Column('local_key', sa.String(length=80), nullable=False),
    sa.Column('external_id', sa.String(length=64), nullable=False),
    sa.Column('external_ref', sa.String(length=120), nullable=True),
    sa.Column('extra', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['connection_id'], ['integration_connections.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('connection_id', 'entity', 'local_key', name='uq_integration_link_local')
    )
    op.create_index('ix_integration_links_external', 'integration_links', ['connection_id', 'entity', 'external_id'], unique=False)
    op.create_index(op.f('ix_integration_links_tenant_id'), 'integration_links', ['tenant_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_integration_links_tenant_id'), table_name='integration_links')
    op.drop_index('ix_integration_links_external', table_name='integration_links')
    op.drop_table('integration_links')
    op.drop_index(op.f('ix_integration_events_tenant_id'), table_name='integration_events')
    op.drop_index('ix_integration_events_recent', table_name='integration_events')
    op.drop_table('integration_events')
    op.drop_index(op.f('ix_integration_connections_tenant_id'), table_name='integration_connections')
    op.drop_table('integration_connections')