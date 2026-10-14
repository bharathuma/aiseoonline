# ADR 0005: Evidence and security boundaries

**Status:** Accepted; not implemented.

## Context

The application processes URLs provided by visitors, third-party pages, and model-generated content. These inputs are not inherently trustworthy.

## Decision

Technical SEO findings must be supported by actual parsed page data. AI may explain findings but should not invent or silently alter them.

Fetching must enforce URL and network restrictions, redirect checks, timeouts, response-size ceilings, and crawl budgets. Extensive audits require proof of website ownership. Private projects require access checks at both API and retrieval layers.

AI tools must have explicit permissions and limits on time, steps, tokens, and cost. Retrieved page content must never grant the model additional authority.

## Alternatives

LLM-only site audits, unrestricted anonymous crawling, and prompt-only security controls are not reliable enough.

## Consequences

Some features will require authentication and additional tests. Security controls must be verified at both the application and infrastructure boundaries before public use.
