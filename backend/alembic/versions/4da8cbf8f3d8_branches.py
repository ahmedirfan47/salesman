"""branches: per-branch stock, prices, zones, customers, orders and WhatsApp numbers

Every existing tenant gets one default branch called "Main branch". All of its
existing data moves to that branch, and its WhatsApp number (previously on the
tenant) moves to the branch, so a live WhatsApp number keeps working.

Owners, admins and demo users keep seeing every branch (branch_id NULL); other
staff are placed in the default branch.

Revision ID: 4da8cbf8f3d8
Revises: 84437fc215e7
Create Date: 2026-10-26 01:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '4da8cbf8f3d8'
down_revision: Union[str, None] = '84437fc215e7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# tables whose rows always belong to one branch
REQUIRED = [
    'zones', 'customers', 'orders', 'inventory', 'inventory_transactions', 'price_lists',
    'product_prices', 'conversations', 'escalations', 'print_jobs',
]
# tables where "no branch" is meaningful
OPTIONAL = ['users', 'prospects']

_DEFAULT_BRANCH = (
    "(SELECT b.id FROM branches b WHERE b.tenant_id = {table}.tenant_id AND b.is_default LIMIT 1)"
)


def upgrade() -> None:
    op.create_table(
        'branches',
        sa.Column('tenant_id', sa.UUID(), nullable=False),
        sa.Column('name', sa.String(length=120), nullable=False),
        sa.Column('city', sa.String(length=120), nullable=True),
        sa.Column('address', sa.String(length=500), nullable=True),
        sa.Column('is_default', sa.Boolean(), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('whatsapp_phone_number_id', sa.String(length=64), nullable=True),
        sa.Column('whatsapp_access_token', sa.String(length=512), nullable=True),
        sa.Column('whatsapp_display_number', sa.String(length=32), nullable=True),
        sa.Column('whatsapp_update_template', sa.String(length=120), nullable=True),
        sa.Column('order_updates_enabled', sa.Boolean(), nullable=False),
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('tenant_id', 'name', name='uq_branch_tenant_name'),
    )
    op.create_index(op.f('ix_branches_tenant_id'), 'branches', ['tenant_id'], unique=False)
    op.create_index(op.f('ix_branches_whatsapp_phone_number_id'), 'branches', ['whatsapp_phone_number_id'], unique=True)

    # one default branch per tenant, taking over the tenant's WhatsApp number
    op.execute("""
        INSERT INTO branches (id, tenant_id, name, is_default, is_active, order_updates_enabled,
                              whatsapp_phone_number_id, whatsapp_access_token, created_at)
        SELECT gen_random_uuid(), t.id, 'Main branch', true, true, true,
               t.whatsapp_phone_number_id, t.whatsapp_access_token, now()
        FROM tenants t
    """)

    for table in REQUIRED + OPTIONAL:
        op.add_column(table, sa.Column('branch_id', sa.UUID(), nullable=True))

    for table in REQUIRED + ['prospects']:
        op.execute(f"UPDATE {table} SET branch_id = {_DEFAULT_BRANCH.format(table=table)}")
    op.execute(
        f"UPDATE users SET branch_id = {_DEFAULT_BRANCH.format(table='users')} "
        "WHERE role NOT IN ('owner', 'admin', 'demo')"
    )

    for table in REQUIRED:
        op.alter_column(table, 'branch_id', nullable=False)
        op.create_index(op.f(f'ix_{table}_branch_id'), table, ['branch_id'], unique=False)
        op.create_foreign_key(f'fk_{table}_branch_id', table, 'branches', ['branch_id'], ['id'])
    for table in OPTIONAL:
        op.create_index(op.f(f'ix_{table}_branch_id'), table, ['branch_id'], unique=False)
        op.create_foreign_key(f'fk_{table}_branch_id', table, 'branches', ['branch_id'], ['id'], ondelete='SET NULL')

    # stock is now held per branch
    op.drop_constraint('uq_inventory_tenant_product', 'inventory', type_='unique')
    op.create_unique_constraint('uq_inventory_branch_product', 'inventory', ['tenant_id', 'branch_id', 'product_id'])

    # WhatsApp numbers now live on branches
    op.drop_index(op.f('ix_tenants_whatsapp_phone_number_id'), table_name='tenants')
    op.drop_column('tenants', 'whatsapp_phone_number_id')
    op.drop_column('tenants', 'whatsapp_access_token')


def downgrade() -> None:
    # Only safe while each tenant has a single branch: stock rows from several
    # branches can't be folded back into one row per product.
    op.add_column('tenants', sa.Column('whatsapp_access_token', sa.VARCHAR(length=512), nullable=True))
    op.add_column('tenants', sa.Column('whatsapp_phone_number_id', sa.VARCHAR(length=64), nullable=True))
    op.execute("""
        UPDATE tenants t SET whatsapp_phone_number_id = b.whatsapp_phone_number_id,
                             whatsapp_access_token = b.whatsapp_access_token
        FROM branches b WHERE b.tenant_id = t.id AND b.is_default
    """)
    op.create_index(op.f('ix_tenants_whatsapp_phone_number_id'), 'tenants', ['whatsapp_phone_number_id'], unique=True)

    op.drop_constraint('uq_inventory_branch_product', 'inventory', type_='unique')
    op.create_unique_constraint('uq_inventory_tenant_product', 'inventory', ['tenant_id', 'product_id'])

    for table in REQUIRED + OPTIONAL:
        op.drop_constraint(f'fk_{table}_branch_id', table, type_='foreignkey')
        op.drop_index(op.f(f'ix_{table}_branch_id'), table_name=table)
        op.drop_column(table, 'branch_id')

    op.drop_index(op.f('ix_branches_whatsapp_phone_number_id'), table_name='branches')
    op.drop_index(op.f('ix_branches_tenant_id'), table_name='branches')
    op.drop_table('branches')