"""add email and reset token columns to users

Revision ID: dbfcf041e4a2
Revises: a762062fe5ad
Create Date: 2026-07-23 00:00:00.000000

Adds what the forgot-password flow needs: an email address to send the
reset link to, and a token + expiry to validate that link. All nullable -
existing accounts had no email on file and simply can't use password reset
until they set one in Settings.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'dbfcf041e4a2'
down_revision = 'a762062fe5ad'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(sa.Column('email', sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column('reset_token', sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column('reset_token_expires', sa.DateTime(timezone=True), nullable=True))
        batch_op.create_unique_constraint(batch_op.f('uq_users_email'), ['email'])
        batch_op.create_unique_constraint(batch_op.f('uq_users_reset_token'), ['reset_token'])
        batch_op.create_index(batch_op.f('ix_users_email'), ['email'], unique=False)
        batch_op.create_index(batch_op.f('ix_users_reset_token'), ['reset_token'], unique=False)


def downgrade():
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_users_reset_token'))
        batch_op.drop_index(batch_op.f('ix_users_email'))
        batch_op.drop_constraint(batch_op.f('uq_users_reset_token'), type_='unique')
        batch_op.drop_constraint(batch_op.f('uq_users_email'), type_='unique')
        batch_op.drop_column('reset_token_expires')
        batch_op.drop_column('reset_token')
        batch_op.drop_column('email')
