from __future__ import annotations

import time

from app.core.config import get_settings
from app.core.logging import configure_logging, get_logger
from app.core.tracing import configure_tracing


def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    configure_tracing(settings)

    logger = get_logger("npcink_ai_cloud.worker")
    logger.info("noop worker started")

    while True:
        time.sleep(60)


if __name__ == "__main__":
    main()
