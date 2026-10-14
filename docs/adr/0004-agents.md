# ADR 0004: LangGraph for audit workflows

**Status:** Accepted; not implemented.

## Context

Site audits may need conditional checks, partial recovery, and state across long-running jobs. Unbounded model loops can be unreliable and expensive.

## Decision

Use LangGraph for bounded, stateful audit workflows and controlled tool calls. Deterministic code will identify technical findings; models will assist with explanations and prioritization based on evidence.

## Alternatives

A fixed pipeline works well for simpler tasks but offers less flexibility for selective follow-up checks. Unrestricted autonomous agents are harder to test and control.

## Consequences

Workflow tests must cover tool choice, retries, checkpoints, budgets, source citations, and hostile page content. Website-changing actions will require explicit authorization and approval.
