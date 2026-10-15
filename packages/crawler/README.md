# Website crawler

The active implementation lives in [the API crawler package](../../apps/api/src/aiseoonline_api/crawler), organized into URL/DNS validation, pinned network transport, crawl limits and HTML evidence parsing.

This is reusable server-side code; no public crawl endpoint or standalone package is exposed yet. Multi-page crawling remains disabled until account authentication, verified ownership, and request quotas are implemented.

See [crawler security and design notes](../../docs/crawler.md).
