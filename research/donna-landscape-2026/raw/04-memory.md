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

## Mem0

- Repo: https://github.com/mem0ai/mem0 (Apache-2.0)
- Docs: https://docs.mem0.ai/open-source/overview ; memory types:
  https://docs.mem0.ai/core-concepts/memory-types
- Self-host guide: https://mem0.ai/blog/self-host-mem0-docker
- AWS reference: https://aws.amazon.com/blogs/database/build-persistent-memory-for-agentic-ai-applications-with-mem0-open-source-amazon-elasticache-for-valkey-and-amazon-neptune-analytics/
- Latest: SDK v2.0.0 launched April 16 2026; OpenClaw plugin v1.0.10
  April 23 2026.

**What it is.** A memory-as-a-service layer for LLM agents. Two distributions:
hosted SaaS (`app.mem0.ai`) and self-hosted (Docker Compose: FastAPI +
Postgres/pgvector + Neo4j optional + history DB).

**Architecture.** Python (~56%) + TypeScript (~35%). 19 supported vector
stores (Qdrant, Chroma, pgvector, Pinecone, Mongo, …); Neo4j or Memgraph for
graph mode. v2 introduced **entity linking** so graph DB is now optional;
hybrid retrieval = semantic + BM25 + entity-graph boost.

**Memory taxonomy.** Mem0 explicitly names **episodic, semantic, procedural,
and associative** memory in its core-concepts docs — the most explicit
taxonomy of any product in this category.

**Temporal versioning.** Has timestamps and "memory consolidation" between
short-term and long-term, but no documented bitemporal/validity-window query
("what did the user believe in March?"). Treat temporal model as recency-
weighted, not bitemporal.

**Forgetting.** Documented "decay mechanisms that remove irrelevant
information over time" plus auto-filtering against memory bloat. Specifics
of the decay function are not exposed in primary docs.

**Human-in-loop fact mgmt.** Strong CRUD over REST: `DELETE /delete?memory_id=…`,
`DELETE /delete_all?user_id=…`, plus update/overwrite. MCP server exposes the
same. History DB tracks every change.

**API shape.** `pip install mem0ai` / `npm install mem0ai`. `m.add(...)`,
`m.search(query, user_id=…)`, `m.update(...)`, `m.delete(id)`. Self-hosted
REST mirrors this.

**Self-host & pricing.** OSS Apache-2.0, full self-host via Docker Compose.
Hosted plans gate scale (free tier exists; the Mem0 MCP server review notes
the hosted tier's serious value lives behind paid plans).

**Known issues / gaps.** Quality depends on LLM-driven extraction step;
mediocre temporal reasoning vs Zep/Graphiti; multi-tenant assumptions
(`user_id` is required) leak into a solo-operator setup but are tolerable.

---

## Zep

- Repo: https://github.com/getzep/zep (Community Edition, **deprecated**)
- Cloud: https://www.getzep.com
- Paper: https://arxiv.org/abs/2501.13956 ("Zep: A Temporal Knowledge Graph
  Architecture for Agent Memory", Jan 2025)
- Deprecation note: https://blog.getzep.com/announcing-a-new-direction-for-zeps-open-source-strategy/
- February 2026 retirement wave: https://help.getzep.com/february-2026-deprecation-wave

**What it is.** Managed agent-memory service built on Graphiti. The full Zep
"product" (sessions, users, multi-agent abstractions, dashboard) is
**cloud-only** as of April 2025; the previous self-hostable Community
Edition has been deprecated and is not receiving updates.

**Architecture.** Python (~70%) + Go (~26%). Backend = Graphiti (see next
entry). Hybrid retrieval = semantic + BM25 + graph traversal, no LLM call
in the hot retrieval path. Reports DMR 94.8% vs MemGPT 93.4% and up to 18.5%
LongMemEval improvement with 90% lower latency (per the arXiv paper).

**Memory taxonomy.** Episodic (raw episode nodes) + semantic (entity nodes
and validity-windowed fact edges). No explicit procedural memory primitive.

**Temporal versioning.** Best-in-class. **Bitemporal**: every node and edge
carries both *event time* (when true in the world) and *ingestion time* (when
the agent learned it). Old facts are *invalidated*, not deleted; you can
query "what was true on date X" or "what does the agent currently believe".

**Forgetting.** No decay/TTL — full history is preserved, with invalidation
flags. Costs accumulate over time.

**Human-in-loop fact mgmt.** Via Graphiti API (delete entity edge, delete
episode, patch fact). Zep Cloud surfaces this through dashboard + API.

**Self-host & pricing.** Self-hosting = use Graphiti directly. Zep Cloud is
credit-based; pricing not flat. SOC2 Type 2 / HIPAA on cloud.

**Known issues / gaps.** OSS path forces you down to Graphiti — Zep's
session/user abstractions are not redistributable. Solo-operators get the
worst of the deal: pay cloud or rebuild the surrounding service.

---

## Graphiti

- Repo: https://github.com/getzep/graphiti (Apache-2.0)
- Docs: https://help.getzep.com/graphiti/getting-started/welcome ;
  https://www.graphiti.dev
- Neo4j launch post: https://neo4j.com/blog/developer/graphiti-knowledge-graph-memory/
- Latest release: mcp-v1.0.2, March 11 2026.

**What it is.** Open-source temporal knowledge-graph engine. The substrate
under Zep, but usable standalone — and the only way to self-host the Zep
architecture today.

**Architecture.** Python framework, built on the Claude Agent SDK as of
2026. Pluggable graph backends: **Neo4j 5.26+, FalkorDB 1.1.2+, Kuzu 0.11.2+,
Amazon Neptune** (DB Cluster or Analytics). BM25 in-process or via OpenSearch
Serverless. Async/concurrent ingestion with semaphore-bounded LLM calls
(LLM is used for entity/fact extraction at write time).

**Memory taxonomy.** Three node-types: **Episode** (raw input), **Entity**
(person/concept/product, with evolving summary), **Fact/Relationship**
(temporal triplet with validity window). No formal procedural memory; can be
encoded as entities/facts.

**Temporal versioning.** Bitemporal — explicit `valid_from` / `valid_until`
on edges plus separate ingestion timestamps. Point-in-time queries
supported. This is the engine's headline feature.

**Forgetting.** No TTL/decay. Old facts are invalidated, never auto-pruned.

**Human-in-loop fact mgmt.** API + MCP server expose `delete_entity_edge`,
`delete_episode`, fact-patching. Several community projects (e.g. Notion
front-ends via MCP) wire this to a human UI.

**API shape.** Python SDK + FastAPI REST + MCP server. `add_episode(...)`,
`search(...)`, `delete_entity_edge(...)`. Async-first.

**Self-host & pricing.** Free, Apache-2.0. You operate Neo4j (or pick a
lighter backend like Kuzu — embedded, no separate process — which is the
likely solo-operator pick).

**Known issues / gaps.** LLM-on-write means ingestion costs scale with
volume; no decay means the graph grows unbounded; you build the surrounding
service yourself. No first-class procedural-memory model.

---

## mnemostack

- Repo: https://github.com/udjin-labs/mnemostack (Apache-2.0)
- Status: **alpha** ("API may change between 0.1.x releases").
- Last activity: ~April 2026 (recent commits per repo metadata).

**What it is.** Hybrid memory stack for AI agents. Tagline: "Vector + BM25 +
Knowledge Graph + Temporal, RRF retrieval, 8-stage recall pipeline." Small
project (single-digit stars at time of scan) — currency is high but
maturity is low.

**Architecture.** Python (~99%). **Qdrant** (required) for vectors,
**Memgraph** (optional) for the knowledge graph, in-memory or external BM25,
state persistence via JSON file or Redis-compatible `StateStore`. Retrieval
fuses the four sources via Reciprocal Rank Fusion, then runs an 8-stage
pipeline: query classification, exact-token rescue, gravity dampening,
reranking, etc.

**Memory taxonomy.** Does not separate episodic / semantic / procedural;
all stored as facts with metadata.

**Temporal versioning.** Yes — facts carry `valid_from` / `valid_until`,
described as "bitemporal in spirit". Point-in-time recall ("who was alice
working on in March?") demonstrated. Less mature than Graphiti's model
but the same conceptual shape.

**Forgetting.** No TTL/decay primitive documented; a "consolidation runtime"
is mentioned but not detailed.

**Human-in-loop fact mgmt.** Not surfaced. API focuses on `Ingestor.ingest`
and `Recaller.recall`; no documented delete/correct endpoints. **This is
the biggest gap relative to Donna's needs.**

**API shape.** `Ingestor(batch_size=64).ingest([IngestItem(...)])` (idempotent,
UUID5 dedup); `Recaller.recall(query, limit=10)`.

**Self-host & pricing.** Fully self-hostable, Docker Compose for Qdrant +
Memgraph. Free, Apache-2.0. No managed offering.

**Known issues / gaps.** Alpha-stage; no community of operators; author
publishes a private "17k-point memory stack" benchmark but no third-party
validation. Not safe to depend on without a fork plan.

---

## Cross-cutting observations

- **Procedural memory is under-served.** Only Mem0 explicitly names it; Letta
  approximates with persona/sleep-time rewrites; Zep/Graphiti and mnemostack
  ignore it. For Donna's "how the operator works" tier this is a real gap.
- **Bitemporal vs agent-rewrite is the central design split.**
  Zep/Graphiti/mnemostack store time as a property of facts (queryable);
  Letta/Mem0 rely on the agent to overwrite. Donna's tenets demand the
  former.
- **Forgetting is mostly hand-waved.** Mem0 mentions decay; nobody else
  ships an inspectable forgetting policy. Donna will likely need to define
  its own (confidence-weighted TTL? operator-pinned vs agent-derived?).
- **Self-host viability ranking (solo-operator):**
  Letta > Mem0 > Graphiti > mnemostack >> Zep. Zep cloud-only excludes it
  from Donna's design center.

## Scope gaps I couldn't resolve

- Mem0's exact decay function (curve, half-life, manual override) is not
  documented in primary sources I could fetch.
- Letta's behavior under conflicting rewrites (race between user edit and
  agent edit, or between primary agent and sleep-time agent) is not
  documented; the docs assume a single writer at a time.
- Graphiti's storage cost vs query cost trade-off across the four supported
  backends (Neo4j/Falkor/Kuzu/Neptune) is not benchmarked publicly; Kuzu
  appears to be the solo-operator-friendly choice but I couldn't find
  comparative numbers.
- mnemostack: production users, real release cadence, and durability of
  the project (single-author alpha) — couldn't establish from the repo
  alone.
- Zep Cloud pricing: credit-based, but no flat per-month tier I could find
  for solo-operator scale.
- Letta Cloud pricing: officially TBD as of last public statement.
