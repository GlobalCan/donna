# Market Research Session — Personal-AI / Agent / RAG landscape

> **Purpose:** paste this into a NEW Claude Code session on the user's
> LOCAL laptop (Obsidian brain + Chrome extension + browser access
> available). The goal is a comparative feature + architecture
> analysis against every relevant competitor in the 2026 personal-AI /
> agent / RAG space, to inform Donna v0.5+ planning. The output
> artifact feeds into the Codex deep-dive comparison.
>
> **Why this runs on the user's laptop, not the cloud sandbox:** the
> cloud session doesn't have browser automation, Chrome extension
> access, or the Obsidian brain vault. Live research needs those.

---

## You are

A research agent tasked with producing a competitive landscape report
on the personal-AI / agent-framework / RAG-product space as of April
2026. Your user has built a project called Donna — a solo-operator
Discord-based personal AI assistant, hand-rolled on the Anthropic SDK,
with corpus-grounded QA + voice-extrapolation + cross-author debate
modes. They want to know what others have built, what lessons are
worth stealing, and what pitfalls are worth avoiding, before they
commit to v0.5 feature work.

## Deliverable

A single Markdown document (plan for ~3000-5000 words):

```
# Personal-AI / Agent / RAG Landscape 2026 — Research for Donna v0.5

## 0. Executive summary (3 paragraphs)

## 1. Comparative feature matrix
Big table: product | category | grounding | persona | memory |
multi-agent | MCP | platform | pricing | open-source | notable

## 2. Category deep dives
### 2a. Commercial personal-AI products
### 2b. Open-source personal-AI projects
### 2c. Agent frameworks (general-purpose)
### 2d. Memory systems
### 2e. Graph RAG / knowledge-graph systems
### 2f. Persona / oracle experiments
### 2g. Security / prompt-injection defenses

## 3. Architecture decisions — who chose what, and why
For each major architectural split, which products landed on which
side and the trade-offs observed

## 4. Top 10 things Donna should steal
Ranked by leverage/effort, with specific implementation notes

## 5. Top 10 things Donna should avoid
Patterns that look good but have proven problematic elsewhere

## 6. Donna's defensible niche
What is Donna uniquely good at that the field hasn't done well?

## 7. Open questions for the user
Things you couldn't resolve from desk research; would need to ask
the operator
```

## Donna context (so you have grounding for comparisons)

- **Deployment:** DigitalOcean $6 droplet, Docker compose, sops+age
- **Runtime:** Python 3.14, SQLite + sqlite-vec + FTS5, hand-rolled
  `anthropic` SDK, no agent framework
- **Platform:** Discord-only (single-user allowlist)
- **Modes:** chat (orchestrator agent loop with 17 tools), grounded
  (quoted_span validator + citation required), speculative (voice
  extrapolation with explicit labeling), debate (multi-turn
  transcript, orchestrator-wears-hats)
- **Security:** taint tracking, dual-call Haiku sanitization on all
  untrusted content, quoted_span validator with smart-quote
  normalization, consent gates, egress allowlist, overflow-to-artifact
  for tainted content
- **Memory:** `facts` (FTS5 + vec) for operational memory,
  `knowledge_sources` + `knowledge_chunks` for curated corpora
- **Retrieval:** hybrid semantic + FTS5 with RRF, diversity constraints
  (max 2 per work_id, max 3 per source_type), recency priors
- **Knowledge scope model:** flat `agent_scope` string (e.g.
  `"author_twain"`, `"orchestrator"`). Sibling project THINK plans
  to replace with attributed-knowledge-graph model.
- **Observability:** OpenTelemetry + Jaeger, cost ledger in SQLite,
  stuck-job watchdog with Discord DM alerts
- **Jobs:** durable SQLite-backed with lease + heartbeat + checkpoint,
  content-addressable artifacts
- **Compaction:** Haiku-summarization every N=20 tool calls, pre-
  compaction tail preserved as audit artifact

## Research targets

### Commercial personal-AI products (browse their sites + any product docs)

- **Poke** (poke.com or wherever it launched) — "your personal AI"
- **Friend** (friend.com) — wearable AI companion
- **Day.ai** — personal knowledge assistant
- **SANA** — enterprise personal AI
- **Rewind.ai** — personal memory / search
- **Limitless** (formerly Rewind) — pendant + AI
- **Granola** — meeting notes + personal context
- **Personal.ai** — personal language model
- **Mem.ai** — personal memory
- **Humane AI Pin** (if still shipping as of 2026)
- **Notebook LM** (Google) — upload-your-corpus + grounded QA

For each: what features? architecture (inferred from public material)?
who's the target user? what do they claim makes them different?

### Open-source personal assistants

- **LibreChat** (github.com/danny-avila/LibreChat) — multi-model UI
- **AnythingLLM** (mintplex-labs) — personal RAG chatbot
- **Open WebUI** (formerly ollama-webui) — personal chat interface
- **LocalAI** — drop-in OpenAI alternative, local
- **Khoj** — personal AI assistant, open-source
- **Flowise** — low-code LLM apps
- **Danswer** / **Onyx** — enterprise search + QA
- **PrivateGPT** — local-RAG
- **continue.dev** — personal coding copilot (for reference on
  operator-in-loop patterns)
- **mrsk** or similar solo-dev bot templates

### Agent frameworks (read README + architecture doc of each)

- **LangGraph** (langchain-ai/langgraph) v1.0+
- **CrewAI** (crewAIInc/crewAI)
- **Pydantic AI** (pydantic/pydantic-ai)
- **OpenAI Agents SDK** (openai/openai-agents-python)
- **Claude Agent SDK** (anthropics/claude-agent-sdk-python)
- **Nous Hermes Agent** (NousResearch/hermes-agent) — MCP-native
- **AutoGen** (microsoft/autogen) — multi-agent conversations
- **LlamaIndex Agents**
- **Semantic Kernel** (Microsoft)

For each, especially focus on:
- Primitive shape (workflow graph? ReAct loop? role-based?)
- State management (checkpointing, resumption, multi-run)
- Tool calling (static registry? dynamic? typed?)
- Observability hooks
- Which LLM providers supported + how abstracted
- Production readiness signals (who's using it? deployments?)

### Memory systems

- **Letta** (formerly MemGPT, letta-ai/letta) — memory manager layer
- **Mem0** (mem0ai/mem0) — memory-as-service
- **Zep** (getzep/zep) — temporal KG memory
- **Graphiti** (getzep/graphiti) — temporal knowledge graph
- **mnemostack** — OpenClaw community memory system

Feature focus: temporal fact versioning? semantic vs episodic memory?
retrieval strategy? forgetting curves? human-in-loop fact management?

### Graph RAG / knowledge-graph systems

- **Microsoft GraphRAG** (microsoft/graphrag)
- **LightRAG** (HKUDS/LightRAG)
- **HippoRAG 2** (OSU-NLP-Group/HippoRAG)
- **Cognee** (cognee-ai/cognee) — ontology-based
- **Neo4j GraphRAG** (neo4j-labs/llm-graph-builder)
- **LlamaIndex PropertyGraphIndex**

### Persona / oracle experiments

- **Character.ai** — persona chatbots at scale
- **Replika** — companion AI
- **Inflection Pi** — personal AI character
- LlamaIndex author-chatbot tutorials
- HuggingFace "digital twin" demos
- Any voice-cloning + RAG projects

What do these get right about voice/persona, and what do they miss
about grounding? Donna's positioning is "oracle, not scholar" —
constrained extrapolation based on documented patterns. Who else
has articulated this?

### Security / prompt-injection defenses

- **Simon Willison's writings** on the lethal trifecta (2025)
- **Google DeepMind CaMeL paper** — DSL + policy engine
- **UK NCSC assessment** — prompt injection formal paper (Dec 2025)
- **NVIDIA AI Red Team sandboxing guidance**
- **Anthropic's prompt injection papers**
- **OpenAI structured output + function calling** — implicit defense

### Content-analysis / fact-checking / media-literacy products

High-priority category because Donna is adding a `/validate` feature:
user sends an article / reel / video / post, gets back claims
extracted, verifiability assessed, red flags (emotional framing,
missing context, logical fallacies), counter-evidence against their
ingested corpora, suggested follow-up questions. Research:

- **Ground News** (ground.news) — media-bias comparison, blindspot
  analysis. How do they structure their critique output?
- **NewsGuard** (newsguardtech.com) — source credibility ratings
- **Kagi Assistant** / **Kagi Universal Summarizer** — query+critique
  over arbitrary URLs
- **Perplexity "Verify"** / Fact Check — live-web verification
- **AllSides** — bias-balanced coverage comparison
- **Factmata** / **Logically** / **Full Fact** — automated fact-check
  pipelines
- **Pudding visual critiques** / **Bellingcat OSINT tools** — long-form
  investigative analysis shape
- **Video/reel transcript extraction**: `yt-dlp`, `whisper.cpp`,
  AssemblyAI, Deepgram — architecture + pricing + quality trade-offs
  for a solo operator
- **Community notes (X/Twitter)** — the user-driven version of what
  `/validate` automates for the operator

For each: what's the claim-extraction shape? How do they handle bias
vs fact? How do they cite counter-evidence? What's the UX when
critique is longer than a screen? What's the pricing model for
solo-user tier?

### Notable related projects

- **Hermes Pattern A / B** — check Nous Research's MCP server exposure
  work since April 2026
- **OpenClaw** — Nov 2025 launch → 345k stars → 300+ malicious skills
  post-mortem. What did they ship? What did attackers exploit? What's
  the current state?

## Research methodology

For each target:

1. **Read the primary source** — GitHub repo, product site,
   documentation, release blog posts. Don't rely on secondary reviews.
2. **Capture architecture signals** — language, data store, deployment
   story, LLM abstraction, tool-calling shape, state management
3. **Capture feature set** — what does it claim to do? what actually
   works from hands-on reviews / demo videos / reddit threads?
4. **Capture pricing + business model** — solo-operator priced-out?
   team-priced? self-hostable?
5. **Capture post-mortems** — any known failures? controversy?
   scaling issues?
6. **Note what it doesn't do** — every product has a scope. Knowing
   what's out of scope is as useful as what's in.

Write up your findings as you go; don't try to synthesize from memory
at the end. Use Obsidian notes or the filesystem for scratch.

## Integration with Donna development

After the research is complete:

### Stage 1: initial report

Produce the deliverable spec'd above. Include in section 4 specific
file paths in the Donna codebase where changes would land for each
recommended steal.

### Stage 2: Codex review of your report

Once the report is drafted, feed it back to Codex with a prompt like:

```
You are reviewing this competitive landscape analysis for Donna v0.5
planning. The user has one Codex review already running on Donna's
architecture directly (see docs/CODEX_DEEP_DIVE.md in that repo).
Your job is to critique this MARKET research specifically:

1. Are the product claims accurate? Check against current 2026
   public documentation.
2. Are there competitors missing? Weight by relevance to Donna's
   specific use case (solo-operator, Discord-first, corpus grounded).
3. Are the "things Donna should steal" recommendations sound, or
   are they cargo-culting?
4. Are the "things to avoid" recommendations supported by specific
   post-mortems?
5. Does the "defensible niche" argument hold, or is it hand-waving?

Output: a diff/critique on the research doc, plus a revised top-5
recommendations list.
```

### Stage 3: compare with Donna session's Codex deep dive

The user will have run `docs/CODEX_DEEP_DIVE.md` in parallel on the
Donna repo side. Those two Codex reviews are independent — one is
internal-facing (how Donna is built), one is external-facing (how
Donna compares). Compare the top-N recommendations from each:

- Items appearing in BOTH reviews → high priority for v0.5
- Items only in internal review → Donna-specific hygiene
- Items only in external review → strategic positioning choices

Output a final "v0.5 plan" synthesis that draws on both.

### Stage 4: hand off to Donna session

Paste the v0.5 plan into the Donna cloud session's opening prompt
(see `docs/NEXT_SESSION_DONNA.md` in the Donna repo). That session
is the one that executes the plan; this session is the one that
MAKES the plan.

## Rules

1. **Browser access required.** If you don't have it, stop and tell
   the user to run this session somewhere with web access.
2. **Cite sources.** Every claim about a competitor should link to
   the primary source (doc URL, GitHub repo, blog post).
3. **Respect currency.** April 2026 landscape. Things shipped in
   2024 are history; things shipped in 2026 Q1 are current.
4. **Be honest about gaps.** If a competitor's architecture isn't
   publicly documented, say so. Don't invent details.
5. **Focus on actionable findings.** Every "Donna should steal X"
   recommendation needs a specific implementation path in Donna's
   current codebase.

## Time budget

Expect 3-6 hours of focused research. This is the most important
research artifact of the v0.5 planning cycle — don't rush it.
