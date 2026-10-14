"""Application logging setup without configuration or credential dumps."""

import logging

LOGGER_NAME = "aiseoonline"


def configure_logging(level: str) -> logging.Logger:
    """Configure an application-scoped logger; leave host logging alone."""
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(level)
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
        logger.addHandler(handler)
    logger.propagate = False
    return logger
