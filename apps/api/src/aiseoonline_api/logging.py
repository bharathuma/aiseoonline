"""Application-scoped logging with request correlation and credential redaction."""

import logging
import re
from contextvars import ContextVar

LOGGER_NAME = "aiseoonline"
current_request_id: ContextVar[str] = ContextVar("request_id", default="-")

_CREDENTIALS = (
    (re.compile(r"(?i)\b(bearer)\s+[^\s,;]+"), r"\1 [REDACTED]"),
    (
        re.compile(r"(?i)\b(password|token|secret|api[_-]?key)\s*[:=]\s*[^\s,;]+"),
        r"\1=[REDACTED]",
    ),
    (
        re.compile(r"(?i)(\b(?:postgresql|postgres|redis)(?:\+psycopg)?://[^:/@\s]+:)[^@/\s]+(@)"),
        r"\1[REDACTED]\2",
    ),
    (re.compile(r"\bsk-[A-Za-z0-9_-]{8,}\b"), "[REDACTED]"),
)


def redact(value: str) -> str:
    for pattern, replacement in _CREDENTIALS:
        value = pattern.sub(replacement, value)
    return value


class PrivacyFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = current_request_id.get()
        record.msg = redact(record.getMessage())
        record.args = ()
        return True


def configure_logging(level: str) -> logging.Logger:
    """Configure this application's logger without changing the host logging."""
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(level)
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s %(levelname)s %(name)s request_id=%(request_id)s %(message)s"
            )
        )
        handler.addFilter(PrivacyFilter())
        logger.addHandler(handler)
    logger.propagate = False
    return logger
