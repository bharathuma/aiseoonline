# Security Policy

AISEOOnline has no supported application release yet.

## Reporting a vulnerability

Please do not publish exploit details, credentials, or private data in a GitHub issue or pull request.

If the repository has private vulnerability reporting enabled, use **Security → Report a vulnerability**. Otherwise, use an available private contact method on the [maintainer's GitHub profile](https://github.com/bharathumashankar).

Include the affected component, potential impact, and steps to reproduce the problem using systems you own or have permission to test. A response-time guarantee is not currently offered.

## Security considerations

The application will accept URLs and process third-party web content, so the implementation must address:

- Server-side request forgery, including DNS changes and redirects.
- Request timeouts, response-size limits, concurrency, and crawl budgets.
- Website ownership verification for larger or private scans.
- Authorization for project data, reports, and indexed documents.
- Untrusted content and prompt injection in AI workflows.
- API credential isolation, rate limits, and model usage budgets.
- Minimal sensitive data in logs, traces, and analytics.

These are requirements for future releases, not claims that any protection has already been deployed. The policy will be updated when supported versions are available.
