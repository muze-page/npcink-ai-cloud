from __future__ import annotations

from app.core.config import get_settings
from app.core.db import require_database_connection
from app.core.logging import configure_logging, get_logger
from app.domain.usage.rollup import UsageRollupService


def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    require_database_connection(settings.database_url)

    result = UsageRollupService(settings.database_url).generate_rollups()
    get_logger("magick_ai_cloud.usage_rollup").info("usage rollups generated: %s", result)


if __name__ == "__main__":
    main()
