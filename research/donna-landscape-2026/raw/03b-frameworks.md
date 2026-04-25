# Agent Frameworks (part 2) — Landscape Scan (April 2026)

Subagent: agent-frameworks (part 2 of 2)
Date: 2026-04-25
Scope: Covers Nous Hermes Agent, AutoGen (Microsoft), LlamaIndex Agents, Semantic Kernel (Microsoft). LangGraph lives in 03-agent-frameworks.md and is not duplicated here. Focus: primitive shape, checkpointing, tool registry/sandboxing, observability, provider abstraction, solo-operator viability, governance/breaking-change history.

## Nous Hermes Agent (Nous Research)

- Repo: https://github.com/NousResearch/hermes-agent
- Docs / product: https://hermes-agent.nousresearch.com/ (tried 2026-04-25; returned 403 to my fetcher, but pages are public in browser per external references)
- Security docs: https://hermes-agent.nousresearch.com/docs/user-guide/security
- MCP docs: https://hermes-agent.nousresearch.com/docs/user-guide/features/mcp

**One-line:** A self-improving, self-hostable personal agent ("the agent that grows with you") from Nous Research — closed learning loop with autonomous skill creation from experience.

**Architecture:** Python (~87%) + TypeScript (~9%) per the repo [github.com/NousResearch/hermes-agent]. Primitive shape is a **state-machine agent loop** rather than a user-authored graph; the framework is agent-first, not orchestration-first. **Tool registry:** 40+ built-in tools plus MCP servers; terminal backends are pluggable (local, Docker, SSH, Daytona, Singularity, Modal) — i.e. the *execution substrate* is abstracted, not just the tool set. **Memory:** persistent across sessions; FTS5-backed session search with LLM summarisation, and a "Honcho dialectic" user-model layer; v0.7.0 added a *pluggable memory-provider interface* [github.com/NousResearch/hermes-agent/releases]. **Checkpointing:** serverless hibernation on Daytona/Modal rather than explicit graph checkpoints — environment pauses when idle. **Observability:** TUI (React/Ink rewrite in v0.11.0) with streaming tool output, `/compress`, `/usage`, `/steer`. **Provider abstraction:** broad — Nous Portal, OpenRouter (200+ models), OpenAI, Bedrock (v0.11.0), xAI, Google AI Studio, Xiaomi MiMo, z.ai/GLM, Kimi, MiniMax, HuggingFace, custom endpoints.

**Security posture (from security/MCP docs, summarised via 07-security.md since my direct fetch 403'd):** filtered env to subprocesses (only PATH, HOME, USER, LANG, LC_ALL, TERM, SHELL, TMPDIR, XDG_\* pass through — API keys stripped); OSV malware scan on every npx/uvx-spawned MCP server before launch; per-server tool include/exclude lists; resources/prompts disableable per server; tool error messages sanitised before returning to the LLM. v0.7.0 release notes call out "gateway hardening" and "secret exfiltration blocking" [release notes].

**Production signals:** messaging platforms count is the telling signal — 17 as of v0.11.0 (Telegram, Slack, iMessage via BlueBubbles, WeChat/WeCom, QQBot, etc.). That is a solo/prosumer-operator product, not an enterprise SaaS. No named enterprise adopters. No public incident/migration-off stories I found.

**Solo viable?** Yes — this is the closest shipping product to Donna's design centre. Runs on a "$5 VPS, GPU cluster, or serverless" per the README. MIT-licensed. Self-hostable by default.

**License:** MIT. **Pricing:** OSS free; Nous Portal and Nous Tool Gateway (web search, image gen, TTS, browser automation, v0.10.0) are subscriptions.

**Governance/breaking-change history:** Pre-1.0 (latest = v0.11.0 on 2026-04-23). Release cadence is weekly in April 2026. None of v0.7.0–v0.11.0 release notes flag breaking changes explicitly, but the pre-1.0 version label means API stability is not guaranteed.

**Scope gaps / things Donna should note:**
- "Self-improving" = autonomous skill creation + agent-curated memory with periodic nudges. This is the *same* design space as Donna's procedural memory but with a stronger autonomy posture (Hermes mutates its own skill set); Donna's "oracle-not-scholar" constrained-extrapolation tenet probably wants more operator-in-the-loop gating than Hermes defaults to.
- MCP-heavy tool model means Hermes inherits MCP's trust problems; the mitigations above are thoughtful but do not claim to solve prompt injection.
- Currency: all cited releases are April 2026 — fully current.

## AutoGen (Microsoft) — now *maintenance mode*, superseded by Microsoft Agent Framework

- Repo: https://github.com/microsoft/autogen
- AG2 community fork: https://github.com/ag2ai/ag2
- Successor: https://github.com/microsoft/agent-framework
- Migration guide: https://learn.microsoft.com/en-us/agent-framework/migration-guide/ (auth-walled to my fetcher; referenced via Microsoft devblogs)

**One-line:** Microsoft's multi-agent conversation framework; as of April 2026 in maintenance mode, superseded by Microsoft Agent Framework.

**Status:** The `microsoft/autogen` README explicitly says: *"AutoGen is now in maintenance mode. It will not receive new features or enhancements and is community managed going forward. New users should start with Microsoft Agent Framework."* Latest release **v0.7.5 on 2025-09-30** [github.com/microsoft/autogen] — no releases in the last ~7 months, confirming maintenance status.

**Architecture (historical):** Layered — Core API (event-driven message passing between actor-style agents), AgentChat API (two-agent / group-chat conversation patterns), Extensions (LLM clients, MCP tools). Python/.NET/TypeScript. **No explicit checkpointing** in the README. **Tools** via Extensions API + MCP. **Observability** not called out in README. **Provider abstraction** via Extensions (OpenAI, Azure OpenAI, Anthropic, local).

**License:** MIT (code) + CC-BY-4.0 (docs).

**Governance / fork drama:** Well-documented 2024 split. Original AutoGen creators (Chi Wang, Qingyun Wu) left Microsoft in Nov 2024, created AG2AI org, forked AutoGen as AG2 citing speed and governance neutrality. Microsoft responded with the AutoGen 0.4 rewrite, then in 2025–2026 converged with Semantic Kernel into **Microsoft Agent Framework 1.0 GA (2026-04-03 / 04-07)** [devblogs.microsoft.com/agent-framework]. AG2 continues independently — AG2 v0.12.1 released 2026-04-24; Apache-2.0 for new code, MIT for inherited Microsoft code. Pattern remains conversation-centric (swarms, group chats, nested chats, sequential chats). [github.com/ag2ai/ag2]

**Production signals:** Pre-split AutoGen had broad research/enterprise uptake; post-split, enterprise users are being steered to Microsoft Agent Framework, hobbyists/researchers largely to AG2 or LangGraph. The three-way split is itself a production signal — the ecosystem fragmented.

**Solo-operator viable?** Original AutoGen: technically yes but abandoned. AG2: yes, more multi-agent-oriented than single-loop. Neither is a great single-user substrate — both are multi-agent-first; Donna is solo-operator, single-agent-primary.

**Breaking-change history:** 0.2 → 0.4 was a *rewrite* (breaking); AG2 forked off 0.2 and is backwards-compatible with 0.2 code; Microsoft path now asks you to migrate again, to Agent Framework. Two forced migrations in ~18 months.

**Scope gaps / relevance to Donna:**
- Multi-agent framing is overkill for a single-user oracle. Group chat primitives don't map to "one operator, one assistant, many tools."
- Governance chaos in 2024–2025 is a cautionary tale: do not couple Donna to a framework that may fork under you. Prefer lower-level, more stable substrates (plain loop; LangGraph v1 with its stability guarantees).

## Microsoft Agent Framework 1.0 (covered here because AutoGen and Semantic Kernel both funnel into it)

- Repo: https://github.com/microsoft/agent-framework
- Docs: https://learn.microsoft.com/en-us/agent-framework/ (auth-walled to my fetcher)
- Launch blog: https://devblogs.microsoft.com/agent-framework/microsoft-agent-framework-version-1-0/

**One-line:** Microsoft's unified successor to AutoGen and Semantic Kernel — a .NET + Python SDK for single- and multi-agent workflows. GA'd **April 3, 2026**.

**Architecture:** Semantic Kernel's service connectors + session/middleware layer form the foundation; AutoGen's orchestration concepts re-implemented as a **graph workflow engine** on top [devblogs.microsoft.com/agent-framework/microsoft-agent-framework-version-1-0/]. Workflows support branching, fan-out/parallel, converge. Python + .NET ship with the same API shape under `Microsoft.Agents.AI`. **Checkpointing is stable** and configurable: `WorkflowBuilder().with_checkpointing(storage).build()` at build time, or `workflow.run(..., checkpoint_storage=storage)` at runtime — checkpoints write at the end of each *superstep* and workflows can be paused/resumed across process restarts. **Tools** via Semantic-Kernel-style decorated functions + MCP + A2A. **Observability:** OpenTelemetry hooks; DevUI is a preview feature. **Provider abstraction:** model-agnostic (OpenAI, Azure OpenAI, Anthropic, others).

**License:** MIT. **Pricing:** OSS free; deeper Azure integration is paid.

**Solo viable?** Technically yes but enterprise-shaped (service connectors, middleware, hosted-agent integration). Heavy dependency footprint.

**Governance/breaking changes:** RC on 2026-02-19, GA on 2026-04-03. *Second* forced migration for AutoGen users, *first* for Semantic Kernel users. Microsoft committed to long-term support at 1.0.

## LlamaIndex Agents (AgentWorkflow on Workflows 1.0)

- Core repo: https://github.com/run-llama/llama_index
- Workflows repo: https://github.com/run-llama/workflows-py
- AgentWorkflow announcement: https://www.llamaindex.ai/blog/introducing-agentworkflow-a-powerful-system-for-building-ai-agent-systems
- Workflows 1.0 announcement: https://www.llamaindex.ai/blog/announcing-workflows-1-0-a-lightweight-framework-for-agentic-systems (2025-06-30)
- Docs: https://developers.llamaindex.ai/python/framework/ (403'd to my fetcher; accessible in browser)

**One-line:** Event-driven, step-decorated agent/workflow framework that grew out of LlamaIndex's RAG history into a general agentic substrate.

**Architecture:** Python-first (~72%) [github.com/run-llama/llama_index]. Primitive shape is **event-driven steps**: workflows are async Python functions decorated with `@step` that consume and emit typed `Event` objects. The decorator infers I/O types and the framework validates the workflow before run [llamaindex.ai/blog/announcing-workflows-1-0]. Above this sits `AgentWorkflow`, which bundles `FunctionAgent` (for function-calling models) and `ReActAgent` (for non-function-calling models) — both inherit `BaseWorkflowAgent`. **Checkpointing:** pluggable durability — save/resume runs from files or a DB backend. `llama-agents-server` wraps workflows as REST APIs with "streaming, persistence, and human-in-the-loop support" [github.com/run-llama/workflows-py]. **Tools:** registered as Python callables or LlamaIndex `Tool` objects; MCP servers supported; no built-in sandbox. **Observability:** integrates with OpenTelemetry, Arize, LangFuse via instrumentation. **Provider abstraction:** strong — `llama_index.llms.*` packages cover OpenAI, Anthropic, Azure OpenAI, Gemini (3 is now the default per v0.14.19, 2026-03-25), NVIDIA, MiniMax, local via Ollama, HuggingFace, etc. **Memory:** `ChatMemoryBuffer`, vector-store-backed memory, and the strategic pivot mentions "persistent memory" at the AgentWorkflow layer.

**Production signals:** Broad RAG adoption pre-2025 is the base. 2025–2026 rebrand is explicit — docs are now built around AgentWorkflow ("LlamaIndex rebranded from a RAG framework to a multi-agent framework"). Notable: LlamaParse/LlamaCloud are the commercial pull; AWS Prescriptive Guidance includes LlamaIndex as an agentic framework option.

**Breaking-change history:** Workflows 1.0 (Jun 2025) was itself a re-architecture. v0.14.18 (Mar 2026) deprecated Python 3.9 and fixed a breaking change in "Message Block Buffer Resolution." v0.14.20 (Apr 2026) pinned `llama-index-workflows >=2.14.0`. Workflows package has its own release cadence — `llama-agents-server@v0.4.7` on 2026-04-24. Cadence is high; breaking changes occur but are flagged in changelogs.

**License:** MIT (both core and workflows). **Pricing:** OSS free; LlamaCloud/LlamaParse are paid SaaS.

**Solo-operator viable?** Yes. Lightweight workflows package installs standalone (`pip install llama-index-workflows`) without the full RAG stack. Event-driven + `@step` is a reasonable primitive for a single-user agent loop with typed transitions.

**Scope gaps / relevance to Donna:**
- Historical DNA is document-centric RAG; if Donna avoids heavy RAG, much of the LlamaIndex surface is unused.
- Event-driven steps are a *different* primitive from LangGraph's state graph — more Python-native, less explicit state-machine-shaped. Donna's trifecta-partitioning requirement (see 07-security.md) maps awkwardly to arbitrary event flow; a graph with explicit trust-boundary nodes fits better.
- Multi-agent patterns are available but not forced; single-agent use is a first-class case.

## Semantic Kernel (Microsoft)

- Repo: https://github.com/microsoft/semantic-kernel
- Devblog: https://devblogs.microsoft.com/semantic-kernel/ (now the Microsoft Agent Framework blog)
- Support-policy discussion: https://github.com/microsoft/semantic-kernel/discussions/13215

**One-line:** Microsoft's enterprise-flavoured agent orchestration SDK (C#/Python/Java), now positioned as the foundation layer that Microsoft Agent Framework is built on top of.

**Architecture:** C# (~67%), Python (~31%), Java [github.com/microsoft/semantic-kernel]. Primitives are **Kernel** (central orchestrator that wires services + plugins), **Plugins** (groups of functions declared via `@kernel_function` / `[KernelFunction]`), **Agents** (`ChatCompletionAgent` as the primary construct), and historically **Planners** (now mostly superseded by function-calling). **Tool declaration:** `@kernel_function` decorator with type annotations; no built-in sandbox — you run in-process. **Memory:** pluggable vector-store connectors (Azure AI Search, Elasticsearch, Chroma, Pinecone, Redis). **Checkpointing:** no explicit workflow-checkpoint primitive (that's where Agent Framework adds value). **Observability:** OpenTelemetry-first; telemetry is a selling point. **Provider abstraction:** broad and genuine — OpenAI, Azure OpenAI, HuggingFace, Nvidia, Anthropic via connectors, local via Ollama.

**Latest release:** `python-1.41.2` on **2026-04-08** [github.com/microsoft/semantic-kernel/releases]. Still shipping patches.

**Support posture:** Per the official Agent Framework devblog, SK v1.x will be supported *"for the foreseeable future, with critical bugs and security issues being addressed, and some existing features being taken to GA, though the majority of new features will be built for Microsoft Agent Framework."* Microsoft recommends starting new projects on Agent Framework. Community perception (issue #13215) is that SK is already receiving reduced investment — PRs sit open, few feature PRs merged.

**License:** MIT.

**Production signals:** Widely used inside the Microsoft/.NET enterprise stack (Copilot implementations, Azure-heavy shops). C#-first origin meant .NET enterprise adoption outran Python hobbyist adoption.

**Solo-operator viable?** Technically yes (MIT, runs locally, works with non-Azure models), but the ergonomics are enterprise-shaped: heavy DI patterns, `Kernel` assembly boilerplate, .NET idioms leaking into Python. Not a natural substrate for a solo Python agent loop.

**Breaking-change history / governance:** No hostile drama, but the *strategic* breaking change is real — "Semantic Kernel v2.0" is effectively being delivered as a differently-named product (Microsoft Agent Framework). New features land there; SK gets a soft-sunset migration path rather than a Python 2→3-style rewrite.

**Scope gaps / relevance to Donna:**
- Plugin/Kernel model is interesting as a tool-registry shape, but SK's in-process trust model (plugins run in the host process) conflicts with Donna's prompt-injection-first threat model.
- No checkpointing at the SK layer means durability has to be hand-rolled. LangGraph or Agent Framework give this for free.
- For Donna, SK is mostly a foil — demonstrates what happens when a framework is optimised for the enterprise `.NET` centre and then has to retrofit Python-native and single-user ergonomics.

## Cross-cutting synthesis for Donna

**Primitive shape fit for a solo single-agent loop:**
| Framework | Primitive | Solo-loop fit |
|---|---|---|
| LangGraph (see 03-agent-frameworks.md) | Typed state graph | Strong — explicit trust-boundary nodes are natural |
| Hermes Agent | Opinionated state machine (closed loop) | Strong as a *product*, weaker as a *substrate* you embed |
| LlamaIndex AgentWorkflow | `@step` event-driven | Medium — typed, but trust boundaries are implicit |
| MS Agent Framework | Graph workflow on SK foundation | Medium — capable, heavy dep footprint, enterprise idioms |
| AutoGen / AG2 | Conversation / group-chat actors | Weak — multi-agent-first, solo feels awkward |
| Semantic Kernel | Kernel + plugins + ChatCompletionAgent | Weak — in-process plugin trust, no checkpointing |

**Checkpointing maturity (April 2026):**
- LangGraph: mature, pluggable, v1 stable.
- MS Agent Framework: stable at 1.0 GA, superstep-based, `WorkflowBuilder().with_checkpointing(storage)`.
- LlamaIndex Workflows: pluggable durability; solid but less opinionated.
- Hermes: "serverless hibernation" (environment, not graph state) — different axis.
- AutoGen / AG2: no first-class checkpointing in README.
- Semantic Kernel: none; hand-rolled.

**Tool sandboxing maturity (April 2026):**
- Hermes leads the field for defensible tool-sandbox primitives *today* (env filter, OSV scan on MCP spawn, per-server allowlist, error sanitisation, terminal-backend abstraction including Docker/SSH/Daytona/Modal/Singularity). Others default to "it's your job."
- LangGraph, LlamaIndex, SK, AutoGen, Agent Framework: tool execution is in-process by default; sandboxing is the user's problem.
- None of these frameworks implement CaMeL-style plan/execute trifecta partitioning natively — that remains a Donna build.

**Substrate vs. build-from-scratch recommendation for Donna:**
- **Strongest substrate candidate: LangGraph v1** (see 03-agent-frameworks.md) — typed state graph maps cleanly to trifecta partitioning, checkpointing is first-class, provider-agnostic, and v1 gives stability commitments. It is also the most conservative "not a migrating Microsoft product."
- **Strongest *reference product* (not substrate): Hermes Agent.** Closest design-centre match (self-hostable, solo-operator, MCP hygiene) and its security primitives are directly borrowable. But adopting Hermes as a substrate means inheriting its opinions (autonomous skill creation, agent-curated memory nudges) which conflict with Donna's "oracle-not-scholar" operator-in-the-loop posture.
- **Plausible alternate: LlamaIndex Workflows 1.0** — lightweight `pip install llama-index-workflows`, `@step` primitive, pluggable durability. Less opinionated than LangGraph; more opinionated than a plain loop. Viable if you want Python-native event flow without LangChain's orbit.
- **Avoid as substrate: AutoGen / AG2 / Semantic Kernel.** Two have been through forced migrations in the last 18 months (AutoGen 0.2 → 0.4, now → Agent Framework) and one (SK) is in soft-sunset. Governance risk is real. Multi-agent conversation primitives also don't fit Donna's solo-oracle shape.
- **MS Agent Framework 1.0** is technically the most feature-complete of the Microsoft lineage (graph workflow + checkpointing + SK service connectors), but the enterprise shape + .NET-centric DNA + recent-GA-status make it a poor fit for a Python solo operator today. Re-evaluate in 12 months.

## Scope gaps I couldn't resolve

- **Direct Hermes security-docs and MCP-feature pages** (https://hermes-agent.nousresearch.com/docs/user-guide/security and .../features/mcp) returned HTTP 403 to my WebFetch client. The details I cite are recycled from 07-security.md, which itself sourced them in a browser. I could not independently verify the exact env-var allowlist, OSV-scanner invocation, or tool-error sanitisation implementation in this session.
- **Microsoft Learn docs** (learn.microsoft.com/en-us/agent-framework/*) and **Microsoft devblogs** (devblogs.microsoft.com/*) were consistently 403 to my fetcher. I relied on the Agent Framework GitHub README, the Visual Studio Magazine writeup, and web-search excerpts of the official blog posts. Deep API-shape details (specifically the Python vs .NET divergences, middleware execution order, exact DevUI feature set) are undercollected.
- **LlamaIndex developer docs** (developers.llamaindex.ai) returned 403. AgentWorkflow's exact persistence/resume semantics and the precise relationship between `llama-index-workflows` versions and `llama_index` core versions are undercollected.
- **AG2 production adopters** — AG2's README does not name them, and I did not dig into their case-study pages.
- **AutoGen 0.4 vs AG2 divergence in 2025** is partially resolved (I confirmed both are maintained, Apache-2.0 vs MIT, conversation-pattern-based) but I did not enumerate the feature divergences in detail — e.g. does AG2 have anything Microsoft's Agent Framework migration path cannot absorb?
- **Observability in Hermes** beyond the TUI (slash commands, streaming output) — whether there is a structured trace/replay story for post-hoc analysis was not covered in my sources.
- **Memory primitives** were only partially surveyed here; deeper treatment lives in 04-memory.md and should be cross-referenced when evaluating substrates.
