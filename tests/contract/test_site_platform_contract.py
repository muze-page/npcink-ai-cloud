from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.adapters.repositories.commercial_repository import CommercialRepository
from app.api.routes.service import SiteProvisionPayload
from app.core.models import PLATFORM_KIND_WORDPRESS, Base, Site
from app.domain.commercial.identity import _extract_site_url
from app.domain.commercial.service import CommercialService

ROOT = Path(__file__).resolve().parents[2]
MIGRATION_PATH = ROOT / "migrations/versions/20260714_0060_site_platform_contract.py"


def _load_migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "site_platform_contract_migration",
        MIGRATION_PATH,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_site_model_has_first_class_url_and_wordpress_platform_defaults() -> None:
    site_url = Site.__table__.c.site_url
    platform_kind = Site.__table__.c.platform_kind

    assert site_url.nullable is False
    assert site_url.type.length == 2048
    assert site_url.default is not None
    assert site_url.default.arg == ""
    assert platform_kind.nullable is False
    assert platform_kind.type.length == 32
    assert platform_kind.default is not None
    assert platform_kind.default.arg == PLATFORM_KIND_WORDPRESS
    assert platform_kind.index is True


def test_site_repository_and_serializer_keep_one_url_truth() -> None:
    engine = sa.create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        repository = CommercialRepository(session)
        site = repository.upsert_site(
            site_id="site_contract",
            account_id=None,
            name="Contract Site",
            status="active",
            site_url="https://example.test",
            platform_kind=PLATFORM_KIND_WORDPRESS,
            metadata_json={
                "site_url": "https://duplicate.example.test",
                "url": "https://fallback.example.test",
                "source": "contract_test",
            },
            provisioned_at=None,
        )

        assert site.site_url == "https://example.test"
        assert site.platform_kind == PLATFORM_KIND_WORDPRESS
        assert site.metadata_json == {"source": "contract_test"}
        assert _extract_site_url(site) == "https://example.test"

        payload = CommercialService._serialize_site(object.__new__(CommercialService), site)
        assert payload["site_url"] == "https://example.test"
        assert payload["platform_kind"] == PLATFORM_KIND_WORDPRESS
        assert payload["metadata"] == {"source": "contract_test"}

        preserved = repository.upsert_site(
            site_id="site_contract",
            account_id=None,
            name="Contract Site Updated",
            status="active",
            site_url=None,
            platform_kind=PLATFORM_KIND_WORDPRESS,
            metadata_json={"source": "contract_test_updated"},
            provisioned_at=None,
        )
        assert preserved.site_url == "https://example.test"

        cleared = repository.upsert_site(
            site_id="site_contract",
            account_id=None,
            name="Contract Site Cleared",
            status="active",
            site_url="",
            platform_kind=PLATFORM_KIND_WORDPRESS,
            metadata_json={"source": "contract_test_cleared"},
            provisioned_at=None,
        )
        assert cleared.site_url == ""

        with pytest.raises(ValueError, match="unsupported platform_kind"):
            repository.upsert_site(
                site_id="site_unsupported",
                account_id=None,
                name="Unsupported Site",
                status="active",
                site_url="https://unsupported.example.test",
                platform_kind="unsupported",
                metadata_json={},
                provisioned_at=None,
            )


def test_site_identity_does_not_fall_back_to_metadata() -> None:
    site = Site(
        site_id="site_no_fallback",
        name="No Fallback",
        site_url="",
        platform_kind=PLATFORM_KIND_WORDPRESS,
        metadata_json={"site_url": "https://metadata.example.test"},
    )

    assert _extract_site_url(site) == ""


def test_internal_site_payload_rejects_superseded_url_field() -> None:
    superseded_field = "wordpress" + "_url"

    with pytest.raises(ValidationError):
        SiteProvisionPayload.model_validate(
            {
                "site_id": "site_legacy",
                "account_id": "acct_legacy",
                superseded_field: "https://legacy.example.test",
            }
        )


def test_site_platform_migration_backfills_and_cleans_legacy_metadata_on_sqlite() -> None:
    legacy_url_key = "wordpress" + "_url"
    engine = sa.create_engine("sqlite+pysqlite:///:memory:")
    legacy_metadata = sa.MetaData()
    legacy_sites = sa.Table(
        "sites",
        legacy_metadata,
        sa.Column("site_id", sa.String(length=191), primary_key=True),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
    )
    legacy_metadata.create_all(engine)

    migration = _load_migration()
    with engine.begin() as connection:
        connection.execute(
            legacy_sites.insert(),
            [
                {
                    "site_id": "site_primary",
                    "metadata_json": {
                        legacy_url_key: "https://primary.example.test",
                        "source": "legacy",
                    },
                },
                {
                    "site_id": "site_fallback",
                    "metadata_json": {
                        "url": "https://fallback.example.test",
                        "source": "fallback",
                    },
                },
            ],
        )
        migration.op = Operations(MigrationContext.configure(connection))
        migration.upgrade()

        reflected = sa.Table("sites", sa.MetaData(), autoload_with=connection)
        rows = {
            str(row.site_id): row
            for row in connection.execute(sa.select(reflected)).mappings()
        }
        indexes = {index["name"] for index in sa.inspect(connection).get_indexes("sites")}
        migration.downgrade()
        downgraded = sa.Table("sites", sa.MetaData(), autoload_with=connection)
        downgraded_rows = {
            str(row.site_id): row
            for row in connection.execute(sa.select(downgraded)).mappings()
        }
        downgraded_columns = set(downgraded.c.keys())

    assert rows["site_primary"].site_url == "https://primary.example.test"
    assert rows["site_primary"].platform_kind == PLATFORM_KIND_WORDPRESS
    assert rows["site_primary"].metadata_json == {"source": "legacy"}
    assert rows["site_fallback"].site_url == "https://fallback.example.test"
    assert rows["site_fallback"].metadata_json == {"source": "fallback"}
    assert "ix_sites_platform_kind" in indexes
    assert "site_url" not in downgraded_columns
    assert "platform_kind" not in downgraded_columns
    assert (
        downgraded_rows["site_primary"].metadata_json[legacy_url_key]
        == "https://primary.example.test"
    )


def test_frontend_site_contract_reads_only_first_class_url() -> None:
    display_source = (ROOT / "frontend/src/lib/portal-site-display.ts").read_text(
        encoding="utf-8"
    )
    client_source = (ROOT / "frontend/src/lib/portal-client.ts").read_text(encoding="utf-8")
    session_source = (ROOT / "frontend/src/hooks/useSession.ts").read_text(encoding="utf-8")

    assert "return normalizeString(site.site_url);" in display_source
    assert "metadata?.site_url" not in display_source
    assert "metadata?.site_url" not in session_source
    assert "platform_kind: 'wordpress';" in client_source


def test_active_sources_have_no_superseded_site_url_token() -> None:
    superseded_token = "wordpress" + "_url"
    for relative_root in ("app", "tests", "frontend/src", "frontend/tests", "scripts"):
        root = ROOT / relative_root
        for path in root.rglob("*"):
            if not path.is_file() or path.suffix not in {".py", ".ts", ".tsx", ".mjs", ".sh"}:
                continue
            assert superseded_token not in path.read_text(encoding="utf-8"), path
