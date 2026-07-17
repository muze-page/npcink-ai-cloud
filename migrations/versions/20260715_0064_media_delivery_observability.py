"""converge media observability on delivery lifecycle evidence"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260715_0064"
down_revision = "20260715_0063"
branch_labels = None
depends_on = None

_TABLE = "media_derivative_job_metrics"
_COUNT_COLUMN = "artifact_download_count"
_LAST_AT_COLUMN = "artifact_last_downloaded_at"


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table(_TABLE):
        return
    columns = {column["name"] for column in inspector.get_columns(_TABLE)}
    with op.batch_alter_table(_TABLE) as batch:
        if _COUNT_COLUMN in columns:
            batch.drop_column(_COUNT_COLUMN)
        if _LAST_AT_COLUMN in columns:
            batch.drop_column(_LAST_AT_COLUMN)


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table(_TABLE):
        return
    columns = {column["name"] for column in inspector.get_columns(_TABLE)}
    with op.batch_alter_table(_TABLE) as batch:
        if _COUNT_COLUMN not in columns:
            batch.add_column(
                sa.Column(
                    _COUNT_COLUMN,
                    sa.Integer(),
                    nullable=False,
                    server_default="0",
                )
            )
        if _LAST_AT_COLUMN not in columns:
            batch.add_column(sa.Column(_LAST_AT_COLUMN, sa.DateTime(timezone=True), nullable=True))
