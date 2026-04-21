# Corpus — Session Bootstrap Brief

**This is the mission brief for a new Claude Code session tasked with building "Corpus" — a corpus interpretation engine. Paste this entire file as the opening context of that session, or reference it via its path.**

Corpus is an internal Python package that lives inside the existing `GlobalCan/donna` monorepo alongside the agent runtime. Same repo, same deployable process, same database file — but a hard internal boundary, separate schema namespace (`corpus_*` tables), separate migrations folder, separate public API, separate test suite, separate eval harness. Donna imports from Corpus; Corpus never imports from Donna.

Why monorepo: single maintainer, single deployment target, one-process product. Multi-repo splits at this stage would be premature generalization. Codex explicitly recommended this structure.

---

## 0 · How to use this brief

You (the agent reading this) are a session operating inside the existing Donna repository at `C:\Users\rchan\OneDrive\Desktop\donna` (remote: `GlobalCan/donna`). Your job is to add a new `corpus/` package alongside `donna/`.

Read in this order before writing any code:

1. This whole file.
2. `docs/PLAN.md` — Donna's architectural plan.
3. `docs/KNOWN_ISSUES.md` — two Codex adversarial reviews absorbed, plus the "v1.1 — Hermes Agent adversarial comparison" section that motivated this extraction.
4. `docs/OPERATIONS.md` — production ops.
5. `docs/review.html` — interactive adversarial review of Donna.
6. `src/donna/modes/retrieval.py` — current hybrid retrieval (you're porting this).
7. `src/donna/memory/knowledge.py` — current knowledge/chunk primitives.
8. `src/donna/security/validator.py` — grounded-mode citation validator (moves to Corpus).
9. `src/donna/security/sanitize.py` — untrusted-content dual-call (moves to Corpus).
10. `src/donna/ingest/{chunk.py,embed.py,pipeline.py}` — ingestion (moves to Corpus).
11. `src/donna/modes/{grounded.py,speculative.py,debate.py}` — mode direct-call APIs (their retrieval primitives move; orchestration stays in Donna).

Then come back here for the mission.

---

## 1 · Who this is for and what they actually want

**User:** Solo maintainer. Security-conscious, architecture-fluent, iteration-heavy. Not building a SaaS. Building a personal thinking partner.

**The core product thesis — learn this by heart:**

The user does NOT want a scholar ("what did Michael Lewis say about X").
The user DOES want an oracle ("what would Michael Lewis say about X").

They also want cross-author synthesis — "where do Lewis and Dalio overlap on X, and where do they use the same words to mean different things?"

Both require structured interpretation artifacts — worldview pillars, recurring preoccupations, canonicalized concepts, argumentative moves — not just chunks of text retrieved by cosine similarity. **This is the hard, interesting, distinctive thing about the project.** Corpus is not a generic RAG system. If it ends up looking like a generic RAG system, you've failed.

Real use cases (not hypotheticals):

- "What would Michael Lewis think about AI coding assistants?"
- "Based on Taleb's writings, how should I think about long-tail risk?"
- "Where do Lewis and Dalio agree about humility?"
- "Where does Dalio operationalize something Lewis moralizes?"
- "Early Lewis vs late Lewis — how has his view of Wall Street changed?"
- Putting distinct authors in dialog over the user's own drafts to sharpen thinking.

---

## 2 · The critical reframe — Corpus is NOT a memory system

From Codex (GPT-5.4) session `019db08b-9636-7d83-90bd-7ef5e477770d`:

> **Corpus is a "corpus interpretation engine," not a memory system.** Memory is about facts the agent accumulates from use. Corpus interpretation is about extracting, canonicalizing, distilling, and synthesizing the structured content of a body of work. Same tool types (vector DBs, graph, LLM) but fundamentally different problem shape.

Memory systems (Mem0, Letta, Zep/Graphiti) store facts the agent learns during interaction. Corpus stores interpretations of external bodies of work the user curates. Don't conflate. Donna already has a `facts` table for memory; Corpus is something else entirely.

**Corpus answers:**
- What does this corpus contain?
- What concepts recur?
- What pillars of thought hold across works?
- What claims support a synthesis?
- What tensions exist across authors?
- What evidence justifies this generated answer?

**Donna answers:**
- Who is talking?
- What permissions exist?
- What tools may execute?
- How do we recover after restart?
- How do we trace, alert, bill?

Two different problems. Two different lifecycles. Two different failure modes. One repo, two packages, clean boundary.

---

## 3 · Name-is-the-concept: a note

"corpus" is both the project name and the root data concept. Disambiguate by context:
- **Project/package:** `corpus` (lowercase, e.g. `from corpus import Corpus`)
- **Schema prefixes:** `corpus_chunks`, `corpus_pillars`, etc.
- **Data model:** "this author's corpus of work" — the concept rooted at the `corpus` table.

Project vs. concept never actually clashes in practice.

---

## 4 · The architectural primitive — attributed knowledge graph, NOT persona-scoped silos

Codex pushed back on the obvious modeling choice. Do NOT model `scope = persona` as the root. Model:

```
corpus                           (root — "my whole library")
 └── source                      (a book, article, interview, transcript)
      └── work                   (groups of sources — "The Big Short" vs "Flash Boys")
           └── chunk             (the evidence substrate — 500-ish tokens)
                │
                ├── author        (attribution)
                ├── publication_date  (temporal)
                ├── entities extracted  (people, orgs, works, concepts)
                └── claims extracted

concepts                         (cross-corpus namespace)
 ├── concept_aliases              (Lewis's "outsider-insight" ≈ Dalio's "outside perspective")
 ├── concept_mentions             (chunk → concept w/ salience)
 └── concept_edges                (co-occurrence, contrasts_with, broader_than, ...)

worldview_pillars                (per-author thematic distillations)
 ├── pillar_evidence              (supporting + disconfirming chunks)
 └── pillar_version               (corpus changes, pillars regenerate)

cross_corpus_alignments          (typed relationships between concepts in different profiles)
 │  (same_as, close_to, broader_than, narrower_than, contrasts_with,
 │   uses_different_frame_for)

interpretation_profiles          (saved filter views — THIS is "persona")
 │  profile("late_lewis") = author=Lewis AND publication_date>=2015
 │  profile("lewis_full") = author=Lewis
 │  profile("investors")  = author IN (Lewis, Dalio, Buffett) AND topic=markets
```

A **persona is a view over attributed knowledge, not a root object.** This unlocks:
- Temporal personas ("early Lewis")
- Multi-author composite personas ("investors who write about incentives")
- Single-author filtered personas ("Lewis on Wall Street specifically")

It's also the only schema that answers cross-author questions naturally. Donna v1 currently models `agent_scope` as the root — that's the wrong primitive. Corpus fixes it.

---

## 5 · The Corpus ↔ Donna integration contract

Corpus is an **internal Python package** that Donna imports directly. Same repo, same process, same SQLite file. No HTTP boundary, no separate deployment.

The contract — load-bearing:

**Corpus returns structured `EvidencePack` objects, NOT final prose.**

```python
from corpus import Corpus

c = Corpus.open("./data/donna.db")   # same db file, corpus_* tables

pack = c.answer(
    profile="lewis",                  # interpretation profile id
    question="What would Lewis think about AI coding assistants?",
    mode="oracle",                    # oracle | grounded | overlap | debate_prep
    max_chunks=8,
    temporal_hint=None,               # or "recent" | "early" | "evolution"
)

# pack contains:
#   pack.chunks: [Chunk(id, content, citation, score), ...]        evidence substrate
#   pack.pillars: [Pillar(name, summary, evidence_chunks), ...]    worldview shape
#   pack.concepts: [Concept(name, relevance, neighbors), ...]      graph context
#   pack.style_anchors: [Chunk(...)]                               voice calibration
#   pack.argumentative_moves: [Move(pattern, examples), ...]       reasoning habits
#   pack.confidence: {retrieval: 0.0-1.0, pillar_coverage: 0.0-1.0}
#   pack.attributions: [{claim, source}]                           provenance chain
#   pack.refusal_reason: str | None                                if below threshold
```

**Donna composes the final response** using the pack. That means:
- Corpus does NOT know about Discord or any chat surface
- Corpus does NOT own the LLM call that produces user-facing prose
- Corpus does NOT handle consent or taint propagation (Donna's concerns)
- Corpus DOES everything up to "structured context ready for final composition"

This prevents Donna from becoming a thin shell over Corpus and keeps voice/consent/interaction responsibility with the agent runtime.

Corpus DOES call LLMs internally — for entity extraction, canonicalization, pillar distillation, post-gen validation. Those are "curation-time" LLM calls, not "query-time response generation." Different concerns.

### Schema ownership rule

Strict: **Corpus owns every `corpus_*` table. Donna owns everything else.** No cross-writing ever. Donna reads Corpus only via `from corpus import ...` — never via SQL.

### Directory layout

```
GlobalCan/donna/
├── src/
│   ├── donna/                    (existing agent runtime — unchanged except imports)
│   └── corpus/                   (NEW — corpus interpretation engine)
│       ├── __init__.py
│       ├── api.py                (public Corpus class + EvidencePack)
│       ├── types.py              (Chunk, Pillar, Concept, Alignment, Profile dataclasses)
│       ├── db.py                 (connection, pragmas — shares SQLite file with Donna)
│       ├── ingest/
│       │   ├── chunk.py          (ported from donna/ingest/chunk.py)
│       │   ├── embed.py          (Voyage-3 via HTTP, ported)
│       │   ├── extract.py        (NEW — entity + claim extraction)
│       │   ├── canonicalize.py   (NEW — entity/concept canonicalization)
│       │   ├── distill.py        (NEW — pillar distillation)
│       │   └── align.py          (NEW — cross-corpus alignment)
│       ├── retrieve/
│       │   ├── chunks.py         (vector + FTS5, ported)
│       │   ├── concepts.py       (NEW — graph traversal)
│       │   ├── pillars.py        (NEW — pillar surfacing)
│       │   └── overlap.py        (NEW — cross-profile)
│       ├── modes/
│       │   ├── grounded.py       (ported — returns EvidencePack, not prose)
│       │   ├── speculative.py    (upgraded → oracle, returns EvidencePack)
│       │   └── debate_prep.py    (NEW — cross-scope synthesis prep)
│       ├── validator.py          (grounded quoted_span, ported)
│       ├── sanitize.py           (dual-call untrusted content, ported)
│       └── cli/
│           └── corpusctl.py      (NEW — ingest, review queue, list profiles)
├── tests/
│   ├── donna/                    (existing)
│   └── corpus/                   (NEW)
├── evals/
│   ├── donna/                    (existing)
│   └── corpus/                   (NEW — oracle, pillar-recovery, overlap, attribution)
├── migrations/
│   └── versions/                 (shared migration history; corpus files named corpus_NNNN_*)
└── docs/
    └── CORPUS_DESIGN.md          (your first real output — write before coding)
```

Donna's `tools/knowledge.py` becomes a thin wrapper over `corpus.Corpus` — one Donna PR, separate from Corpus's development.

---

## 6 · The field — what exists and what to learn from

Do deep research on these. Read source code where possible, find post-mortems, don't just read marketing.

### Graph RAG systems
- **Microsoft GraphRAG** — hierarchical community summaries, "global" vs "local" search. Expensive ingestion, high-quality themes. `github.com/microsoft/graphrag`. Paper: "From Local to Global: A Graph RAG Approach to Query-Focused Summarization."
- **LightRAG** — dual-level retrieval (entity-level + relation-level). Lighter than MS GraphRAG. `github.com/HKUDS/LightRAG`.
- **HippoRAG / HippoRAG 2** (2024-2025) — neurobiologically inspired, personalized PageRank over entity graphs.
- **Cognee** — ontology-driven. Production-focused, requires FalkorDB. Likely overkill for solo use; study their ontology approach.
- **Neo4j GraphRAG** — official client + patterns.
- **LlamaIndex PropertyGraphIndex** — graph on top of LlamaIndex.
- **KG-RAG** academic literature.

### Memory/knowledge systems (confirming the split)
- **Letta (MemGPT)** — memory manager separate from agent. Study context assembly.
- **Zep / Graphiti** — temporal KG. Study fact versioning.
- **Mem0** — memory-as-service. Shallow but API design is informative.
- **mnemostack** (OpenClaw community) — 4-way parallel retrieval + RRF.

### Persona/oracle attempts (instructive, none nail it)
- Character.ai — shallow, no grounding.
- Replika — pure vibe.
- LlamaIndex author-chatbot tutorials — naive baseline.
- HuggingFace "digital twin" projects — note what they all miss (worldview layer).

### What to steal (spec-level)
- **MS GraphRAG**: community summaries → worldview pillars. Adapt methodology.
- **LightRAG**: dual-level retrieval → chunks + concepts + pillars layered model.
- **Graphiti**: provenance + temporal versioning on every fact.
- **Letta**: the separation boundary.
- **Cognee**: ontology thinking, even if not their stack.

### What to NOT do
- No fine-tuning. User explicit. Oracle effect from retrieval + composition, not weights.
- No Neo4j unless graph traversal is the *measured* bottleneck. Start SQLite + adjacency tables. Codex: *"Your hard problem is semantic quality, not graph query performance."*
- No autonomous knowledge ingestion. User reviews everything.
- No multi-platform adapter. Corpus has no Discord code.
- No framework (LangChain, LlamaIndex). Hand-roll like Donna.

---

## 7 · Corpus's layered retrieval model

From Codex, directly:

> The graph is not "the retriever." The graph is the planner and organizer. Chunks remain the evidence substrate.

Five layers, consulted in a coordinated sweep:

1. **Chunks** (vector + FTS5 hybrid with RRF) — evidence substrate. Uses `sqlite-vec` `vec_distance_cosine`.
2. **Concept graph** (1-2 hop traversal) — organizes which chunks matter. Query → extract concepts → find in profile's concept graph → traverse adjacent → surface chunks.
3. **Worldview pillars** (distilled per profile) — 5-15 recurring preoccupations with evidence. Inject query-relevant pillars.
4. **Cross-corpus alignments** (overlap mode) — shared concepts across profiles with typed relationships.
5. **Style anchors** (characteristic passages) — voice calibration, NOT claim support.

Output: `EvidencePack`.

---

## 8 · The ingestion pipeline

Donna's current: fetch → chunk → dedupe → embed → store. Corpus extends significantly.

```
┌─────────┐
│ Source  │
└────┬────┘
     ▼
┌─────────────────┐
│ Fetch + parse   │ (markdownify, pypdf, custom)
└────┬────────────┘
     ▼
┌─────────────────┐
│ Chunk           │ (paragraph-aware, ~500t/80t overlap)
└────┬────────────┘
     ▼
┌─────────────────────────┐
│ Dedupe (fingerprint)    │
└────┬────────────────────┘
     ▼
┌──────────────────────────────┐
│ Embed (Voyage-3 via HTTP)    │ (SDK blocked on 3.14 — use direct HTTP like Donna)
└────┬─────────────────────────┘
     ▼
┌───────────────────────────────────────────────┐
│ ★ Entity + claim extraction (NEW)             │
│   Haiku per chunk: entities (people, orgs,    │
│   works, concepts) + claims                   │
│   Store in corpus_entities, corpus_claims,    │
│   corpus_chunk_entities                       │
└────┬──────────────────────────────────────────┘
     ▼
┌───────────────────────────────────────────────┐
│ ★ Entity canonicalization (NEW)               │
│   1. Embedding similarity → candidates        │
│   2. Alias rules → obvious overlaps           │
│   3. Haiku reconciliation →                   │
│       same_as, close_to, broader_than, etc    │
│   4. Human review queue for ambiguous cases   │
└────┬──────────────────────────────────────────┘
     ▼ (async, after all source chunks ingest)
┌───────────────────────────────────────────────┐
│ ★ Pillar distillation (NEW)                   │
│   Cluster candidate claims by similarity      │
│   Score by recurrence + distribution          │
│   LLM names + compresses clusters → pillars   │
│   Store supporting AND disconfirming evidence │
└────┬──────────────────────────────────────────┘
     ▼ (periodically, across profiles)
┌───────────────────────────────────────────────┐
│ ★ Cross-corpus alignment (NEW)                │
│   Find concepts in 2+ profiles                │
│   Classify relationship                       │
│   (same_as, contrasts_with,                   │
│    uses_different_frame_for)                  │
│   Human review queue                          │
└───────────────────────────────────────────────┘
```

**Key principles:**

- **Provenance on everything.** Entity, claim, pillar → must trace to `chunk_id`s.
- **Versioned, not replaced.** New sources regenerate pillars; preserve history.
- **Human-in-loop is a feature.** Canonicalization especially — review queue.
- **Cheap to rebuild.** Assume you'll re-extract with better prompts. Don't paint into corners.

---

## 9 · Eval harness — non-negotiable, build FIRST

Codex was blunt:

> "Graph RAG without evals becomes a confidence machine."

Build the eval harness BEFORE the graph layer. Minimum v0:

```yaml
# evals/corpus/golden_oracle/lewis_ai_agents.yaml
id: lewis_ai_agents
profile: lewis
mode: oracle
question: "What would Michael Lewis think about AI coding assistants?"
expect:
  must_reference_pillars:
    - "technical shortcuts with human cost"
    - "eccentric outsiders seeing what experts miss"
  must_cite_works_from: ["Flash Boys", "The Big Short"]
  must_include_hedge: true
  forbidden_claims:
    - Lewis has explicitly written about AI coding assistants
  min_confidence: 0.3
```

### Eval categories

- **Retrieval quality** (score EvidencePack): right pillars surfaced? right chunks pulled?
- **Attribution**: grounded mode — every claim has verbatim quote from cited chunk.
- **Overlap**: cross-corpus alignments typed correctly on gold set?
- **Pillar quality**: on curated corpus (Twain seed, Lewis with user priors), does distillation recover expected pillars?
- **Speculative labeling**: oracle output correctly labels its own speculation?

### Setup

- Golden cases in `evals/corpus/` as YAML
- Seed corpus: Project Gutenberg Mark Twain (~500 chunks, deterministic)
- Pytest-integrated, CI-blocking
- Baseline numbers before graph layer, so you have comparisons

---

## 10 · Quality bar — what "done" looks like per phase

### Phase 0 — Research + design doc (3-5 days)
- [ ] Read papers + reference code from §6. Notes to `docs/CORPUS_RESEARCH_NOTES.md`.
- [ ] Write `docs/CORPUS_DESIGN.md`: variant comparison, schema with worked examples (Lewis/Dalio/Twain), canonicalization decision tree, EvidencePack schema precisely, top 3 risks + mitigations.
- [ ] Get user feedback BEFORE writing code.

### Phase 1 — Package scaffold + port Donna's knowledge layer (~1 week)
- [ ] `src/corpus/` layout per §5
- [ ] Migrations prefixed `corpus_NNNN_*`, all `corpus_*` tables
- [ ] Port: `ingest/{chunk,embed,pipeline}`, `modes/retrieval`, `security/{validator,sanitize}` into Corpus
- [ ] Public API: `Corpus.open()`, `.ingest()`, `.retrieve_chunks()`, `.answer(mode=...)` → EvidencePack
- [ ] Donna PR: `tools/knowledge.py` as thin wrapper over Corpus
- [ ] All existing Donna tests still pass
- [ ] New Corpus tests covering ported primitives

### Phase 2 — Entity + claim extraction (~1 week)
- [ ] Schema: `corpus_entities`, `corpus_entity_aliases`, `corpus_entity_mentions`, `corpus_claims`, `corpus_chunk_entities`
- [ ] Ingestion adds Haiku extraction per chunk
- [ ] Embeddings on entities + claims
- [ ] API: `recall_entities(profile, query)`, `recall_claims(profile, query)`
- [ ] Provenance on every entity: `chunk_ids`, `salience`, `extraction_prompt_version`

### Phase 3 — Canonicalization + concept graph (~1 week)
- [ ] Schema: `corpus_concepts`, `corpus_concept_edges`, `corpus_canonicalization_proposals`
- [ ] Three-stage canonicalization (embed → alias rules → LLM reconciliation)
- [ ] Review queue via `corpusctl review`
- [ ] Typed relationships: `same_as`, `close_to`, `broader_than`, `narrower_than`, `contrasts_with`, `uses_different_frame_for`
- [ ] Never auto-apply `same_as`

### Phase 4 — Worldview pillars (~1-2 weeks, eval-heavy)
- [ ] Schema: `corpus_worldview_pillars`, `corpus_pillar_evidence`, `corpus_pillar_versions`
- [ ] Distillation pipeline: cluster claims → score → name → evidence + counter
- [ ] Regeneration + versioning on corpus change
- [ ] Pillar-recovery evals on curated corpus
- [ ] `recall_pillars(profile, query)` returns top-K by relevance

### Phase 5 — Cross-corpus alignments + overlap mode (~1 week)
- [ ] Schema: `corpus_cross_corpus_alignments`
- [ ] Cross-profile canonicalization (typed relationships matter more here)
- [ ] `answer(mode="overlap", profile_a, profile_b, topic)` → EvidencePack
- [ ] `answer(mode="debate_prep", topic, profiles=[...])` for Donna's orchestrator

### Phase 6 — Oracle mode (~1 week)
- [ ] `answer(mode="oracle", profile, question)` → EvidencePack:
  - Layered retrieval (chunks → concepts → pillars)
  - Query-relevant pillar surfacing
  - Style anchor selection
  - Argumentative move extraction
  - Explicit confidence + refusal
- [ ] Oracle evals (labeling, pillar coverage, evidence grounding)
- [ ] Donna's speculative mode rewired to call Corpus oracle

### Eval harness stays alive through every phase.

---

## 11 · Hard rules — never do these

From two Codex reviews + Hermes comparison:

1. **Corpus never does final prose.** Returns EvidencePack. Donna composes.
2. **Don't auto-merge concepts/entities without human review.** Automatic canonicalization destroys nuance.
3. **Don't strip provenance.** Every pillar/claim/alignment → chunk evidence.
4. **Don't build without evals.** Retrieval changes must move golden eval numbers.
5. **Don't reach for Neo4j early.** SQLite + `sqlite-vec` + FTS5 + adjacency tables handle 500k chunks.
6. **Don't treat pillars as facts.** They are interpretations. Version them. Preserve counterexamples. No-counter-evidence pillars are suspicious.
7. **Don't fine-tune.** Retrieval + composition + style anchors + pillars beats fine-tuning for voice and doesn't lock to a model.
8. **Don't build a real-time ingestion pipeline.** Entity extraction + pillar distillation are batch. Background jobs.
9. **Don't cross schema ownership.** Corpus owns `corpus_*`. Donna owns everything else. Cross-boundary only via Corpus public API.
10. **Don't over-generalize.** Single-digit profiles, ~500k total chunks. Resist distributed-systems reach.

---

## 12 · Dependencies — what Donna already decided, inherit these

- **Python 3.14** (Donna runs 3.14.3; Dockerfile `python:3.14-slim`)
- **SQLite with WAL + FTS5 + sqlite-vec** (in-process, no external DB)
- **Voyage-3 embeddings via direct HTTP** (voyageai SDK dropped on 3.14; Donna has the pattern in `src/donna/ingest/embed.py`)
- **Anthropic for LLM calls** (Haiku for extraction/canonicalization, Sonnet for complex distillation, Opus only for user-visible generation in Donna)
- **Ruff + pytest + pytest-asyncio + mypy**
- **Alembic for migrations** (shared with Donna, `corpus_NNNN_*` filename prefix)
- **structlog** for logging
- **OpenTelemetry** for tracing (same Phoenix instance Donna exports to)

Do NOT add:
- Neo4j / FalkorDB
- Redis (no queue; background jobs in-process or reuse Donna's worker)
- Postgres
- LangChain / LlamaIndex frameworks

---

## 13 · Non-obvious things the user cares about

From multiple days of design conversation:

- **Provenance > polish.** Pillar without chunk evidence → remove it, even if it "feels right."
- **Human review queue is a feature.** 10 min/week > auto-merge degradation.
- **Refusal is respected.** "I don't have material on this" is correct, not failure. Oracle too: no relevant pillars → refuse.
- **User is in this for the learning, not the product.** Understanding > speed.
- **Enterprise is not a consideration.** Don't mention enterprise in code or docs.
- **Oracle voice must be genuinely distinct per author.** If Lewis and Dalio "feel" the same, project failed.
- **Seed corpus: Twain** (Gutenberg). Move to Lewis after pipeline proven.
- **Review queue surface preferred: `corpusctl review` CLI** (Rich + Typer, like `botctl`).

---

## 14 · Verbatim Codex insights (GPT-5.4) — session `019db08b-9636-7d83-90bd-7ef5e477770d`

> "Corpus is a corpus interpretation engine, not memory."

> "The graph is not 'the retriever.' The graph is the planner and organizer. Chunks remain the evidence substrate."

> "Worldview-Pillar Extraction: A useful v0 is 2-4 days. A trustworthy system is several weeks of eval and iteration. The trap is asking Haiku: 'What are this author's 10 recurring preoccupations?' That produces plausible book-report themes."

> "A better pipeline: 1. Extract candidate claims/themes per chunk or per cluster. 2. Cluster candidates by semantic similarity. 3. Score by recurrence, distribution across works/time, and evidence density. 4. Ask an LLM to name and compress clusters into pillars. 5. Store pillars with supporting and disconfirming evidence. 6. Periodically regenerate as corpus changes. 7. Evaluate against manually written gold questions."

> "Entity Canonicalization: Use a three-stage pipeline. 1. Embedding similarity proposes candidates. 2. Lexical/alias rules catch obvious overlaps. 3. LLM reconciliation decides: same concept, related concept, narrower/broader concept, false friend. You want relationship types, not just merges."

> "'What Would X Say' Ceiling: The best framing is not 'Lewis simulator.' It is: 'A constrained reconstruction of how Lewis might reason about this, grounded in recurring patterns from the corpus.' The model will often produce 'Claude explaining Lewis' rather than 'Lewis thinking freshly.' It may imitate cadence superficially while missing the inner pressure of the worldview."

> "I would not model the primitive as scope = persona. I would model: corpus, source, author, work, chunk, claim, concept, pillar, alignment, interpretation profile. A persona is then a view over attributed knowledge, not the root object."

> "Extract it as a library/package with a hard internal API and its own eval suite. Keep one deployable system for now. Separate project boundary, not necessarily separate repo/process/database on day one."

> "That is not architecture theater. The product goal changed. The knowledge layer is now the product's hard part."

---

## 15 · Known unknowns — ask these BEFORE committing code

1. **First real corpus**: Twain as seed confirmed. Lewis is the first "real" target. User has Lewis's books on Kindle — confirm delivery format (Kindle export → txt, manual extract, etc.) before building a parser.
2. **Review queue surface**: `corpusctl review` CLI is default. Confirm vs. Discord slash command.
3. **Pillar cardinality**: 7-12 per profile default, configurable. Confirm.
4. **Alignment approval thresholds**: auto-apply `close_to` at confidence > 0.9? Never auto-apply `same_as`. Confirm defaults.
5. **Oracle refusal strictness**: retrieval confidence threshold for refusal. Start at 0.3, calibrate on real use.
6. **Background ingestion runner**: reuse Donna's worker process, or spawn a separate `corpus-worker`? Default: reuse Donna's worker since it already has lease-and-recovery.

---

## 16 · The quality signal — how the user knows you're on track

Not "tests pass." Table stakes.

**Real signal:** when you query `corpus.answer(profile="lewis", question="X", mode="oracle")` and Donna hands the composed reply back, the user reads it and says **"yes — that is a Lewis-shaped thought I have not had before, grounded in passages I recognize."**

Failure mode: "this sounds like Claude writing a book report about Lewis."

Between those extremes is where every prior attempt has lived. Your job: push toward the first. Lives in:
- Pillar quality (non-obvious, evidence-backed, distinctive)
- Style anchor selection (actually sounds like the author)
- Argumentative move extraction (reasoning *patterns*, not topics)
- Refusal discipline (don't extrapolate past corpus)
- Attribution rigor (every substantive claim → evidence)

---

## 17 · Bootstrap: first ~4 hours

1. Read papers in §6 (~2 hours). Notes to `docs/CORPUS_RESEARCH_NOTES.md`.
2. Write `docs/CORPUS_DESIGN.md` with variant comparison + schema + worked examples (~1-2 hours).
3. Scaffold empty `src/corpus/` package: `__init__.py` with `__version__ = "0.0.1"`, `api.py` with method stubs + docstrings, `types.py` with dataclass skeletons.
4. Stop. Ask user for feedback on design doc before writing real code.

Then phases 1-6 in order, each gated by evals + user sign-off.

---

## 18 · Timeline

**5-8 weeks** for all six phases with evals, solo pace, from cold start.

- Faster if rushing — not recommended
- Slower if paper-reading takes longer — fine
- Phase 0 (design doc) alone: 3-5 days. Don't skimp.

---

## 19 · Final instruction

Build thoughtfully. This is the hard part of the larger system.

When design doc is ready, stop and get user feedback. It's the most important artifact of the first week.

Ask questions when spec is ambiguous. Don't pick defaults silently.

Good luck. The knowledge layer is now the product's hard part.
