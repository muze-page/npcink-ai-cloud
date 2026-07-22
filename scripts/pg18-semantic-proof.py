from __future__ import annotations

import json
import secrets
from datetime import UTC, datetime

from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool

from app.core.config import get_settings


def main() -> None:
    settings = get_settings()
    engine = create_engine(
        settings.database_url,
        future=True,
        hide_parameters=True,
        poolclass=NullPool,
        connect_args={"connect_timeout": settings.database_connect_timeout_seconds},
    )
    table = f"pg18_semantic_proof_{secrets.token_hex(8)}"
    partial_index = f"{table}_active_dedupe"
    try:
        with engine.begin() as connection:
            version_num = int(
                connection.execute(text("SHOW server_version_num")).scalar_one()
            )
            if version_num // 10000 != 18:
                raise RuntimeError("semantic proof requires PostgreSQL major version 18")
            connection.execute(
                text(
                    f"""
                    CREATE TABLE {table} (
                        id bigint PRIMARY KEY,
                        dedupe_key text NOT NULL,
                        payload jsonb NOT NULL,
                        run_at timestamptz NOT NULL,
                        active boolean NOT NULL,
                        fence_token bigint NOT NULL
                    )
                    """
                )
            )
            connection.execute(
                text(
                    f"CREATE UNIQUE INDEX {partial_index} "
                    f"ON {table} (dedupe_key) WHERE active"
                )
            )
            for row_id, key in ((1, "first"), (2, "second")):
                connection.execute(
                    text(
                        f"""
                        INSERT INTO {table}
                            (id, dedupe_key, payload, run_at, active, fence_token)
                        VALUES
                            (:id, :key, CAST(:payload AS jsonb),
                             CAST(:run_at AS timestamptz), true, 2)
                        ON CONFLICT (id) DO UPDATE
                        SET payload = EXCLUDED.payload,
                            run_at = EXCLUDED.run_at
                        """
                    ),
                    {
                        "id": row_id,
                        "key": key,
                        "payload": json.dumps({"kind": "queue", "row": row_id}),
                        "run_at": datetime.now(UTC).isoformat(),
                    },
                )
            semantic_row = connection.execute(
                text(
                    f"""
                    SELECT payload ->> 'kind', pg_typeof(payload)::text,
                           pg_typeof(run_at)::text
                    FROM {table} WHERE id = 1
                    """
                )
            ).one()
            if tuple(semantic_row) != ("queue", "jsonb", "timestamp with time zone"):
                raise RuntimeError("JSONB or timestamptz semantics did not match")
            index_definition = str(
                connection.execute(
                    text(
                        "SELECT pg_get_indexdef(indexrelid) "
                        "FROM pg_index WHERE indexrelid = CAST(:name AS regclass)"
                    ),
                    {"name": partial_index},
                ).scalar_one()
            )
            if "WHERE active" not in index_definition:
                raise RuntimeError("partial-index predicate was not preserved")

        first = engine.connect()
        second = engine.connect()
        first_tx = first.begin()
        second_tx = second.begin()
        try:
            locked_id = int(
                first.execute(
                    text(
                        f"SELECT id FROM {table} ORDER BY id "
                        "FOR UPDATE SKIP LOCKED LIMIT 1"
                    )
                ).scalar_one()
            )
            skipped_id = int(
                second.execute(
                    text(
                        f"SELECT id FROM {table} ORDER BY id "
                        "FOR UPDATE SKIP LOCKED LIMIT 1"
                    )
                ).scalar_one()
            )
            if (locked_id, skipped_id) != (1, 2):
                raise RuntimeError("two-connection SKIP LOCKED semantics did not match")
        finally:
            second_tx.rollback()
            first_tx.rollback()
            second.close()
            first.close()

        with engine.begin() as connection:
            stale = connection.execute(
                text(
                    f"UPDATE {table} SET payload = CAST(:payload AS jsonb) "
                    "WHERE id = 1 AND fence_token = 1"
                ),
                {"payload": json.dumps({"kind": "stale"})},
            )
            if stale.rowcount != 0:
                raise RuntimeError("stale fencing token unexpectedly mutated the row")
            current = connection.execute(
                text(
                    f"UPDATE {table} SET fence_token = 3 "
                    "WHERE id = 1 AND fence_token = 2"
                )
            )
            if current.rowcount != 1:
                raise RuntimeError("current fencing token did not mutate exactly one row")
    finally:
        try:
            with engine.begin() as connection:
                connection.execute(text(f"DROP TABLE IF EXISTS {table}"))
        finally:
            engine.dispose()

    print(
        "[ok] PostgreSQL 18 semantic proof passed: JSONB, timestamptz, partial index, "
        "ON CONFLICT, two-connection SKIP LOCKED, and stale fencing rejection."
    )


if __name__ == "__main__":
    main()
