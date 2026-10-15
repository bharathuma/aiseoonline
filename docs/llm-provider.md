# Optional LLM provider layer

The AISEOOnline backend can call an LLM through the typed `LLMProvider` interface. OpenAI Chat Completions is the initial adapter. The nine public SEO tools remain **fully deterministic** and **do not call the provider**. This PR adds infrastructure only: it does not expose an AI endpoint, activate paid API usage, or deploy anything.

The implementation lives in `apps/api/src/aiseoonline_api/ai_core/`, with:

- `contracts.py` — validated inputs, structured results, token budgets, usage, pricing, streaming events and typed failures
- `prompts.py` — immutable trusted prompt templates, explicit versioning and quoted untrusted website evidence
- `openai_provider.py` — asynchronous OpenAI adapter, HTTPS, typed JSON results, SSE, rate-limit handling, retries, timeouts and concurrent-request limits
- `fixture_provider.py` — explicit deterministic provider for offline tests, not a fallback for live failures

LangChain and LangGraph are deliberately **not** required by the low-level HTTP transport. They can consume the provider interface in the planned agent phase. This keeps the transport lightweight, testable and replaceable.

## Configuration

Set `AISEO_OPENAI_API_KEY` only on the backend when deliberately enabling paid calls. Without credentials, the application still starts; calling `make_openai_provider()` raises `CredentialsUnavailable`. No API key is ever sent to the frontend. The environment variables are listed in [the example configuration](../.env.example).

Defaults: `gpt-4o-mini`, 8,192 conservative input characters/byte ceiling, 512 maximum completion tokens, 8,704 total tokens, 15-second per-operation network timeouts, two retries and three concurrent provider requests. Settings are upper-bounded by Pydantic. The conservative admission guard counts JSON-encoded UTF-8 bytes to avoid relying on an absent tokenizer; it may reject prompts that would actually fit in the model context. **Actual** input/output token counts are taken from the provider response and enforced again.

No built-in price is assumed. Configure **both** `AISEO_LLM_INPUT_USD_PER_MILLION` and `AISEO_LLM_OUTPUT_USD_PER_MILLION` to compute a decimal USD estimate from measured usage; otherwise `cost_usd` is `None`. The pricing configuration must be kept in sync with the actual model and contract.

## Example — typed response

This code requires a deliberately configured backend API key. Do not run it automatically in CI:

```python
import asyncio

from pydantic import BaseModel

from aiseoonline_api.ai_core import GenerationRequest, make_openai_provider
from aiseoonline_api.config import Settings


class TitleSuggestion(BaseModel):
    title: str
    rationale: str


async def main() -> None:
    provider = make_openai_provider(Settings())
    try:
        result = await provider.complete(
            GenerationRequest(
                template_id="meta_draft", template_version="v1",
                task="Suggest a clear title using only the supplied facts.",
                website_text="Observed H1: Ceramic planters. No prices or discounts shown.",
                max_output_tokens=320,
            ),
            schema=TitleSuggestion,
        )
        print(result.value.model_dump())
        print("Measured usage:", result.usage.model_dump())
        print("Estimated cost (when configured):", result.cost_usd)
    finally:
        await provider.aclose()


asyncio.run(main())
```

The adapter asks the API for JSON Schema-guided output (without strict-mode assumptions that all Pydantic schemas are supported), and validates the returned JSON against the specified Pydantic model. Incomplete, malformed, refused, absent-usage and budget-exceeding responses **raise typed exceptions**; none are silently treated as valid. Model-generated text is advisory and must not overwrite deterministic SEO facts.

## Example — streaming

```python
async for event in provider.stream(
    GenerationRequest(task="Explain observed title issues.", website_text="Title element absent.")
):
    if event.kind == "delta":
        print(event.text, end="")
    elif event.kind == "usage":
        print("Tokens:", event.usage)
    elif event.kind == "done":
        print("Completed")
```

A stream carries text deltas, then actual usage and a completion event. Partially emitted output is never replayed on network failure. If the provider does not deliver the final usage chunk or ends with an unsupported reason, the stream raises an error. Consumers must treat partial text as unverified until `done`.

## Prompt and security boundaries

All system messages come from registered, versioned backend templates. Requests can select registered names and versions but **cannot supply system messages**. The user's task and the scraped page excerpt are JSON-serialized into the **user** role, with a separate labeled `untrusted_website_text` field. Injection text inside fetched pages never becomes executable instructions or a trusted system message. This reduces prompt-injection risk but does **not** guarantee a model will ignore every malicious instruction: downstream agents must continue to verify citations and never execute a model response as code.

The API client does not follow HTTP redirects, makes requests to the fixed OpenAI HTTPS endpoint, does not log prompts, raw provider errors or responses, and only logs model and measured token totals. Keep API egress locked to approved endpoints in deployment and never log the Authorization header. Model outputs remain untrusted.

## Retry behavior and error reporting

- Retry up to two times on HTTP 429, 500, 502, 503, 504 and transient network failures, using short capped exponential delays and a capped `Retry-After`.
- Do **not** retry authentication errors, schema errors or budget violations.
- Timeouts, rate limits, unavailable credentials, unexpected provider responses, and budget failures are distinct typed exceptions.
- Streaming retries apply only before a successful stream starts; partial streams never replay. Provider access is guarded by a semaphore.

The provider is currently a Python service-level component, not a public HTTP endpoint, so credentials and user data have no browser exposure. Public authentication, site ownership controls and paid-call budgets are prerequisites for any future AI endpoint.

## Testing

Run offline tests:

```sh
uv sync --project apps/api --locked --group dev
uv run --project apps/api --locked pytest apps/api/tests/test_ai_core.py -q
uv run --project apps/api --locked ruff check apps/api
uv run --project apps/api --locked ruff format --check apps/api
uv run --project apps/api --locked mypy --config-file apps/api/pyproject.toml apps/api/src
```

Tests use `httpx.MockTransport` and the explicit `FixtureProvider`. They never use live credentials or incur provider cost. **No live paid integration tests run in CI.** A future opt-in live integration test must be separately approved, billed and labeled.

## API reference

The adapter uses the documented OpenAI [Chat Completions API](https://platform.openai.com/docs/api-reference/chat/create), including `max_completion_tokens`, `response_format`, `stream_options.include_usage`, and the measured `usage` object. The adapter is deliberately kept behind an interface so newer Responses API models can be added without changing callers.
