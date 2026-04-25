# Agent Frameworks — digest

> **Coverage warning:** The raw file contains only ONE product (LangGraph). The upstream subagent suffered a stream idle timeout before covering the other planned targets (CrewAI, Pydantic AI, OpenAI Agents SDK, Claude Agent SDK, Nous Hermes Agent, AutoGen, LlamaIndex Agents, Semantic Kernel). This digest faithfully reflects only what is in the raw file.

## Per-product table

| product | one-line | arch (lang/store/llm/tool/state) | pricing | self-host | notable | source |
|---|---|---|---|---|---|---|
| LangGraph v1+ (LangChain) | Low-level graph-orchestration framework for stateful, durable LLM agents (Python + JS). | Python (+ langgraphjs); state graph / state machine of nodes+edges over typed shared state; pluggable checkpointers (in-memory, SQLite, Postgres) with replay/fork; `@tool` decorators via LangChain Core, Pydantic validation, sandboxing left to user; provider-agnostic via LangChain Core wrappers; observability via LangSmith or OTel hooks; memory split short-term (graph state) + long-term `Store` (Postgres/Redis). | OSS free (MIT); LangSmith + LangGraph Platform paid (managed). | Yes — runs locally with SQLite checkpointer, no cloud needed. | v1.0 GA Oct 2025; latest `1.1.9` (Apr 21 2026); `langgraph.prebuilt` deprecated in favor of `langchain.agents`; production users: Klarna, Replit, Elastic; LangChain core saw migration churn 2024–2025. | https://docs.langchain.com/oss/python/releases/langgraph-v1 |

## Three patterns to steal

1. **Per-node automatic checkpointing with pluggable backends and replay/fork primitives.** (a) Every node execution writes a checkpoint into a backend you choose, and you can replay or fork from any point. (b) LangGraph v1. (c) Donna's "oracle, not scholar" stance requires the operator to drill into evidence and re-run reasoning under different assumptions; checkpoint+fork is the mechanism for that validation surface, and SQLite-backed checkpoints fit the self-host tenet. (d) https://docs.langchain.com/oss/python/releases/langgraph-v1
2. **Split memory: short-term graph state + long-term `Store` interface over Postgres/Redis.** (a) Frame ephemeral run state and durable cross-session memory as two distinct interfaces with different backends. (b) LangGraph v1. (c) Donna treats memory as first-class with episodic/semantic/procedural layers; cleanly separating run-scoped state from durable store maps onto that and lets the operator own the data store. (d) https://blog.langchain.com/langchain-langgraph-1dot0/
3. **Local-first OSS core with optional managed plane (LangSmith / LangGraph Platform).** (a) Ship a fully local-runnable OSS package and sell observability/hosting separately rather than locking core features to cloud. (b) LangGraph v1. (c) Donna's solo-operator + self-host tenet rules out cloud-required tooling; this packaging model proves the OSS-core / paid-plane split is viable for agent infra. (d) https://github.com/langchain-ai/langgraph

## Three patterns to avoid

*(None listed — the rules require a specific post-mortem URL per entry, and the raw file does not include any post-mortem links for the LangGraph entry. The general churn note about LangChain core migrations 2024–2025 is mentioned without a primary-source post-mortem URL, so it is dropped per the rule.)*

## Cross-cutting observations

- Only one product (LangGraph) is documented; cross-category claims would be speculative and are intentionally omitted.
- Within that one data point: the framework explicitly leaves tool sandboxing to the user — a meaningful gap for any assistant that ingests open-web content under prompt-injection assumptions.
- Provider abstraction is delegated upward to LangChain Core wrappers rather than reimplemented in the agent layer.
- v1.0 was advertised as zero-breaking-change, but `langgraph.prebuilt` was simultaneously deprecated in favor of `langchain.agents` — a signal that "stable" still ships re-homing churn.

## Unresolved

- **Eight planned frameworks missing from the raw file due to upstream subagent stream idle timeout:** CrewAI, Pydantic AI, OpenAI Agents SDK, Claude Agent SDK, Nous Hermes Agent, AutoGen, LlamaIndex Agents, Semantic Kernel. Without these, the category cannot be compared and the "patterns to steal/avoid" sections are evidence-starved. This is the dominant gap and blocks synthesis on agent-loop primitives, decorator-vs-graph-vs-crew shape, and provider-abstraction conventions across the field.
- **No "Scope gaps" section in the raw file** — the subagent terminated before writing one, so we cannot inherit its self-identified gaps.
- **No post-mortem URLs for LangGraph or LangChain core migration churn**, despite the raw file alluding to "churn — many teams migrated off LangChain core to LangGraph or to plain-Python loops over 2024–2025." Without a primary source this cannot feed the "patterns to avoid" list. Why it matters: Donna needs concrete failure modes to decide whether to build on LangGraph vs. a plain-Python loop.
- **Tool-sandboxing posture is unspecified beyond "left to the user."** Why it matters: Donna's security tenet treats prompt injection as the default state of the open web; we need to know what each framework does (or doesn't) provide before adopting one.
- **Claude Agent SDK GA, OpenClaw skill-store post-mortem (Nov 2025), and NCSC prompt-injection paper (Dec 2025)** flagged as recent in DONNA_CONTEXT are not yet reflected against any framework in this category.
- **No comparison of checkpointer durability/perf, cost of LangSmith vs. self-hosted OTel, or memory-store schema** in the single entry — needed for solo-operator viability calls.
