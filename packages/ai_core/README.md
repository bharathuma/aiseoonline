# ai_core

The executable backend LLM implementation lives in [apps/api/src/aiseoonline_api/ai_core](../../apps/api/src/aiseoonline_api/ai_core). It includes typed provider contracts, an OpenAI adapter, structured output verification, versioned prompts, budgets, streaming, and deterministic offline fixture providers.

This directory is reserved for any future truly shared package. Avoid duplicating the executable backend implementation here. See [LLM provider documentation](../../docs/llm-provider.md).
