# Agent Frameworks (part 2) — Landscape Scan (April 2026)

Subagent: agent-frameworks-part-2
Date: 2026-04-25
Scope: CrewAI, Pydantic AI, OpenAI Agents SDK, Claude Agent SDK. Complements 03-agent-frameworks.md (LangGraph). Focus: primitive shape, checkpointing, tool registry/sandboxing, observability, provider abstraction, solo-operator viability.

## CrewAI

- Repo: https://github.com/crewAIInc/crewAI
- Docs: https://docs.crewai.com/
- Pricing: https://crewai.com/pricing
- Enterprise product: https://crewai.com/amp

**One-line:** Python multi-agent orchestration framework built around role-played "agents" collaborating in "crews" (autonomous team) or "flows" (event-driven workflow).

**Architecture:** Python 3.10–3.13 (98.6% Python), MIT license, current `1.14.3` released Apr 24 2026 [https://github.com/crewAIInc/crewAI]. **Primitive shape:** role/goal/backstory `Agent` objects + `Task` units composed into a `Crew` (classic) or a `Flow` (event-driven state machine with `@start`/`@listen`/`@router` decorators). YAML-first agent/task config. **Checkpointing** is explicitly in early release — `@persist` decorator snapshots Flow state to SQLite/Postgres/Redis; APIs "may change" [https://docs.crewai.com/en/changelog]. **Memory** is layered: short-term, long-term, entity, and (2025) "Cognitive Memory" with LLM-inferred scoping and composite recency/importance scoring [https://crewai.com/blog/how-we-built-cognitive-memory-for-agentic-systems]. Mem0 integration is the recommended production memory backend. **Tools** registered directly on agents; no built-in sandbox. **Observability** via CrewAI AMP tracing (paid) or OpenTelemetry export.

**Production:** 47.8k+ stars, 27M+ downloads, 150+ enterprise customers, 2B agent executions claimed (CrewAI marketing, Feb 2026) [https://www.crewai.com/blog/the-state-of-agentic-ai-in-2026]. Heavy enterprise tilt.

**Pricing:** OSS free; hosted AMP free tier (50 exec/mo) → Pro $99/mo → Ultra up to $120k/yr [https://crewai.com/pricing].

**Solo viability:** OSS core runs self-hosted, but the primitive ("hire a crew") is overkill for a single-user agent loop; Flows+@persist is closer to what Donna needs but still immature.

## Pydantic AI

- Repo: https://github.com/pydantic/pydantic-ai
- Docs: https://ai.pydantic.dev/
- Durable-execution docs: https://ai.pydantic.dev/durable_execution/overview/
- Graph docs: https://ai.pydantic.dev/graph/

**One-line:** Type-safe Python agent framework from the Pydantic team — "FastAPI feeling for GenAI."

**Architecture:** Python, MIT. Current `v1.87.0` released Apr 2026 with 239 releases and ~2k commits [https://pypi.org/project/pydantic-ai/]. **Primitive shape:** function-decorated `Agent` objects with `@agent.tool` functions and Pydantic models as `output_type` (structured output with retry-on-validation-failure). Also ships `pydantic-graph` — an explicit graph/state-machine library with typed nodes and persistence snapshots (`SimpleStatePersistence`, `FullStatePersistence`) [https://ai.pydantic.dev/graph/]. **Durable execution:** native Temporal integration for replay-based fault tolerance; agents survive API failures, restarts, and long-running HITL loops [https://temporal.io/blog/build-durable-ai-agents-pydantic-ai-and-temporal]. **Tools** via decorator with `RunContext` dependency injection; JSON-schema auto-generated from type hints; human-in-the-loop tool approval added 2025–26. **Provider-agnostic:** OpenAI, Anthropic, Gemini, DeepSeek, Grok, Cohere, Mistral, Perplexity, Bedrock/Vertex, plus custom. **Observability:** tight Logfire integration (OpenTelemetry), free tier 10M spans/mo; Team $49, Growth $249, self-hosted enterprise via Helm chart on Postgres + S3 [https://pydantic.dev/pricing, https://pydantic.dev/articles/logfire-self-hosting-announcement].

**Production:** ~5000 orgs sending data to Logfire (Pydantic's own metric, Oct 2025+); individual users not publicly listed. Fast release cadence (v1.x since Sep 2025).

**Solo viability:** Strong fit. Typed tools + structured output + optional graph + self-hostable OTel backend — closest to Donna's "oracle with labeled inference" stance.

## OpenAI Agents SDK

- Repo: https://github.com/openai/openai-agents-python
- Docs: https://openai.github.io/openai-agents-python/
- Announcement (evolution): https://openai.com/index/the-next-evolution-of-the-agents-sdk/

**One-line:** OpenAI's "production-ready Swarm successor" — a lightweight Python agent framework centered on Agents, Handoffs, Guardrails, Sessions, and (new in 2026) Sandbox Agents.

**Architecture:** Python 3.10+, MIT, current `0.14.6` (Apr 25 2026) [https://github.com/openai/openai-agents-python]. **Primitive shape:** Agents are LLMs + instructions + tools + handoffs; `handoff()` delegates to other agents; `Runner.run()` drives the loop. **Tools** via `@function_tool` decorator (JSON schema auto-generated), plus MCP and hosted tools. **Guardrails** are parallel safety-check agents for input/output validation. **Sessions** auto-manage conversation history across runs. **Sandbox Agents (beta, 2026)** add `SandboxAgent`, `Manifest`, `SandboxRunConfig` for persistent isolated workspaces — files, Git repos, mounts, snapshots, serialized-session resume [per OpenAI 2026 changelog summaries; docs at openai.github.io/openai-agents-python/sessions/ unreachable during fetch]. **Provider abstraction:** advertised as "100+ LLMs" via OpenAI Responses/Chat Completions or LiteLLM adapter; but first-party models and the Traces dashboard are OpenAI-only. **Observability:** built-in tracing → OpenAI Traces dashboard (platform.openai.com/traces); Langfuse/Langsmith integrations available.

**Breaking changes 2026:** requires `openai` v2.x (v1.x dropped); several APIs changed `Agent` → `AgentBase` typing; MCP `list_tools()` gained `run_context`/`agent`.

**Production:** Coinbase AgentKit; Stripe dispute-agent cookbook example [https://cookbook.openai.com/examples/agents_sdk/dispute_agent].

**Solo viability:** Works locally, but Traces dashboard and Sandbox Agents push you toward OpenAI-hosted infra. License is permissive; ergonomics are minimal.

## Claude Agent SDK (Anthropic)

- Repo (Python): https://github.com/anthropics/claude-agent-sdk-python
- Repo (TS): https://github.com/anthropics/claude-agent-sdk-typescript
- Docs: https://code.claude.com/docs/en/agent-sdk/overview
- Changelog: https://github.com/anthropics/claude-agent-sdk-python/blob/main/CHANGELOG.md

**One-line:** Anthropic's SDK for building agents on top of the Claude Code runtime — renamed from "Claude Code SDK" in late 2025 to signal broader agent-building use beyond coding.

**Architecture:** Python 3.10+ (current `0.1.68`, bundles Claude CLI 2.1.119, Apr 2026) and a TS SDK. MIT code; Anthropic Commercial ToS governs usage. **Primitive shape:** a subprocess-wrapped CLI agent driven via `query()` (one-shot) or `ClaudeSDKClient` (stateful, bidirectional). **Rename breaking changes:** `ClaudeCodeOptions` → `ClaudeAgentOptions`, merged system prompts, stricter settings isolation, programmatic subagents [CHANGELOG §0.1.0]. **Tools/MCP:** `@tool` decorator defines in-process MCP servers (no subprocess overhead); external MCP servers composable; tool annotations (`readOnlyHint`, `destructiveHint`, `idempotentHint`, `openWorldHint`) since 0.1.31. **Permissions/sandboxing:** `allowed_tools`/`disallowed_tools` lists, `permission_mode` (incl. new `auto`), `PreToolUse`/`PostToolUse`/`PermissionRequest` hooks for deterministic intercept. **State:** sessions with `fork_session()`, `delete_session()`, pagination (0.1.51); full `SessionStore` adapter protocol with S3/Redis/Postgres reference impls (0.1.64, Feb–Mar 2026). **File checkpointing** (`enable_file_checkpointing`, `rewind_files()`) since 0.1.15. **OTel distributed tracing** since 0.1.60. **Provider abstraction:** Claude-only; Bedrock/Vertex/Azure accepted, but all proxy to Claude. Non-Anthropic models require third-party gateways (Bifrost) [https://github.com/anthropics/claude-agent-sdk-python/issues/410].

**Solo viability:** Excellent ergonomics for a single operator running Claude; the SessionStore+checkpointing story is the most mature of the four. The vendor-lock is real — Donna would couple tightly to Anthropic.

## Scope gaps I couldn't resolve

- **CrewAI docs site** (`docs.crewai.com/`, `docs.crewai.com/en/changelog`) returned HTTP 403 to WebFetch — version-specific Flow checkpointing API details sourced via secondary search; original changelog not directly read.
- **Pydantic AI landing page** (`ai.pydantic.dev/`) and **OpenAI Agents SDK docs** (`openai.github.io/openai-agents-python/sessions/`, `/release/`) were 403-blocked for WebFetch; relied on repo READMEs and search-result summaries for session/runtime detail. Precise release-note dates for OpenAI Agents SDK 2026 breaking changes (openai v2 requirement, AgentBase typing) are summarized but not line-cited from the GitHub release feed.
- **CrewAI OSS→enterprise disclosures:** no public data on how many of the "2B agent executions" ran on OSS vs. AMP; adoption claims are self-reported.
- **Production adopters** for Pydantic AI and Claude Agent SDK are not publicly enumerated (beyond Logfire user counts and Anthropic's own dogfooding in Claude Code); could not find named customer case studies.
- **OpenAI Agents SDK Sandbox Agents beta:** could not verify sandbox isolation model (container, gVisor, firecracker?) from primary docs — only the API surface is documented.
- **Claude Agent SDK pricing** is effectively Anthropic API token pricing; no separate SDK fee, but `max_budget_usd` implies per-run cost controls — full economics depend on Claude API list prices, not the SDK itself.
