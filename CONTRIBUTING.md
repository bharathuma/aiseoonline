# Contributing

AISEOOnline welcomes bug reports, documentation improvements, tests, and suggestions for useful SEO tools.

## Getting started

Browse open issues before starting work. For significant changes, open an issue to discuss the proposed approach first.

The repository currently contains project documentation. Local development commands will be documented when the frontend and backend are added.

## Submitting a change

1. Create a branch from the latest `main` (for example, `feat/sitemap-validator`, `fix/canonical-checker`, or `docs/getting-started`).
2. Keep changes focused and include tests where behavior changes.
3. Update relevant documentation when adding features or changing APIs.
4. Run the applicable checks and record what passed or could not be run.
5. Open a pull request with a short description of the change and any known limitations.

## Guidelines

- Use deterministic code for technical SEO checks and retain the evidence behind findings.
- Avoid unsupported ranking promises and misleading results.
- Validate all input, particularly URLs and content fetched from other websites.
- Keep AI operations bounded in cost and permissions, and treat retrieved text as untrusted.
- Do not commit credentials, private crawl data, or personal information.
- Make public tools accessible and useful on mobile devices.
- Use sample websites and test data you own or are authorized to use.

For vulnerabilities, follow [SECURITY.md](SECURITY.md) rather than posting a public issue. Contributors agree that their submissions may be distributed under the project's [Apache 2.0 license](LICENSE).

Please follow the [Code of Conduct](CODE_OF_CONDUCT.md).
