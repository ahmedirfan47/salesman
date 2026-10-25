"""cost import, job queue, message id index

Revision ID: c4a1f2e9b7d3
Revises: 8e0db3804efc
Create Date: 2026-10-25 19:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = 'c4a1f2e9b7d3'
down_revision: Union[str, None] = '8e0db3804efc'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # cost imported from the price sheet, kept with each price version
    op.add_column('product_prices', sa.Column('unit_cost', sa.Numeric(precision=14, scale=2), nullable=True))

    # background job queue
    op.create_table(
        'jobs',
        sa.Column('tenant_id', sa.UUID(), nullable=True),
        sa.Column('kind', sa.String(length=64), nullable=False),
        sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('status', sa.String(length=16), nullable=False),
        sa.Column('attempts', sa.Integer(), nullable=False),
        sa.Column('max_attempts', sa.Integer(), nullable=False),
        sa.Column('run_after', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('locked_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_error', sa.Text(), nullable=True),
        sa.Column('dedupe_key', sa.String(length=200), nullable=True),
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('dedupe_key'),
    )
    op.create_index('ix_jobs_due', 'jobs', ['status', 'run_after'], unique=False)
    op.create_index(op.f('ix_jobs_tenant_id'), 'jobs', ['tenant_id'], unique=False)

    # fast "have we already handled this WhatsApp message?" lookups
    op.create_index(op.f('ix_messages_wa_message_id'), 'messages', ['wa_message_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_messages_wa_message_id'), table_name='messages')
    op.drop_index(op.f('ix_jobs_tenant_id'), table_name='jobs')
    op.drop_index('ix_jobs_due', table_name='jobs')
    op.drop_table('jobs')
    op.drop_column('product_prices', 'unit_cost')