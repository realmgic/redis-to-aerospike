"""Shared log banners for marking the migration write phase in console output."""

from __future__ import annotations

import logging

LOG_RULE = "-" * 72
BANNER_TITLE = "redis-to-aerospike: migration"


def log_migration_banner(logger: logging.Logger) -> None:
    """Log the same three-line delimiter before and after the write phase."""
    logger.info("%s", LOG_RULE)
    logger.info("%s", BANNER_TITLE)
    logger.info("%s", LOG_RULE)
