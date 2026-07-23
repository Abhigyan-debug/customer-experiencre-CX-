"""add avatar column to users

Revision ID: a762062fe5ad
Revises: 45195e752ddb
Create Date: 2026-07-10 20:30:59.789789

Note: baseline schema (45195e752ddb) already creates feedbacks/users with the
correct NOT NULL constraints, column widths, and indexes for any database
built from these migrations, so the only real delta from baseline is the new
avatar column. (A pre-existing, hand-maintained SQLite database that predated
this migration history needed a one-time, out-of-band reconciliation for
drift accumulated before Alembic was adopted - not something later databases
built from this history will ever encounter.)
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a762062fe5ad'
down_revision = '45195e752ddb'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(sa.Column('avatar', sa.String(length=200), nullable=True))


def downgrade():
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_column('avatar')
