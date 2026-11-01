"""platform admins: Stonic Console accounts, separate from business users

Revision ID: 126cf29e6d17
Revises: 82f0b6655b0a
Create Date: 2026-11-01 22:41:55.104849

The audit log's actor now points at platform_admins. Earlier entries were made
by business users acting as admins; they keep their actor_email, and their
actor_id is cleared.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '126cf29e6d17'
down_revision: Union[str, None] = '82f0b6655b0a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

FK = 'admin_audit_log_actor_id_fkey'


def upgrade() -> None:
    op.create_table('platform_admins',
    sa.Column('email', sa.String(length=255), nullable=False),
    sa.Column('password_hash', sa.String(length=255), nullable=False),
    sa.Column('full_name', sa.String(length=255), nullable=True),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('last_login_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_seen_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('token_version', sa.Integer(), server_default='0', nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_platform_admins_email'), 'platform_admins', ['email'], unique=True)
    op.drop_constraint(FK, 'admin_audit_log', type_='foreignkey')
    op.execute("UPDATE admin_audit_log SET actor_id = NULL")
    op.create_foreign_key(FK, 'admin_audit_log', 'platform_admins', ['actor_id'], ['id'], ondelete='SET NULL')


def downgrade() -> None:
    op.drop_constraint(FK, 'admin_audit_log', type_='foreignkey')
    op.execute("UPDATE admin_audit_log SET actor_id = NULL")
    op.create_foreign_key(FK, 'admin_audit_log', 'users', ['actor_id'], ['id'], ondelete='SET NULL')
    op.drop_index(op.f('ix_platform_admins_email'), table_name='platform_admins')
    op.drop_table('platform_admins')