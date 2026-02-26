import logging

from api.logging_config import GZipRotatingFileHandler, configure_logging
from config import settings


def _set_settings(**kwargs):
    previous = {key: getattr(settings, key) for key in kwargs}
    for key, value in kwargs.items():
        setattr(settings, key, value)
    return previous


def _restore_settings(previous):
    for key, value in previous.items():
        setattr(settings, key, value)


def test_configure_logging_default_mode_uses_configured_levels() -> None:
    previous = _set_settings(
        LOGGING_SPIKE_MODE=False,
        LOG_LEVEL="ERROR",
        AGENTS_LOG_LEVEL="WARNING",
    )
    try:
        configure_logging()
        assert logging.getLogger().level == logging.ERROR
        assert logging.getLogger("agents").level == logging.WARNING
        assert all(not isinstance(h, GZipRotatingFileHandler) for h in logging.getLogger().handlers)
    finally:
        _restore_settings(previous)


def test_configure_logging_spike_mode_reduces_volume_and_enables_compression(tmp_path) -> None:
    log_file_path = tmp_path / "spike.log"
    previous = _set_settings(
        LOGGING_SPIKE_MODE=True,
        LOG_LEVEL="DEBUG",
        AGENTS_LOG_LEVEL="DEBUG",
        LOG_SPIKE_FILE_PATH=str(log_file_path),
        LOG_SPIKE_MAX_BYTES=1024,
        LOG_SPIKE_BACKUP_COUNT=2,
    )
    try:
        configure_logging()
        root_logger = logging.getLogger()
        assert root_logger.level == logging.WARNING
        assert logging.getLogger("agents").level == logging.INFO
        assert any(isinstance(h, GZipRotatingFileHandler) for h in root_logger.handlers)
    finally:
        _restore_settings(previous)
