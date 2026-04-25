# Graph-Augmented RAG Systems — digest

## Per-product table

| product | one-line | arch (lang/store/llm/tool/state) | pricing | self-host | notable | source |
|---|---|---|---|---|---|---|
| Microsoft GraphRAG | KG + hierarchical community summaries pipeline for global/local/drift search | Python; parquet on disk + optional vector store; OpenAI-compatible LLM; `graphrag index`/`update` CLI; Leiden communities | OSS MIT; LLM cost is the spend | Yes (local) | LazyGraphRAG claims ~1/700 query cost; full mode cost trap; incremental from v0.5.0 | https://github.com/microsoft/graphrag |
| LightRAG (HKU) | Lighter dual-level (entity + graph) graph RAG | Python; Neo4j/Postgres/Mongo/OpenSearch/JSON-KV; recommends 32B+ LLM; iterative indexing; delete + auto-regen | OSS MIT | Yes | RAG-Anything multimodal add-on; HippoRAG 2 contests its benchmarks | https://github.com/HKUDS/LightRAG |
| HippoRAG 2 | Neuro-inspired retrieval with OpenIE + Personalized PageRank | Python; in-process graph (bespoke); LLM/vLLM OpenIE; configurable embedder; explicit incremental + delete | OSS MIT | Yes | ICML 2025 paper; beats GraphRAG/LightRAG/RAPTOR on multi-hop benchmarks | https://github.com/OSU-NLP-Group/HippoRAG |
| Cognee | "AI memory engine": graph+vector hybrid with add/cognify/memify/forget | Python; Kùzu embedded default (also Neo4j/FalkorDB/Memgraph/Neptune); LanceDB/Qdrant/Weaviate/pgvector/Redis vectors; Pydantic ontology; Ollama-friendly | OSS Apache-2.0; managed cloud optional | Yes | `temporal_cognify` event graphs; published Graphiti integration acknowledging Graphiti's better bitemporal model | https://github.com/topoteretes/cognee |
| Neo4j GraphRAG (Python) | Neo4j's first-party GraphRAG toolkit | Python; Neo4j only graph store; Neo4j/Weaviate/Pinecone/Qdrant vectors; SimpleKGPipeline + retriever family (Vector, Hybrid, Text2Cypher); upserts | OSS Apache-2.0; Neo4j CE free, AuraDB managed | Yes (Neo4j req'd) | No built-in community detection; ms-graphrag-neo4j sister project fills that | https://github.com/neo4j/neo4j-graphrag-python |
| LlamaIndex PropertyGraphIndex | Modular labelled-property-graph index w/ pluggable extractors+retrievers | Python; SimplePropertyGraphStore/Neo4j/Memgraph/Nebula/Kùzu/FalkorDB; multiple LLM extractors (Simple/Schema/Dynamic); upsert by doc_id; `refresh()` re-extracts changed | OSS MIT | Yes | Framework not algorithm; quality depends on extractor+retriever combo | https://developers.llamaindex.ai/python/framework/module_guides/indexing/lpg_index_guide/ |

## Three patterns to steal

1. (a) Embedded graph store as default backend so the operator doesn't run a DB process. (b) Cognee (Kùzu embedded), LightRAG (JSON-KV/in-memory), LlamaIndex (SimplePropertyGraphStore), HippoRAG 2 (in-process). (c) Matches Donna's "operator owns the data store" tenet and solo-operator ergonomics — no Neo4j ops surface to babysit. (d) https://github.com/topoteretes/cognee
2. (a) First-class incremental updates via upsert-by-doc-id with re-extract-only-changed semantics (`refresh()` / `incremental_loading=True`). (b) LlamaIndex PropertyGraphIndex, Cognee, LightRAG, HippoRAG 2. (c) Donna's memory is mutating personal corpora; one-shot indexing (Microsoft GraphRAG full mode) is a non-starter. Donna needs the upsert-and-prune model. (d) https://www.llamaindex.ai/blog/introducing-the-property-graph-index-a-powerful-new-way-to-build-knowledge-graphs-with-llms
3. (a) Event-tagged temporal graph with time-aware query parsing ("last week", "in 2023") that filters graph events. (b) Cognee's `temporal_cognify`. (c) Donna's temporal-versioning tenet needs at minimum this; Cognee's own Graphiti blog flags the next step (true bitemporal). Steal the event-edge shape now, plan the bitemporal upgrade. (d) https://docs.cognee.ai/guides/time-awareness

## Three patterns to avoid

1. (a) One-shot whole-corpus community summarization where every incremental add re-touches communities. (b) Microsoft GraphRAG full mode. (c) Documented as the canonical cost blowup; LazyGraphRAG was created specifically to fix it but isn't the OSS default. (d) https://www.microsoft.com/en-us/research/blog/lazygraphrag-setting-a-new-standard-for-quality-and-cost/

(Two further candidate anti-patterns — heuristic entity dedup in Cognee (Issue #1831) and LightRAG's 32B+ extraction-model floor — are noted in the raw file but lack a dedicated post-mortem URL, so per the rule they are dropped.)

## Cross-cutting observations

- None of the six implements true bitemporal fact storage (valid-time × transaction-time, invalidation not overwrite); Cognee is closest and explicitly defers to Graphiti.
- HippoRAG 2 has the most rigorous third-party-style eval (MuSiQue/2Wiki/HotpotQA/LV-Eval/NQ/PopQA/NarrativeQA); LightRAG's earlier benchmarks are now contested.
- Cheapest laptop runs: LightRAG, Cognee (embedded Kùzu), HippoRAG 2. Microsoft GraphRAG full is the cost trap.
- Provenance is uniformly chunk-level; no system surfaces claim-level confidence/bias/retraction — Donna's validation-surface tenet is unmet category-wide.
- Neo4j GraphRAG and LlamaIndex are libraries, not memory products; they need composition for community summaries and temporal facts.

## Unresolved

- Microsoft GraphRAG cost-per-million-tokens on a 1k-doc personal corpus — no controlled 2026 benchmark located; matters for Donna's budget model.
- Whether LazyGraphRAG is exposed in OSS `microsoft/graphrag` v3.0.x CLI vs. Azure-only — determines if Donna can use the cheap path without Azure.
- Neo4j Inc. official support status of community detection (only via `neo4j-contrib/ms-graphrag-neo4j`) — affects production reliance.
- HippoRAG 2 graph-store internals (dict vs. NetworkX vs. custom) undocumented; matters for concurrent-write productionization.
- Claim-level provenance (confidence, source bias, retraction flags) absent across all six — directly blocks Donna's validation surface.
- Cognee third-party benchmarks unavailable; only vendor-run comparisons exist.
