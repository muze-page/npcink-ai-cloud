"""store site api signing secret ciphertext separately from verifier hash"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260428_0028"
down_revision = "20260421_0027"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("site_api_keys") as batch_op:
        batch_op.add_column(sa.Column("signing_secret_ciphertext", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("site_api_keys") as batch_op:
        batch_op.drop_column("signing_secret_ciphertext")
