# Agent Memory Systems — Landscape Scan

Category: Agent memory (episodic / semantic / procedural, with temporal versioning).
Date: April 2026.
Lens: Donna v0.5 design tenets — solo-operator, self-hostable, oracle-not-scholar,
memory-first-class, temporal versioning, human-in-loop fact correction.

Targets covered: Letta (MemGPT), Mem0, Zep, Graphiti, mnemostack.

---

## Letta (formerly MemGPT)

- Repo: https://github.com/letta-ai/letta
- Docs: https://docs.letta.com/concepts/memgpt/ , https://docs.letta.com/guides/agents/memory-blocks
- Blog (v1 rearchitecture): https://www.letta.com/blog/letta-v1-agent
- Sleep-time compute: https://www.letta.com/blog/sleep-time-compute , https://docs.letta.com/guides/agents/architectures/sleeptime
- Latest release: v0.16.7, March 31 2026 (per GitHub).

**What it is.** "LLM-as-OS" stateful agent platform; descendant of the MemGPT
paper. Agent self-edits its own memory via tool calls.

**Architecture.** Python (~99.5% of repo). Postgres (with `pgvector`) is the
canonical backend; Aurora-Postgres reference deployment documented by AWS
(https://aws.amazon.com/blogs/database/how-letta-builds-production-ready-ai-agents-with-amazon-aurora-postgresql/).
Three-tier memory: **core** (in-context, editable string blocks like `human` /
`persona`), **recall** (full message history, searchable), **archival**
(pgvector long-term store, semantic search). The agent itself decides what
moves between tiers; "sleep-time agents" run async to consolidate.

**Memory taxonomy.** Does NOT formally separate episodic/semantic/procedural —
memory is undifferentiated text blocks plus archival passages. Procedural-ish
behavior emerges from persona blocks and tool-rules.

**Temporal versioning.** No first-class temporal model. Letta's own comparison
content concedes: "Letta structures memory around agent autonomy" rather than
time, so when a fact changes the agent must overwrite/append; there are no
bitemporal edges (per https://gamgee.ai/vs/zep-vs-letta/).

**Forgetting.** No TTL/decay primitives in the memory layer; reliance on
agent-driven rewrite + sleep-time consolidation.

**Human-in-loop fact mgmt.** Strong: blocks are directly editable by the
developer/user via REST API; deleting = setting `new_content=""`; blocks can
be detached from agents (https://docs.letta.com/guides/core-concepts/memory/memory-blocks/).

**API shape.** REST + Python/TS SDK. `client.agents.messages.create(...)`,
plus block-level CRUD. ADE (Agent Development Environment) for inspection.

**Self-host & pricing.** Fully self-hostable via Docker / `pip install letta`;
OSS Apache-2.0. Letta Cloud pricing TBD.

**Known issues / gaps.** No native bitemporal queries. Block size limits
push large facts into archival, where they lose structure. Memory-correctness
depends on the agent choosing to rewrite. v1 agent loop changed substantially
in late 2025 / early 2026 — older MemGPT integrations need migration.

---
