"""Logging setup helpers for API service."""
from __future__ import annotations

import gzip
import logging
import logging.handlers
import os
import shutil
import sys
from pathlib import Path

from config import settings


class GZipRotatingFileHandler(logging.handlers.RotatingFileHandler):
    """Rotating file handler that compresses backups as .gz files."""

    def rotator(self, source: str, dest: str) -> None:  # type: ignore[override]
        with open(source, "rb") as source_stream, gzip.open(f"{dest}.gz", "wb") as dest_stream:
            shutil.copyfileobj(source_stream, dest_stream)
        os.remove(source)


def _sanitize_level(level_name: str, fallback: int) -> int:
    value = getattr(logging, level_name.upper(), None)
    return value if isinstance(value, int) else fallback


def configure_logging() -> None:
    """Configure process-wide logging based on environment settings."""
    log_format = "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
    root_logger = logging.getLogger()
    root_logger.handlers.clear()

    spike_mode = settings.LOGGING_SPIKE_MODE
    root_level = logging.WARNING if spike_mode else _sanitize_level(settings.LOG_LEVEL, logging.INFO)
    root_logger.setLevel(root_level)

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(logging.Formatter(log_format))
    root_logger.addHandler(stream_handler)

    if spike_mode:
        log_file = Path(settings.LOG_SPIKE_FILE_PATH)
        log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = GZipRotatingFileHandler(
            filename=log_file,
            maxBytes=settings.LOG_SPIKE_MAX_BYTES,
            backupCount=settings.LOG_SPIKE_BACKUP_COUNT,
            encoding="utf-8",
        )
        file_handler.setFormatter(logging.Formatter(log_format))
        root_logger.addHandler(file_handler)

    agents_level = logging.INFO if spike_mode else _sanitize_level(settings.AGENTS_LOG_LEVEL, logging.DEBUG)
    logging.getLogger("agents").setLevel(agents_level)

    logging.getLogger(__name__).info(
        "Logging configured: spike_mode=%s root_level=%s agents_level=%s",
        spike_mode,
        logging.getLevelName(root_level),
        logging.getLevelName(agents_level),
    )
