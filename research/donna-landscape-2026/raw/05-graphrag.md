# Graph-Augmented RAG Systems — Landscape (April 2026)

Research target: candidates for Donna's retrieval layer (or design inspiration).
Donna needs: solo-operator self-hostable, incremental updates, temporal
versioning of facts, claim-level provenance.

## Microsoft GraphRAG

- Primary source: https://github.com/microsoft/graphrag (v3.0.9, Apr 13 2026, MIT)
- Project page: https://www.microsoft.com/en-us/research/project/graphrag/
- LazyGraphRAG: https://www.microsoft.com/en-us/research/blog/lazygraphrag-setting-a-new-standard-for-quality-and-cost/
- What it is: a Python pipeline that builds a knowledge graph + hierarchical
  community summaries from unstructured docs, then answers queries via
  local (entity-neighborhood), global (community-summary map-reduce), drift,
  or basic search.
- Architecture: Python, default storage is parquet files on disk (not a
  graph DB) with optional vector store; LLM-based entity/relation extraction
  via prompts; community detection via Leiden; one-shot indexing with
  `graphrag index`, plus a `graphrag update`/append path that "tries to
  minimize community recomputes" (Discussion #511, Issue #741). Incremental
  support landed v0.5.0 via consistent entity IDs.
- Quality vs. evidence: original paper claims wins on global "sense-making"
  questions vs. naive RAG; LazyGraphRAG (Nov 2024 blog, GA'd into Azure
  Local 2025) claims indexing parity with vector RAG and ~1/700 of full
  GraphRAG's query cost while matching quality.
- Self-host: yes; runs locally against any OpenAI-compatible LLM. But
  README explicitly warns "indexing can be an expensive operation."
- Solo-operator viability: full GraphRAG is the canonical cost blowup
  (community summarization is O(graph) LLM calls). LazyGraphRAG fixes the
  cost story but hasn't fully replaced full GraphRAG in the OSS repo.
- Known issues: token cost (Medium "Cutting GraphRAG token costs by 90%",
  Mar 2026), incremental adds re-touch communities, no first-class temporal
  versioning of facts.
- Scope gaps: no temporal/bitemporal model; no claim-level provenance
  beyond chunk pointers; not designed for personal corpora that mutate.

## LightRAG (HKU)

- Primary source: https://github.com/HKUDS/LightRAG (v1.4.15, Apr 19 2026, MIT)
- Paper: https://arxiv.org/abs/2410.05779 (EMNLP 2025)
- What it is: a lighter-weight graph-augmented RAG that does dual-level
  (low: entity/relation match; high: graph-based ranking) retrieval over
  an LLM-extracted knowledge graph.
- Architecture: Python; storage backends include Neo4j, Postgres, MongoDB,
  OpenSearch (Mar 2026), and JSON-KV/in-memory. LLM-based entity & relation
  extraction (recommends 32B+ model, 32K context). Indexing is iterative;
  supports document delete with auto-graph regeneration and incremental
  insert. RAG-Anything (Jun 2025) adds multimodal ingestion (PDF, images,
  tables, formulas).
- Quality vs. evidence: paper reports 49.6%-84.8% gains over NaiveRAG,
  RQ-RAG, HyDE, and (early) GraphRAG across agriculture/CS/legal/mixed
  datasets. HippoRAG 2 paper (arXiv 2502.14802) reports HippoRAG 2 beats
  LightRAG on multi-hop benchmarks.
- Self-host: yes; pure Python, drop-in storage.
- Solo-operator viability: strong — easiest GraphRAG to actually run on a
  laptop with a local backend.
- Known issues: LLM extraction quality bound by the 32B+ recommendation;
  no native temporal versioning; entity dedup is heuristic.
- Scope gaps: no bitemporal facts, no claim-level provenance metadata
  beyond source-chunk linkage.

## HippoRAG 2

- Primary sources: https://github.com/OSU-NLP-Group/HippoRAG (v1.0.0,
  Feb 27 2025, MIT); https://arxiv.org/abs/2502.14802
  ("From RAG to Memory: Non-Parametric Continual Learning for LLMs",
  ICML 2025)
- What it is: neurobiologically-inspired retrieval framework — LLM as
  neocortex, parahippocampal encoder, and an open KG built via OpenIE.
  Online queries embed → match triples → Personalized PageRank for
  context-aware selection, with a recognition-memory filter step.
- Architecture: Python, OpenIE (LLM- or vLLM-driven) for triple
  extraction; graph stored in-process (not a managed DB); embeddings via
  configurable model (NV-Embed-v2, GritLM-7B, etc.); incremental updates
  and document deletion are explicit test cases in the repo.
- Quality vs. evidence: paper reports +7% over best embedding models on
  associativity benchmarks (MuSiQue, 2Wiki, HotpotQA, LV-Eval) without
  regressing simple-fact (NQ, PopQA) or sense-making (NarrativeQA). Beats
  RAPTOR, GraphRAG, LightRAG. Cost claim: "significantly fewer resources
  for offline indexing compared to GraphRAG/RAPTOR/LightRAG."
- Self-host: yes; pip install, point at OpenAI or vLLM.
- Solo-operator viability: strong on quality-per-dollar; thin ops story
  (no managed graph DB, single process).
- Known issues: graph store is bespoke; productionizing concurrent writes
  is on the user; no temporal/bitemporal model.
- Scope gaps: explicitly a retrieval research framework, not a memory
  service; no provenance UI, no claim versioning.

## Cognee

- Primary sources: https://github.com/topoteretes/cognee (v1.0.3,
  Apr 24 2026, Apache-2.0); https://docs.cognee.ai/guides/time-awareness;
  https://www.cognee.ai/
- What it is: an "AI memory engine" — pipeline that turns docs into a
  graph + vector hybrid, with `add` / `cognify` / `search` / `memify` /
  `forget` operations plus optional ontology grounding (Pydantic).
- Architecture: Python (3.10–3.13). Default graph store is Kùzu
  (embedded, file-based, ACID, Cypher); also supports Neo4j, FalkorDB,
  Memgraph, Amazon Neptune, NetworkX (non-Kùzu adapters live in
  cognee-community repo). Vector backends include LanceDB, Qdrant,
  Weaviate, pgvector, Redis. LLM-based entity/relation extraction with
  optional ontology validation. `cognify()` defaults
  `incremental_loading=True`. `memify()` prunes stale nodes and reweights
  edges as new data arrives.
- Temporal: `temporal_cognify=True` produces an event-based graph with
  timestamps/intervals and explicit before/after/during edges; time-aware
  search parses "last week" / "in 2023" and filters graph events.
  Notably, Cognee published a Graphiti integration
  (cognee.ai/blog/.../cognee-graphiti-integrating-temporal-aware-graphs)
  acknowledging Graphiti's bitemporal model is more rigorous.
- Quality vs. evidence: blog claims 0.93 on HotPotQA multi-hop; vendor's
  own AI-Memory eval (Aug 2025) compares Cognee to LightRAG, Graphiti,
  Mem0 favorably (vendor-run — treat with caution).
- Self-host: yes; pip install or Docker; runs against Ollama for fully
  local. Managed cloud offering exists but optional.
- Solo-operator viability: strong — Kùzu default means no separate DB
  process; closest in spirit to Donna's "operator owns the data store."
- Known issues: dedup behavior is heuristic (Issue #1831); ontology
  enforcement is opt-in; vendor benchmarks are not third-party; temporal
  model is event-tagging, not full bitemporal (no separate transaction-
  time / valid-time per fact).
- Scope gaps: not a full bitemporal store; provenance is chunk-level, not
  claim-level with confidence labels.

## Neo4j GraphRAG (neo4j-graphrag-python)

- Primary sources: https://github.com/neo4j/neo4j-graphrag-python
  (v1.15.0, Apr 23 2026, Apache-2.0);
  https://neo4j.com/docs/neo4j-graphrag-python/current/
- What it is: Neo4j's first-party Python toolkit for building GraphRAG
  apps against a Neo4j database — KG builder pipeline + a family of
  retrievers.
- Architecture: Python; graph store is Neo4j (only). Optional vector
  stores: Neo4j vector index, Weaviate, Pinecone, Qdrant. KG construction
  via `SimpleKGPipeline` (LLM-based extraction with configurable allowed
  node/relationship/pattern schema) or the lower-level `Pipeline` class.
  Retrievers: `VectorRetriever`, `VectorCypherRetriever`,
  `HybridRetriever`, `HybridCypherRetriever`, `Text2CypherRetriever`,
  plus retriever wrappers for the external vector DBs. Inserts are
  upserts; incremental adds are first-class (you simply re-run the
  pipeline on new docs).
- Quality vs. evidence: no published end-to-end benchmark from Neo4j
  itself; vendor positions it as the production-grade alternative to
  Microsoft GraphRAG. The community sister project
  https://github.com/neo4j-contrib/ms-graphrag-neo4j re-implements
  Microsoft's Leiden-based community summarization on top of it for
  global queries.
- Self-host: yes — needs Neo4j (Community Edition is free; AuraDB is
  managed). Single-user runs fine on a laptop with Neo4j Desktop.
- Solo-operator viability: medium — you take on the Neo4j ops surface,
  but get mature graph tooling. Not as turnkey as Cognee/LightRAG
  embedded backends.
- Known issues: no built-in community detection / global summarization
  in the core package (you compose it yourself or use ms-graphrag-neo4j);
  no temporal versioning out of the box (Neo4j supports temporal
  properties but the package doesn't model fact-history).
- Scope gaps: not opinionated about memory or temporal facts — it's a
  retrieval library, not a memory product.

## LlamaIndex PropertyGraphIndex

- Primary sources:
  https://developers.llamaindex.ai/python/framework/module_guides/indexing/lpg_index_guide/
  ; https://www.llamaindex.ai/blog/introducing-the-property-graph-index-a-powerful-new-way-to-build-knowledge-graphs-with-llms
  ; source: https://github.com/run-llama/llama_index (MIT)
- What it is: LlamaIndex's labelled-property-graph index — modular
  knowledge-graph layer with pluggable extractors and retrievers.
- Architecture: Python; pluggable graph stores — `SimplePropertyGraphStore`
  (in-memory), Neo4j, Memgraph, Nebula, Kùzu, FalkorDB, plus others.
  Extractors: `SimpleLLMPathExtractor`, `SchemaLLMPathExtractor`
  (Pydantic-validated), `DynamicLLMPathExtractor`,
  `ImplicitPathExtractor`. Retrievers: `LLMSynonymRetriever`,
  `VectorContextRetriever`, `TextToCypherRetriever`,
  `CypherTemplateRetriever`, custom retrievers; multiple retrievers can
  be composed. Insert/upsert are first-class — `index.insert(Document)`
  and `index.insert_nodes(new_nodes)` are upserts on `doc_id`;
  `refresh()` re-extracts only changed docs.
- Quality vs. evidence: no end-to-end benchmark from LlamaIndex itself;
  positioned as a framework, not a single retrieval algorithm. Quality
  depends on chosen extractor + retriever combo.
- Self-host: yes — purely a library; bring your own LLM and graph store.
- Solo-operator viability: strong if you already use LlamaIndex; you can
  start with `SimplePropertyGraphStore` (in-memory) and graduate to
  Neo4j/Kùzu without code changes.
- Known issues: no built-in community detection / Microsoft-style global
  summarization (you'd compose it); no temporal versioning of facts;
  retrieval quality is a tuning exercise (extractor and retriever choice
  matter).
- Scope gaps: not a memory product; no bitemporal model; no provenance
  beyond doc/node IDs.

## Cross-cutting findings (for Donna)

- Cheapest to run on a personal corpus: **LightRAG** or **Cognee** with
  embedded backends (JSON-KV / Kùzu); both can run end-to-end on a
  laptop with a local LLM. **HippoRAG 2** is also lean (no managed DB).
  Microsoft GraphRAG (full mode) is the canonical cost trap; LazyGraphRAG
  fixes that but is integrated mainly into Azure Local, not the OSS
  pipeline.
- Best incrementality: **Cognee** (`incremental_loading=True` default,
  `memify` reweights), **LlamaIndex PropertyGraphIndex** (upsert by
  doc_id, `refresh()`), **LightRAG** (delete + auto-regen), **HippoRAG 2**
  (explicit incremental tests). Microsoft GraphRAG's `append`/update path
  works but recomputes communities on touched subgraphs and is the
  weakest of the six on smooth incrementality.
- Strongest retrieval-quality claims: **HippoRAG 2** has the most
  rigorous third-party-style evaluation (ICML 2025 paper, multi-benchmark
  including MuSiQue, 2Wiki, HotpotQA, LV-Eval, NQ, PopQA, NarrativeQA),
  beating LightRAG, GraphRAG, RAPTOR. **Microsoft GraphRAG** has the
  strongest claim on global "sense-making" questions specifically.
  **LightRAG** has good benchmarks but they're now contested by HippoRAG
  2 results.
- Temporal versioning of facts: **none of the six** implements true
  bitemporal fact storage (valid-time × transaction-time per fact, with
  invalidation rather than overwrite). Closest is **Cognee** with
  `temporal_cognify` (event-graph with timestamp edges and time-aware
  search) — but Cognee themselves blogged about integrating Graphiti
  precisely because Graphiti has a more complete bitemporal model.
  Donna's bitemporal-fact requirement is genuinely an open scope across
  this category and likely needs Graphiti, Zep, or a custom layer on
  top of one of these graphs.

## Scope gaps I couldn't resolve

- Exact cost-per-million-tokens numbers for Microsoft GraphRAG indexing
  on a representative personal corpus (e.g., 1k documents) — published
  numbers vary wildly with chunk size and community depth, and I did not
  find a controlled 2026 benchmark.
- LazyGraphRAG availability in the OSS `microsoft/graphrag` repo vs.
  Azure-only — the Microsoft Research blog and Stack article describe
  the algorithm and Azure integration, but I could not confirm from the
  repo whether `lazy` mode is exposed in the v3.0.x CLI.
- Neo4j GraphRAG community-detection support: the official package does
  not appear to ship Leiden/community-summary helpers; the
  `neo4j-contrib/ms-graphrag-neo4j` repo fills that gap, but I could not
  confirm whether either is officially supported by Neo4j Inc.
- HippoRAG 2 graph store internals (in-memory dict vs. NetworkX vs.
  custom) — repo describes the algorithm but not the storage layer in
  the docs I fetched; would need to read the source.
- Whether any of these provide claim-level provenance metadata
  (confidence, source bias, retraction flags) — none surfaced in the
  primary sources; Donna's "validation surface" tenet is unmet here.
- Cognee's third-party benchmarks — only vendor-published numbers are
  available; independent reproductions were not located.
