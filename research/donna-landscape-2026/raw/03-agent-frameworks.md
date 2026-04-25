# Agent Frameworks — Landscape Scan (April 2026)

Subagent: agent-frameworks
Date: 2026-04-25
Scope: Frameworks Donna v0.5 could be built on or against. Focus: primitive shape (graph/crew/decorator), checkpointing, tool registry/sandboxing, observability, provider abstraction, solo-operator viability.

## LangGraph v1+ (LangChain)

- Repo: https://github.com/langchain-ai/langgraph
- Docs: https://docs.langchain.com/oss/python/releases/langgraph-v1
- Release notes: https://changelog.langchain.com/announcements/langgraph-1-0-is-now-generally-available

**One-line:** Low-level graph-orchestration framework for building stateful, durable LLM agents (Python + JS).

**Architecture:** Python (with parallel `langgraphjs`). Primitive shape is an explicit **state graph / state machine**: you declare nodes, edges, and a typed shared state object. v1.0 (Oct 2025) is the first stable major release; latest at time of research is `langgraph==1.1.9` (Apr 21, 2026) [https://github.com/langchain-ai/langgraph/releases]. **Checkpointing is the headline feature** — automatic per-node checkpointing into pluggable backends (in-memory, SQLite, Postgres) with replay/fork primitives. **Tools** are registered via `@tool` decorators (LangChain Core); validation through Pydantic; sandboxing is left to the user. **Observability** via LangSmith (proprietary, hosted) or OpenTelemetry hooks. **Provider-agnostic** through LangChain Core model wrappers. **Memory:** short-term (graph state) + long-term (`Store` interface, hits Postgres/Redis). v1 release was advertised as zero-breaking-change; `langgraph.prebuilt` is deprecated in favor of `langchain.agents` [https://blog.langchain.com/langchain-langgraph-1dot0/].

**Production:** Klarna, Replit, Elastic [GitHub README]. LangChain Inc. has had churn — many teams migrated off LangChain core to LangGraph or to plain-Python loops over 2024–2025.

**License:** MIT. **Pricing:** OSS free; LangSmith and LangGraph Platform (managed) are paid. **Solo viable:** yes — runs locally with SQLite checkpointer, no cloud required.

