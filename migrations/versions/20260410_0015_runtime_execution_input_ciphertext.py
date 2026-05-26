from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260410_0015"
down_revision = "20260330_0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("run_records") as batch_op:
        batch_op.add_column(sa.Column("execution_input_ciphertext", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("run_records") as batch_op:
        batch_op.drop_column("execution_input_ciphertext")
