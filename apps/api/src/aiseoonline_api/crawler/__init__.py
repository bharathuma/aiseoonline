"""Server-side safe fetching and passive SEO extraction, with no public endpoint."""

from .html import Evidence, Heading, Link, MetaTag, ParsedHtml, StructuredData, parse_html
from .service import CrawlLimits, CrawlSession, PageSnapshot
from .urls import (
    CrawlError,
    CrawlLimitExceeded,
    CrawlTimeout,
    HttpStatusError,
    InvalidPage,
    NetworkFailure,
    RobotsDenied,
    SafeURL,
    UnsafeTarget,
    normalize_url,
    resolve_public_addresses,
)

__all__ = [
    "CrawlError", "CrawlLimitExceeded", "CrawlLimits", "CrawlSession", "CrawlTimeout",
    "Evidence", "Heading", "HttpStatusError", "InvalidPage", "Link", "MetaTag",
    "NetworkFailure", "PageSnapshot", "ParsedHtml", "RobotsDenied", "SafeURL",
    "StructuredData", "UnsafeTarget", "normalize_url", "parse_html",
    "resolve_public_addresses",
]
