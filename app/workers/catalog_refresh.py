from __future__ import annotations

from app.adapters.providers.registry import resolve_live_provider_adapters
from app.core.config import get_settings
from app.core.db import require_database_connection
from app.core.logging import configure_logging, get_logger
from app.domain.catalog.service import CatalogService


def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    require_database_connection(settings.database_url)

    result = CatalogService(
        settings.database_url,
        providers=resolve_live_provider_adapters(
            settings,
            include_enabled_connections=True,
        ),
    ).refresh_catalog()
    get_logger("npcink_ai_cloud.catalog_refresh").info("catalog refreshed: %s", result)


if __name__ == "__main__":
    main()
