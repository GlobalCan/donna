# Think — Session Bootstrap Brief

**This is the mission brief for a new Claude Code session tasked with building "Think" — a corpus interpretation engine. Paste this entire file as the opening context of that session, or reference it via its path.**

> **Rename note (2026-04-23):** the project was called "Corpus" in earlier design docs and Codex sessions. It has since been renamed to **Think** because "corpus" is still the most precise word for the root data concept ("an author's corpus of work"), and having the project name collide with it was a constant disambiguation tax. So: project/package/class = **Think**; data concept = **corpus**. If you see "Corpus" in any imported Codex quote or older artifact, read it as "Think." The architectural substance is unchanged.

Think is an internal Python package that lives inside the existing `GlobalCan/donna` monorepo alongside the agent runtime. Same repo, same deployable process, same database file — but a hard internal boundary, separate schema namespace (`think_*` tables), separate migrations folder, separate public API, separate test suite, separate eval harness. Donna imports from Think; Think never imports from Donna.

Why monorepo: single maintainer, single deployment target, one-process product. Multi-repo splits at this stage would be premature generalization. Codex explicitly recommended this structure.

---

## 0 · State-of-the-base update (2026-04-23) — READ THIS FIRST

This brief was written before Donna went to production. As of 2026-04-23 the
base Think depends on has materially matured. Many assumptions in this brief
have now moved from "planned" to "validated live." A couple of defaults and
path conventions have also changed. Everything below the horizontal rule in
this section is still current — but read this section first or you will make
decisions based on stale assumptions.

### What Donna is now

- **v0.3.2** · Python **3.14.3** (not 3.12 — 3.14 confirmed everywhere: pyproject, Dockerfile, droplet, CI) · **74 tests green** · **live in production** on a DigitalOcean droplet at `159.203.34.165`
- **Containers:** `donna-bot` + `donna-worker`, `ghcr.io/globalcan/donna:latest`, built automatically by GHA on every `main` merge
- **Three-layer backups live:** DO snapshots (daily, 4-week retention), droplet cron tarball (@ 03:00 UTC, 7-day), laptop scp → OneDrive (@ 06:00 local, 30-day). Think data in the same SQLite file inherits all three layers automatically — no new backup work needed. Scripts: `scripts/donna-backup.sh` and `scripts/donna-fetch-backup.ps1`.
- **Codex reviews absorbed:** three passes (defect, adversarial challenge, Hermes comparison) plus a fourth latent-bug hunt post-deploy. All findings either fixed or explicitly deferred with mitigation. The FTS5 bug below was a fifth Codex-style finding we caught ourselves during the v0.3.2 Huck Finn smoke test.

### Stack that Think will build on — validated live (2026-04-23)

The knowledge layer assumptions in this brief (§7-8) are no longer aspirational. They ran end-to-end against the live droplet:

- **Ingest pipeline:** 402-chunk Huck Finn novel ingested via `botctl teach`. Voyage-3 embeddings via direct HTTP (the `voyageai` SDK is still broken on Py 3.14 — Donna's HTTP pattern in `src/donna/ingest/embed.py` is the reference). `insert_source` + `insert_chunk` + `chunks_fts` INSERT/DELETE/UPDATE triggers all work. ~5 seconds for the whole pipeline on a $6 droplet.
- **Hybrid retrieval:** `retrieve_knowledge()` in `src/donna/modes/retrieval.py` runs semantic (`vec_distance_cosine`) + FTS5 keyword + RRF merge + diversity cap. Returned top-3 chunks for "what does Huck say about civilization" with the chapter-1 table-of-contents chunk ranked first (score 0.588). The sqlite-vec native path, not the Python fallback.
- **Grounded mode + `quoted_span` validator:** `answer_grounded()` called live against the 402-chunk scope. Model produced well-formed JSON with `claims[].citations[]` + `claims[].quoted_span` + `prose`. Validator (`src/donna/security/validator.py`) caught a real hallucination: model cited a Jim-dialogue chunk for an Aunt Sally quote from the book's ending. Validator rejected the claim because the span wasn't in the cited chunk. **The "constrained transparency" model Codex demanded is not theoretical — it works and it's strict.** This is directly what Think oracle mode will be.

### Bugs found and fixed that Think would have inherited

- **FTS5 syntax injection** (PR #15) — `knowledge.keyword_search()` passed raw user input into `chunks_fts MATCH ?`. Any natural-language query containing `"`, `(`, `)`, `*`, `?`, `:`, `+`, `^`, `~`, `-`, or bareword operators (`AND`, `OR`, `NOT`, `NEAR`) raised `sqlite3.OperationalError`. Fix: new `_fts_sanitize(query)` helper (`src/donna/memory/knowledge.py`) tokenizes via `re.findall(r"\w+", q)` and wraps each token in double quotes. Preserves FTS5's implicit-AND semantics; empty-token queries short-circuit to `[]`. **Think: when you port or mirror this FTS path, reuse or copy `_fts_sanitize` — do not send raw queries to MATCH.** Tests live in `tests/test_fts_sanitize.py`.
- **`/cancel` didn't cancel** (PR #9) — jobs ignored the CANCELLED status flip. Fixed via `JobContext.check_cancelled()` raised in each mode's iteration loop. Not directly your concern but: **Think's long-running ingestion jobs will run through Donna's `JobContext`. Inherit the pattern — call `ctx.check_cancelled()` between expensive steps (entity extraction per chunk, pillar distillation per cluster, etc).**
- **`docker compose exec bot python -c ...` bypasses sops-decrypted secrets** — Donna's entrypoint decrypts `secrets/prod.enc.yaml` on container start, but `docker exec` skips ENTRYPOINT so pydantic blows up on inline comments in `.env`. Workaround: `docker compose exec bot /entrypoint.sh python -c ...`. `botctl` already routes through a wrapper; `thinkctl` should do the same. See PR #7 for the Dockerfile shim pattern.
- **PowerShell 5.1 vs 7** (PR #13) — Windows ships PS 5.1 by default. `Get-Date -AsUTC` is PS 7+. Use `(Get-Date).ToUniversalTime().ToString('...')`. Relevant if you build laptop-side tooling for corpus ingestion or review.
- **`flags=re.UNICODE`** — redundant on Py3 str patterns; ruff `UP` rules flag it. Trivial but catches regressions.
- **Droplet `bot` user has NO sudo password** — `harden-droplet.sh` creates it with `--disabled-password` but adds it to the `sudo` group, so `sudo` prompts forever. Anything requiring root must go through DO web console or docker-group escape hatch (`docker run --rm -v /path:/path alpine ...`). Think tooling on the droplet must not assume `sudo`.
- **Phoenix upstream broken (14.x line)** — disabled in `docker-compose.yml` with a big comment block. OpenTelemetry export still runs (it just logs "unreachable" warnings). **Think inherits the same OTEL exporter — your spans will go nowhere useful until we find a working tag or swap to Tempo/Jaeger. Plan accordingly for pillar-distillation eval debugging: pipe to structlog, not traces, for now.**

### Original assumptions in this brief that have moved to "validated"

- §7 layered retrieval model (chunks + concept + pillars) — chunks layer proven on 402-chunk corpus ✓
- §8 ingestion pipeline — through the "embed" step proven live ✓. Extraction / canonicalization / distillation still new work.
- §12 dependencies list — all confirmed except Phoenix (see above). Voyage-3 direct-HTTP pattern ships; don't try the SDK.
- §16 quality signal ("this sounds like Claude writing a book report") is even more real now that grounded mode is live — the validator caught exactly that class of hallucination today.

### Original assumptions in this brief that have NOT changed

- Monorepo with hard internal boundary. Confirmed with the deploy — Think riding Donna's SQLite file + Donna's deploy pipeline is cleaner now, not worse.
- `agent_scope` is still Donna's primitive; it's still the wrong primitive for corpus interpretation. §4's attributed-knowledge-graph model is right.
- No framework. No fine-tuning. No Neo4j day-one. All still right.
- Phase 0 design doc first. User will push back if you skip to coding. They've been burned by agents jumping the gun before.
- EvidencePack contract (Think returns structure; Donna composes prose) is the load-bearing decision. Holds.

### Paths and environment

- User's primary laptop repo path may differ from the brief's old example (`C:\Users\rchan\OneDrive\Desktop\donna`). On the laptop you're running on, check `git remote -v` in the repo root and trust whatever that shows. Remote is still `GlobalCan/donna`.
- Droplet repo at `/home/bot/donna`. DB at `/data/donna/donna.db` (bind-mounted from host; `/data/donna.db` inside container).
- GHCR publish is automatic — any `main` merge triggers image rebuild. Droplet pulls manually via `docker compose pull && up -d`; `donna-update.timer` is installed but intentionally not enabled yet (Codex prescription: auto-deploy without loop-supervision + backups raises blast radius — backups exist now, supervision exists, auto-deploy re-evaluation is on the open list).

### Split of concerns for the multi-session workflow

The user is continuing **Donna-side development on their primary laptop** (this session / successor sessions on the same machine). They're running **Think development on a second laptop** via a separate Claude Code session. That split is the workflow, not a temporary arrangement.

- **Think session owns:** `src/think/*`, `tests/think/*`, `evals/think/*`, `migrations/versions/think_*`, `docs/THINK_*`
- **Donna session owns:** everything else
- **Both sessions share:** `main` branch via GitHub. Coordinate via PR descriptions. Merges happen on whichever laptop is current.
- **Conflict avoidance:** don't edit `src/donna/*` from the Think session unless the change is explicitly the "Donna wires think.Think into tools/knowledge.py" integration PR — and even then, open it as a separate small PR, don't bundle with Think phase work.
- **When Think needs something from Donna** (pattern, helper, test fixture), copy first, unify later. Small duplication is cheaper than cross-session coupling.

### Pointers into the current code you'll want in your first hour

- `src/donna/ingest/embed.py` — Voyage-3 via direct HTTP (pattern to port)
- `src/donna/ingest/chunk.py` + `src/donna/ingest/pipeline.py` — chunking + within-batch dedupe
- `src/donna/memory/knowledge.py` — `insert_source`, `insert_chunk`, `semantic_search`, `keyword_search`, `_fts_sanitize`, `_row_to_chunk`
- `src/donna/modes/retrieval.py` — `retrieve_knowledge`, `_rrf_merge`, `_apply_diversity`, `_apply_temporal_prior`
- `src/donna/modes/grounded.py` — `answer_grounded` (legacy dict-returning shape you can mirror for `Think.answer()` before EvidencePack is fully defined)
- `src/donna/security/validator.py` — `validate_grounded`, `quoted_span` logic — port as-is
- `src/donna/security/sanitize.py` — dual-call untrusted-content pattern — port as-is
- `src/donna/agent/context.py` — `JobContext` primitives (`model_step`, `tool_step`, `check_cancelled`, `maybe_compact`, `checkpoint`, `finalize`) — Think's long-running jobs (extraction, distillation) should run inside this, not invent their own
- `src/donna/memory/ids.py` — typed ID prefixes. Use `ids.chunk_id()` style for corpus IDs too; keep the convention.
- `tests/conftest.py` — `fresh_db` fixture (alembic upgrade via subprocess). Think tests should reuse.
- `tests/test_fts_sanitize.py` — the pattern for testing a DB-touching primitive. Copy.

### The one hard-learned ops lesson

Don't run ad-hoc SQL or Python against the live DB without going through `docker compose exec bot /entrypoint.sh` — `secrets/prod.enc.yaml` must be decrypted first or pydantic rejects config. This trips every fresh debugging session at least once.

---

## 0.1 · How to use this brief

You (the agent reading this) are a session operating inside the existing Donna repository at `C:\Users\rchan\OneDrive\Desktop\donna` (remote: `GlobalCan/donna`). Your job is to add a new `think/` package alongside `donna/`.

Read in this order before writing any code:

1. This whole file.
2. `docs/PLAN.md` — Donna's architectural plan.
3. `docs/KNOWN_ISSUES.md` — two Codex adversarial reviews absorbed, plus the "v1.1 — Hermes Agent adversarial comparison" section that motivated this extraction.
4. `docs/OPERATIONS.md` — production ops.
5. `docs/review.html` — interactive adversarial review of Donna.
6. `src/donna/modes/retrieval.py` — current hybrid retrieval (you're porting this).
7. `src/donna/memory/knowledge.py` — current knowledge/chunk primitives.
8. `src/donna/security/validator.py` — grounded-mode citation validator (moves to Think).
9. `src/donna/security/sanitize.py` — untrusted-content dual-call (moves to Think).
10. `src/donna/ingest/{chunk.py,embed.py,pipeline.py}` — ingestion (moves to Think).
11. `src/donna/modes/{grounded.py,speculative.py,debate.py}` — mode direct-call APIs (their retrieval primitives move; orchestration stays in Donna).

Then come back here for the mission.

---

## 1 · Who this is for and what they actually want

**User:** Solo maintainer. Security-conscious, architecture-fluent, iteration-heavy. Not building a SaaS. Building a personal thinking partner.

**The core product thesis — learn this by heart:**

The user does NOT want a scholar ("what did Michael Lewis say about X").
The user DOES want an oracle ("what would Michael Lewis say about X").

They also want cross-author synthesis — "where do Lewis and Dalio overlap on X, and where do they use the same words to mean different things?"

Both require structured interpretation artifacts — worldview pillars, recurring preoccupations, canonicalized concepts, argumentative moves — not just chunks of text retrieved by cosine similarity. **This is the hard, interesting, distinctive thing about the project.** Think is not a generic RAG system. If it ends up looking like a generic RAG system, you've failed.

Real use cases (not hypotheticals):

- "What would Michael Lewis think about AI coding assistants?"
- "Based on Taleb's writings, how should I think about long-tail risk?"
- "Where do Lewis and Dalio agree about humility?"
- "Where does Dalio operationalize something Lewis moralizes?"
- "Early Lewis vs late Lewis — how has his view of Wall Street changed?"
- Putting distinct authors in dialog over the user's own drafts to sharpen thinking.

---

## 2 · The critical reframe — Think is NOT a memory system

From Codex (GPT-5.4) session `019db08b-9636-7d83-90bd-7ef5e477770d`:

> **Think is a "corpus interpretation engine," not a memory system.** Memory is about facts the agent accumulates from use. Think interpretation is about extracting, canonicalizing, distilling, and synthesizing the structured content of a body of work. Same tool types (vector DBs, graph, LLM) but fundamentally different problem shape.

Memory systems (Mem0, Letta, Zep/Graphiti) store facts the agent learns during interaction. Think stores interpretations of external bodies of work the user curates. Don't conflate. Donna already has a `facts` table for memory; Think is something else entirely.

**Think answers:**
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

## 3 · Names

The rename (see preamble) cleanly separates the previously overloaded word:

- **Project / Python package:** `think` (lowercase module, e.g. `from think import Think`)
- **Top-level class:** `Think` (e.g. `t = Think.open("./data/donna.db")`)
- **CLI:** `thinkctl`
- **Schema prefixes:** `think_*` — every table Think owns (`think_chunks`, `think_pillars`, `think_concepts`, `think_entities`, etc.)
- **Migrations:** `migrations/versions/think_NNNN_*.py` (shared Alembic history with Donna, distinguished by filename prefix)
- **Docs:** `docs/THINK_*.md` (this brief, plus `THINK_DESIGN.md`, `THINK_RESEARCH_NOTES.md` when you create them)
- **Data concept "corpus":** an author's body of work. Stays lowercase, used in prose ("Lewis's corpus", "the Twain seed corpus") and as the root data abstraction in §4's schema.

Project and data concept no longer collide.

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

It's also the only schema that answers cross-author questions naturally. Donna v1 currently models `agent_scope` as the root — that's the wrong primitive. Think fixes it.

---

## 5 · The Think ↔ Donna integration contract

Think is an **internal Python package** that Donna imports directly. Same repo, same process, same SQLite file. No HTTP boundary, no separate deployment.

The contract — load-bearing:

**Think returns structured `EvidencePack` objects, NOT final prose.**

```python
from think import Think

c = Think.open("./data/donna.db")   # same db file, think_* tables

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
- Think does NOT know about Discord or any chat surface
- Think does NOT own the LLM call that produces user-facing prose
- Think does NOT handle consent or taint propagation (Donna's concerns)
- Think DOES everything up to "structured context ready for final composition"

This prevents Donna from becoming a thin shell over Think and keeps voice/consent/interaction responsibility with the agent runtime.

Think DOES call LLMs internally — for entity extraction, canonicalization, pillar distillation, post-gen validation. Those are "curation-time" LLM calls, not "query-time response generation." Different concerns.

### Schema ownership rule

Strict: **Think owns every `think_*` table. Donna owns everything else.** No cross-writing ever. Donna reads Think only via `from think import ...` — never via SQL.

### Directory layout

```
GlobalCan/donna/
├── src/
│   ├── donna/                    (existing agent runtime — unchanged except imports)
│   └── think/                    (NEW — corpus interpretation engine)
│       ├── __init__.py
│       ├── api.py                (public Think class + EvidencePack)
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
│           └── thinkctl.py      (NEW — ingest, review queue, list profiles)
├── tests/
│   ├── donna/                    (existing)
│   └── think/                    (NEW)
├── evals/
│   ├── donna/                    (existing)
│   └── think/                    (NEW — oracle, pillar-recovery, overlap, attribution)
├── migrations/
│   └── versions/                 (shared migration history; corpus files named think_NNNN_*)
└── docs/
    └── THINK_DESIGN.md          (your first real output — write before coding)
```

Donna's `tools/knowledge.py` becomes a thin wrapper over `think.Think` — one Donna PR, separate from Think's development.

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
- No multi-platform adapter. Think has no Discord code.
- No framework (LangChain, LlamaIndex). Hand-roll like Donna.

---

## 7 · Think's layered retrieval model

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

Donna's current: fetch → chunk → dedupe → embed → store. Think extends significantly.

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
│   Store in think_entities, think_claims,    │
│   think_chunk_entities                       │
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
# evals/think/golden_oracle/lewis_ai_agents.yaml
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

- Golden cases in `evals/think/` as YAML
- Seed corpus: Project Gutenberg Mark Twain (~500 chunks, deterministic)
- Pytest-integrated, CI-blocking
- Baseline numbers before graph layer, so you have comparisons

---

## 10 · Quality bar — what "done" looks like per phase

### Phase 0 — Research + design doc (3-5 days)
- [ ] Read papers + reference code from §6. Notes to `docs/THINK_RESEARCH_NOTES.md`.
- [ ] Write `docs/THINK_DESIGN.md`: variant comparison, schema with worked examples (Lewis/Dalio/Twain), canonicalization decision tree, EvidencePack schema precisely, top 3 risks + mitigations.
- [ ] Get user feedback BEFORE writing code.

### Phase 1 — Package scaffold + port Donna's knowledge layer (~1 week)
- [ ] `src/think/` layout per §5
- [ ] Migrations prefixed `think_NNNN_*`, all `think_*` tables
- [ ] Port: `ingest/{chunk,embed,pipeline}`, `modes/retrieval`, `security/{validator,sanitize}` into Think
- [ ] Public API: `Think.open()`, `.ingest()`, `.retrieve_chunks()`, `.answer(mode=...)` → EvidencePack
- [ ] Donna PR: `tools/knowledge.py` as thin wrapper over Think
- [ ] All existing Donna tests still pass
- [ ] New Think tests covering ported primitives

### Phase 2 — Entity + claim extraction (~1 week)
- [ ] Schema: `think_entities`, `think_entity_aliases`, `think_entity_mentions`, `think_claims`, `think_chunk_entities`
- [ ] Ingestion adds Haiku extraction per chunk
- [ ] Embeddings on entities + claims
- [ ] API: `recall_entities(profile, query)`, `recall_claims(profile, query)`
- [ ] Provenance on every entity: `chunk_ids`, `salience`, `extraction_prompt_version`

### Phase 3 — Canonicalization + concept graph (~1 week)
- [ ] Schema: `think_concepts`, `think_concept_edges`, `think_canonicalization_proposals`
- [ ] Three-stage canonicalization (embed → alias rules → LLM reconciliation)
- [ ] Review queue via `thinkctl review`
- [ ] Typed relationships: `same_as`, `close_to`, `broader_than`, `narrower_than`, `contrasts_with`, `uses_different_frame_for`
- [ ] Never auto-apply `same_as`

### Phase 4 — Worldview pillars (~1-2 weeks, eval-heavy)
- [ ] Schema: `think_worldview_pillars`, `think_pillar_evidence`, `think_pillar_versions`
- [ ] Distillation pipeline: cluster claims → score → name → evidence + counter
- [ ] Regeneration + versioning on corpus change
- [ ] Pillar-recovery evals on curated corpus
- [ ] `recall_pillars(profile, query)` returns top-K by relevance

### Phase 5 — Cross-corpus alignments + overlap mode (~1 week)
- [ ] Schema: `think_cross_corpus_alignments`
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
- [ ] Donna's speculative mode rewired to call Think oracle

### Eval harness stays alive through every phase.

---

## 11 · Hard rules — never do these

From two Codex reviews + Hermes comparison:

1. **Think never does final prose.** Returns EvidencePack. Donna composes.
2. **Don't auto-merge concepts/entities without human review.** Automatic canonicalization destroys nuance.
3. **Don't strip provenance.** Every pillar/claim/alignment → chunk evidence.
4. **Don't build without evals.** Retrieval changes must move golden eval numbers.
5. **Don't reach for Neo4j early.** SQLite + `sqlite-vec` + FTS5 + adjacency tables handle 500k chunks.
6. **Don't treat pillars as facts.** They are interpretations. Version them. Preserve counterexamples. No-counter-evidence pillars are suspicious.
7. **Don't fine-tune.** Retrieval + composition + style anchors + pillars beats fine-tuning for voice and doesn't lock to a model.
8. **Don't build a real-time ingestion pipeline.** Entity extraction + pillar distillation are batch. Background jobs.
9. **Don't cross schema ownership.** Think owns `think_*`. Donna owns everything else. Cross-boundary only via Think public API.
10. **Don't over-generalize.** Single-digit profiles, ~500k total chunks. Resist distributed-systems reach.

---

## 12 · Dependencies — what Donna already decided, inherit these

- **Python 3.14** (Donna runs 3.14.3; Dockerfile `python:3.14-slim`)
- **SQLite with WAL + FTS5 + sqlite-vec** (in-process, no external DB)
- **Voyage-3 embeddings via direct HTTP** (voyageai SDK dropped on 3.14; Donna has the pattern in `src/donna/ingest/embed.py`)
- **Anthropic for LLM calls** (Haiku for extraction/canonicalization, Sonnet for complex distillation, Opus only for user-visible generation in Donna)
- **Ruff + pytest + pytest-asyncio + mypy**
- **Alembic for migrations** (shared with Donna, `think_NNNN_*` filename prefix)
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
- **Review queue surface preferred: `thinkctl review` CLI** (Rich + Typer, like `botctl`).

---

## 14 · Verbatim Codex insights (GPT-5.4) — session `019db08b-9636-7d83-90bd-7ef5e477770d`

> "Think is a corpus interpretation engine, not memory."

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
2. **Review queue surface**: `thinkctl review` CLI is default. Confirm vs. Discord slash command.
3. **Pillar cardinality**: 7-12 per profile default, configurable. Confirm.
4. **Alignment approval thresholds**: auto-apply `close_to` at confidence > 0.9? Never auto-apply `same_as`. Confirm defaults.
5. **Oracle refusal strictness**: retrieval confidence threshold for refusal. Start at 0.3, calibrate on real use.
6. **Background ingestion runner**: reuse Donna's worker process, or spawn a separate `corpus-worker`? Default: reuse Donna's worker since it already has lease-and-recovery.

---

## 16 · The quality signal — how the user knows you're on track

Not "tests pass." Table stakes.

**Real signal:** when you query `think.answer(profile="lewis", question="X", mode="oracle")` and Donna hands the composed reply back, the user reads it and says **"yes — that is a Lewis-shaped thought I have not had before, grounded in passages I recognize."**

Failure mode: "this sounds like Claude writing a book report about Lewis."

Between those extremes is where every prior attempt has lived. Your job: push toward the first. Lives in:
- Pillar quality (non-obvious, evidence-backed, distinctive)
- Style anchor selection (actually sounds like the author)
- Argumentative move extraction (reasoning *patterns*, not topics)
- Refusal discipline (don't extrapolate past corpus)
- Attribution rigor (every substantive claim → evidence)

---

## 17 · Bootstrap: first ~4 hours

1. Read papers in §6 (~2 hours). Notes to `docs/THINK_RESEARCH_NOTES.md`.
2. Write `docs/THINK_DESIGN.md` with variant comparison + schema + worked examples (~1-2 hours).
3. Scaffold empty `src/think/` package: `__init__.py` with `__version__ = "0.0.1"`, `api.py` with method stubs + docstrings, `types.py` with dataclass skeletons.
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
