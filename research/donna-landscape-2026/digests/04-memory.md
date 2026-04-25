# Agent Memory Systems — digest

## Per-product table

| product | one-line | arch (lang/store/llm/tool/state) | pricing | self-host | notable | source |
|---|---|---|---|---|---|---|
| Letta (MemGPT) | LLM-as-OS stateful agent; self-edits memory via tools | Python; Postgres+pgvector; LLM agent-driven; REST/Py/TS SDK + ADE; 3-tier core/recall/archival blocks | OSS Apache-2.0; Cloud TBD | Yes (Docker / `pip install letta`) | Sleep-time consolidation agents; no bitemporal model; v1 rearch late-2025 | https://github.com/letta-ai/letta |
| Mem0 | Memory-as-a-service layer for agents | Python+TS; 19 vector stores (Qdrant/pgvector/…) + Neo4j/Memgraph optional; LLM extraction; REST/MCP; history DB | OSS Apache-2.0; hosted SaaS paid tiers | Yes (Docker Compose) | Only product to explicitly name episodic/semantic/procedural/associative; documented decay | https://github.com/mem0ai/mem0 |
| Zep | Managed agent-memory service over Graphiti | Python+Go; Graphiti backend; semantic+BM25+graph, no LLM in hot path; cloud dashboard/API | Cloud credit-based; CE deprecated | No (CE deprecated Feb 2026) | Bitemporal; DMR 94.8% vs MemGPT 93.4%; 90% lower latency | https://arxiv.org/abs/2501.13956 |
| Graphiti | Open-source temporal knowledge-graph engine | Python on Claude Agent SDK; Neo4j/FalkorDB/Kuzu/Neptune; BM25 in-proc/OpenSearch; LLM at write; Py SDK+FastAPI+MCP | Free Apache-2.0 | Yes | Bitemporal `valid_from`/`valid_until`; episode/entity/fact nodes; async ingestion | https://github.com/getzep/graphiti |
| mnemostack | Hybrid Vector+BM25+KG+temporal stack, RRF, 8-stage recall | Python; Qdrant required, Memgraph optional; JSON/Redis StateStore; `Ingestor`/`Recaller` API | Free Apache-2.0 | Yes (Docker Compose) | Alpha; bitemporal-in-spirit; no documented delete/correct API | https://github.com/udjin-labs/mnemostack |

## Three patterns to steal

1. **Bitemporal fact edges with invalidation, not deletion.** (a) Every fact carries event-time and ingestion-time; superseded facts are flagged invalid and stay queryable. (b) Zep, Graphiti, mnemostack. (c) Donna's tenets explicitly require knowing *when* facts changed and supporting validation drill-down — bitemporal edges are the exact substrate. (d) https://arxiv.org/abs/2501.13956
2. **Explicit memory-type taxonomy (episodic/semantic/procedural/associative).** (a) Name and store memory types separately rather than as undifferentiated text. (b) Mem0. (c) Donna's "memory is first-class" tenet calls out all three tiers; Mem0's taxonomy maps directly. (d) https://docs.mem0.ai/core-concepts/memory-types
3. **Direct CRUD over memory blocks for human-in-loop correction.** (a) Expose REST endpoints for edit/delete/overwrite of individual memory units, with a history DB tracking changes. (b) Letta (memory blocks), Mem0 (`DELETE /delete`, history DB). (c) Donna's validation surface and operator fact-correction depend on this; mnemostack's omission is flagged as the biggest gap. (d) https://docs.letta.com/guides/core-concepts/memory/memory-blocks/

## Three patterns to avoid

1. **Cloud-only pivot that strands self-hosters.** (a) Deprecating the OSS edition and forcing users onto a credit-based cloud. (b) Zep Community Edition. (c) Donna is solo-operator and self-host-default; vendor-cloud lock-in is disqualifying. (d) https://blog.getzep.com/announcing-a-new-direction-for-zeps-open-source-strategy/

(Only one pattern-to-avoid has a cited post-mortem URL in the raw file; per the rules, the others are dropped.)

## Cross-cutting observations

- Procedural memory is under-served — only Mem0 explicitly names it; Letta approximates via persona/sleep-time; Zep/Graphiti/mnemostack ignore it.
- Central design split: **bitemporal storage** (Zep/Graphiti/mnemostack) vs **agent-rewrite** (Letta/Mem0). Donna's tenets demand the former.
- Forgetting is hand-waved across the category. Only Mem0 mentions decay; nobody ships an inspectable forgetting policy.
- Self-host viability ranking for solo-operators: Letta > Mem0 > Graphiti > mnemostack >> Zep.
- LLM-on-write (Graphiti, Mem0 extraction) makes ingestion costs scale with volume; combined with no-decay this means unbounded graph growth.

## Unresolved

- **Mem0 decay function** (curve/half-life/manual override) not in primary docs — matters because Donna will need an inspectable forgetting policy and Mem0 is the only prior art.
- **Letta conflicting-rewrite behavior** (user vs agent vs sleep-time agent races) undocumented — matters for human-in-loop fact correction safety.
- **Graphiti backend cost trade-offs** (Neo4j/Falkor/Kuzu/Neptune) not benchmarked publicly — Kuzu looks solo-operator-friendly but unverified.
- **mnemostack durability** (single-author alpha, no production users, no third-party benchmark validation) — can't depend on it without a fork plan.
- **Zep Cloud pricing** (no flat per-month tier visible) — blocks solo-operator sizing even as a foil.
- **Letta Cloud pricing** officially TBD — same.
- **mnemostack human-in-loop fact mgmt** absent from API surface — flagged in raw as biggest gap relative to Donna's needs.
