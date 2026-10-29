"""stonic console: site switches, usage tracking, sign-in log, audit log

Adds the tables behind the Stonic Console, plus last sign-in / last seen and a
session version on users and a suspension flag on businesses. Nothing changes
for anyone until a Stonic admin flips a switch.

Revision ID: 82f0b6655b0a
Revises: 67f9d9a5cc81
Create Date: 2026-10-29 22:07:33.669214
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '82f0b6655b0a'
down_revision: Union[str, None] = '67f9d9a5cc81'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('platform_settings',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('data', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('updated_by', sa.String(length=255), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('admin_audit_log',
    sa.Column('actor_id', sa.UUID(), nullable=True),
    sa.Column('actor_email', sa.String(length=255), nullable=False),
    sa.Column('action', sa.String(length=60), nullable=False),
    sa.Column('target_type', sa.String(length=30), nullable=True),
    sa.Column('target_id', sa.String(length=64), nullable=True),
    sa.Column('target_label', sa.String(length=255), nullable=True),
    sa.Column('detail', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['actor_id'], ['users.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_admin_audit_log_created_at', 'admin_audit_log', ['created_at'], unique=False)
    op.create_table('login_events',
    sa.Column('user_id', sa.UUID(), nullable=True),
    sa.Column('tenant_id', sa.UUID(), nullable=True),
    sa.Column('email', sa.String(length=255), nullable=False),
    sa.Column('client', sa.String(length=10), nullable=False),
    sa.Column('success', sa.Boolean(), nullable=False),
    sa.Column('reason', sa.String(length=30), nullable=False),
    sa.Column('ip', sa.String(length=64), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_login_events_created_at', 'login_events', ['created_at'], unique=False)
    op.create_index(op.f('ix_login_events_tenant_id'), 'login_events', ['tenant_id'], unique=False)
    op.create_index(op.f('ix_login_events_user_id'), 'login_events', ['user_id'], unique=False)
    op.create_table('user_activity',
    sa.Column('day', sa.Date(), nullable=False),
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('client', sa.String(length=10), nullable=False),
    sa.Column('tenant_id', sa.UUID(), nullable=False),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('day', 'user_id', 'client')
    )
    op.create_index('ix_user_activity_day', 'user_activity', ['day'], unique=False)
    op.create_index(op.f('ix_user_activity_tenant_id'), 'user_activity', ['tenant_id'], unique=False)
    op.add_column('tenants', sa.Column('suspended_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('tenants', sa.Column('suspended_reason', sa.String(length=255), nullable=True))
    op.add_column('users', sa.Column('last_login_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('users', sa.Column('last_seen_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('users', sa.Column('token_version', sa.Integer(), server_default='0', nullable=False))


def downgrade() -> None:
    op.drop_column('users', 'token_version')
    op.drop_column('users', 'last_seen_at')
    op.drop_column('users', 'last_login_at')
    op.drop_column('tenants', 'suspended_reason')
    op.drop_column('tenants', 'suspended_at')
    op.drop_index(op.f('ix_user_activity_tenant_id'), table_name='user_activity')
    op.drop_index('ix_user_activity_day', table_name='user_activity')
    op.drop_table('user_activity')
    op.drop_index(op.f('ix_login_events_user_id'), table_name='login_events')
    op.drop_index(op.f('ix_login_events_tenant_id'), table_name='login_events')
    op.drop_index('ix_login_events_created_at', table_name='login_events')
    op.drop_table('login_events')
    op.drop_index('ix_admin_audit_log_created_at', table_name='admin_audit_log')
    op.drop_table('admin_audit_log')
    op.drop_table('platform_settings')