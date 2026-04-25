# OSS Self-Hosted AI Assistants / Chat UIs / RAG Stacks — Donna Landscape 2026

Research date: 2026-04-25
Category: Open-source self-hosted AI assistants, chat UIs, and RAG stacks — Donna's most direct architectural neighbors.

Each entry follows the rubric defined in DONNA_CONTEXT.md: primary-source URL, what-it-is, architecture signals, feature set, license/pricing/self-host, known issues, scope gaps, and currency flags.

## LibreChat

- Primary source: https://github.com/danny-avila/LibreChat ; docs https://www.librechat.ai
- One-liner: A multi-user, ChatGPT-style web UI that fronts many LLM providers with agents, MCP tools, RAG, and a marketplace.
- Architecture signals:
  - Language: TypeScript/JavaScript (~76% TS).
  - Datastore: MongoDB (primary), Redis (resumable streams, horizontal scale), Meilisearch for search.
  - LLM abstraction: Anthropic, OpenAI (incl. Responses API), Azure OpenAI, AWS Bedrock, Google Vertex AI, Groq, DeepSeek, Mistral, Qwen, plus any OpenAI-compatible endpoint (Ollama, OpenRouter, Together, Perplexity).
  - Tool shape: MCP supported ("Model Context Protocol (MCP) Support for Tools"), plus a LibreChat Agents framework with an "Agent Marketplace."
  - State/memory: Per-conversation; conversation forking/editing; resumable streams; no first-class persistent semantic memory documented.
  - Deployment: Docker / docker-compose primary; Railway/Zeabur/Sealos templates; single-server or horizontally scaled.
- Feature set: ChatGPT-parity UX, file/image attachments, code interpreter (paid add-on), web search, agents w/ MCP — all present in the README and docs.
- License/pricing: MIT. Self-hostable. Optional paid "Code Interpreter API" add-on. No hosted SaaS. Solo-operator viable but oriented toward team auth (multi-user, OAuth, LDAP).
- Known issues: 256 open issues / 151 PRs; multi-tenant orientation introduces friction for single-user installs (auth required by default). MongoDB is heavyweight for solo use.
- Scope gaps: No native long-term semantic/episodic memory store, no temporal versioning of facts, no claim-level provenance UI, no constrained-extrapolation labeling. RAG is per-conversation file attach rather than a curated knowledge graph.
- Currency: 4,059 commits on main, marked Active as of April 2026; recent README references current. (Source: GitHub repo page, fetched 2026-04-25.)

## AnythingLLM (Mintplex Labs)

- Primary source: https://github.com/Mintplex-Labs/anything-llm ; product https://anythingllm.com
- One-liner: An all-in-one desktop + Docker app that turns documents into chat-ready "workspaces" with no-code agents and broad provider support.
- Architecture signals:
  - Language: JavaScript (~98%); Vite+React frontend, Node.js Express server, separate document-collector service.
  - Datastore: LanceDB default; PGVector, Pinecone, Chroma, Weaviate, Qdrant, Milvus, Zilliz, Astra DB swappable. SQLite for app metadata (per Docker docs).
  - LLM abstraction: OpenAI, Anthropic, Gemini, Ollama, LM Studio, LocalAI, AWS Bedrock, Azure OpenAI, "30+" providers. Embedders pluggable likewise.
  - Tool shape: "AI Agent builder" (no-code), MCP-compatible per README; "Intelligent Skill Selection" claims up-to-80% token reduction.
  - State/memory: Workspace-scoped chat history + RAG index; no first-class persistent operator-memory layer documented.
  - Deployment: Desktop binaries (Mac/Win/Linux) for solo use; Docker for multi-user; one-click on AWS/GCP/DO/Render/Railway.
- Feature set: PDF/TXT/DOCX/URL ingestion, multi-user perms (Docker only), web browsing agent skill, MCP tool calls, embed widget. v1.12.1 released 2026-04-22.
- License/pricing: MIT. Self-host free; hosted "AnythingLLM Cloud" exists. Solo-operator viable via desktop app (single trust boundary).
- Known issues: 304 open issues; LanceDB has had reindex/corruption reports historically; multi-user perms only on Docker not desktop.
- Scope gaps: No temporal fact versioning, no constrained-extrapolation labeling, RAG-centric (no episodic/procedural memory split), tool sandboxing/prompt-injection posture not documented as a first-class concern.
- Currency: v1.12.1 dated 2026-04-22 — current.

## Open WebUI (formerly Ollama WebUI)

- Primary source: https://github.com/open-webui/open-webui ; docs https://docs.openwebui.com
- One-liner: A polished, batteries-included chat UI for Ollama and OpenAI-compatible models, with pipelines, RAG, and a function/tool plugin model.
- Architecture signals:
  - Language: Python (~35%) + Svelte (~33%) + JS/TS.
  - Datastore: SQLite (default, optionally encrypted), PostgreSQL, S3/GCS/Azure Blob for files; 9 vector backends (ChromaDB default, PGVector, Qdrant, Milvus, Elasticsearch, OpenSearch, Pinecone, S3Vector, Oracle 23ai).
  - LLM abstraction: Ollama-first, plus any OpenAI-compatible API (LM Studio, Groq, Mistral, OpenRouter). Image-gen via DALL-E, Gemini, ComfyUI, A1111.
  - Tool shape: "Pipelines" (Python plugin framework), "Native Python Functions" (BYOF), and MCP integration. "Persistent Artifact Storage" key-value API exposed to functions.
  - State/memory: Per-conversation by default; an opt-in "Memories" feature exists for persistent user facts; artifact KV store available to plugins.
  - Deployment: Docker (multiple image variants incl. `:cuda`, `:ollama`), `pip install open-webui` single-process, Helm/Kustomize for k8s.
- Feature set: Multi-user auth, RBAC, RAG with multiple extractors (Tika, Docling), image gen, web search, voice, MCP tools — all in v0.9.2 (2026-04-24).
- License/pricing: Custom "Open WebUI License" (NOT OSI open source) since April 2025. Branding-preservation requirement kicks in at 50+ users; below that, full rebrand allowed. Enterprise license required to remove branding at scale. CLA mandatory for contributions.
- Known issues: License change drew significant Hacker News / Lobsters backlash (HN thread 43901575, Nov 2025 BigGo coverage), with calls for forks. The Onyx team published a comparison page targeting Open WebUI users.
- Scope gaps: Memory feature is shallow (flat user notes, no temporal versioning), no claim-level provenance, no constrained-extrapolation labeling, no first-class prompt-injection sandbox model.
- Currency: v0.9.2 dated 2026-04-24 — current.

## LocalAI

- Primary source: https://github.com/mudler/LocalAI ; docs https://localai.io
- One-liner: A self-hostable, OpenAI-/Anthropic-API-compatible inference engine with 36+ model backends — *not* an assistant, an LLM substrate.
- Architecture signals:
  - Language: Go (~67%), with JS/Python/HTML/C++ helpers.
  - Datastore: None inherent (inference layer); distributed mode uses PostgreSQL + NATS.
  - LLM abstraction: backends include llama.cpp, vLLM, transformers, whisper.cpp, diffusers, MLX, MLX-VLM, etc.
  - Tool shape: OpenAI-compatible tools/function calling; MCP support (both server-side "MCP Apps" and client).
  - State/memory: None — inference only. Memory is the caller's problem.
  - Deployment: Single binary, Docker (CPU/CUDA/ROCm/Vulkan/Apple), macOS DMG, P2P inferencing mode for distributed inference.
- Feature set: Drop-in OpenAI/Anthropic API replacement, multimodal, audio (TTS/STT), embeddings, image gen.
- License/pricing: MIT. Fully self-hosted. Solo-operator viable as the model-routing layer behind a UI/agent.
- Known issues: Model-config sprawl historically; backend explosion makes "what works on my GPU" non-trivial.
- Scope gaps: Not an assistant — no memory, no agent loop, no UI for ingestion. Fine as Donna's inference target; not a Donna competitor.
- Currency: v4.1.3 dated 2026-04-06 — current.

## Khoj

- Primary source: https://github.com/khoj-ai/khoj ; docs https://docs.khoj.dev
- One-liner: A self-hostable "AI second brain" — chat over your notes/PDFs/Notion/Obsidian/org-mode, with custom agents, scheduling, and (recent) long-term memory.
- Architecture signals:
  - Language: Python (~50%) + TypeScript (~36%); Emacs Lisp + Obsidian plugin clients.
  - Datastore: PostgreSQL with pgvector is documented as the standard backend for self-host; SQLite paths exist historically but pgvector is recommended (per docs.khoj.dev — direct fetch returned 403 during this scan, see currency note).
  - LLM abstraction: Llama, Qwen, Gemma, Mistral via Ollama; OpenAI, Claude, Gemini, DeepSeek cloud.
  - Tool shape: Agents with custom persona/tools/knowledge; web search; deep research mode. MCP support not explicitly confirmed in README.
  - State/memory: Long-term memory introduced in v2.0.0-beta.25 ("Introduced long-term memory capabilities for persistent context") — a real persistent-memory layer, though architecture details aren't in release notes.
  - Deployment: Docker (multiple Dockerfiles), desktop, browser, Obsidian/Emacs plugins; cloud at app.khoj.dev.
- Feature set: Document ingestion (PDF/MD/Notion/DOCX/org), chat over docs, custom agents, scheduled automations, deep research, long-term memory.
- License/pricing: AGPL-3.0. Self-host free. Cloud subscription with student/academic rates (specific tiers not enumerated on GitHub front page).
- Known issues: Beta-track for >12 months (still 2.0.0-beta.X); recent fixes around "memory loading" bugs, "memory leaks in org-mode," "research agent stopping prematurely" in beta.26 — points to real but rough memory subsystem.
- Scope gaps: No claim-level provenance UI, no temporal versioning of facts, no constrained-extrapolation labeling, AGPL is a redistribution constraint for any future Donna fork-and-modify.
- Currency: 2.0.0-beta.28; date reported as either 2025-03-26 or 2026-03-26 across sources (releases page summary said 2025; repo card said 2026). FLAG: cannot fully resolve without GitHub API access; likely 2026 given the beta cadence.

## Flowise

- Primary source: https://github.com/FlowiseAI/Flowise ; product https://flowiseai.com
- One-liner: Drag-and-drop visual builder for LangChain-style agents and RAG pipelines.
- Architecture signals:
  - Language: TypeScript (~60%) + JavaScript; React frontend, Node backend, monorepo.
  - Datastore: SQLite default for app metadata; can swap to MySQL/Postgres (per docs); user-supplied vector DB (Chroma, Pinecone, Qdrant, etc.).
  - LLM abstraction: Inherits LangChain/LangChain.js provider list — OpenAI, Anthropic, Cohere, Ollama, HF, Vertex, Bedrock.
  - Tool shape: Visual nodes; Tool/Function/MCP nodes exist in v3.x (per release notes outside the README excerpt).
  - State/memory: Per-flow memory nodes (Buffer, Window, Summary, Vector-store backed); not a unified persistent operator memory.
  - Deployment: `npm i -g flowise && npx flowise start`, Docker, AWS/Azure/GCP/Render/Railway/HF Spaces.
- Feature set: Visual flow editor, agent + multi-agent canvas, embeddable chat widget, API endpoints per flow.
- License/pricing: Apache-2.0 source; "Flowise Cloud" hosted offering exists (pricing not on README).
- Known issues: Visual-flow paradigm hits a complexity wall fast; debuggability of canvas-built agents is a known pain point in issues.
- Scope gaps: Aimed at non-technical builders making team chatbots — opposite of Donna's solo-operator-coder design center. No memory model that meets episodic+semantic+procedural with temporal versioning. No "oracle vs scholar" labeling.
- Currency: flowise@3.1.2 dated 2026-04-14 — current.

## Onyx (formerly Danswer)

- Primary source: https://github.com/onyx-dot-app/onyx ; product https://onyx.app
- One-liner: Open-source enterprise-search + AI assistant platform with 50+ connectors, agents, MCP — formerly Danswer; YC-backed, $10M seed (Mar 2025, TechCrunch).
- Architecture signals:
  - Language: Python (~64%) + TypeScript (~30%); Next.js frontend.
  - Datastore: PostgreSQL + Vespa (vector + keyword index, per project history) + Redis + MinIO (blob). "Lite Mode" reduces this to <1GB memory.
  - LLM abstraction: Anthropic, OpenAI, Gemini cloud; Ollama, LiteLLM, vLLM self-host.
  - Tool shape: "Custom Agents" + "Actions & MCP" — first-class MCP support including connectors-via-MCP.
  - State/memory: Per-user chat history; agent-scoped knowledge sets; not a unified persistent-memory layer like Khoj's.
  - Deployment: Docker / one-line installer (`curl https://onyx.app/install_onyx.sh | bash`); k8s/Helm/Terraform for prod.
- Feature set: 50+ connectors (Slack, Confluence, GDrive, Notion, GitHub, etc.), web search, deep research, RAG, agents, MCP, SSO/RBAC in Enterprise.
- License/pricing: MIT (Community Edition); separate Enterprise Edition + Onyx Cloud (free tier exists, pricing not on README). Multi-tenant orientation in Enterprise.
- Known issues: Heavyweight stack (Vespa+Postgres+Redis+MinIO) is overkill for solo. Rebrand from Danswer in 2024 caused some link rot; old `danswer-ai/danswer` repo no longer canonical.
- Scope gaps: Built for teams ("connect company documents, applications, and people"); solo-operator features are an afterthought. No temporal fact versioning, no constrained-extrapolation labeling, no claim-level provenance UI.
- Currency: v3.2.11 dated 2026-04-24 — current.

## PrivateGPT

- Primary source: https://github.com/zylon-ai/private-gpt ; commercial https://zylon.ai
- One-liner: A LlamaIndex-based, fully offline RAG-over-your-docs reference implementation; the OG of the "your data never leaves" wave.
- Architecture signals:
  - Language: Python (~76%); FastAPI server + LlamaIndex.
  - Datastore: Qdrant default (vector); abstraction layer for swapping; SQLite/local file metadata.
  - LLM abstraction: LlamaCPP, Ollama, OpenAI, Azure OpenAI, Gemini, AWS SageMaker, vLLM.
  - Tool shape: None to speak of — high-level RAG API + low-level chunk-retrieval API; no agents, no MCP.
  - State/memory: None beyond chat history; pure RAG.
  - Deployment: Docker, Gradio UI client, local Python.
- Feature set: Document ingest, chat-over-docs, embeddings API, contextual retrieval API.
- License/pricing: Apache-2.0. Commercial successor is Zylon (zylon.ai).
- Known issues: Last release v0.6.2 dated 2024-08-08 — over 18 months stale as of April 2026. 264 open issues, repo activity has shifted to the commercial Zylon product. FLAG: effectively maintenance-mode.
- Scope gaps: No agents, no tools, no MCP, no persistent memory, no provenance UI. Useful only as a RAG reference; superseded for any active deployment.
- Currency: STALE — last release 2024-08-08; >18 months old.

## continue.dev

- Primary source: https://github.com/continuedev/continue ; product https://continue.dev
- One-liner: Originally an open-source IDE coding assistant (VS Code + JetBrains); has pivoted into a CLI + CI agent platform with markdown-defined "checks."
- Architecture signals:
  - Language: TypeScript (~84%) + Kotlin (JetBrains plugin) + Rust + Python.
  - Datastore: Local config in `.continue/`; per-workspace indices.
  - LLM abstraction: Provider-pluggable (OpenAI, Anthropic, Ollama, etc. — historical list, not in current README excerpt).
  - Tool shape: MCP Registry referenced; agents defined as markdown files in `.continue/checks/`; CI integration runs them as PR status checks.
  - State/memory: Per-repo, per-workspace; no global operator memory.
  - Deployment: VS Code + JetBrains extensions, CLI installer (bash/PowerShell/npm).
- Feature set: Code completion, chat, agent-mode edits, source-controlled prompts and policies, CI-integrated review checks.
- License/pricing: Apache-2.0. Hosted Continue Hub for sharing configs.
- Known issues: Pivot away from pure IDE assistant toward CI-policy product reportedly upset some original users; fragmentation between VSCode/JetBrains release cadences (latest tag is `v1.2.22-vscode`, 2026-03-27).
- Scope gaps: Coding-domain only. No general personal assistant role, no document ingestion, no persistent semantic memory, no oracle/scholar distinction. Adjacent to Donna only as a model for *source-controlled, markdown-defined* agent specs — a pattern Donna could borrow.
- Currency: v1.2.22-vscode dated 2026-03-27 — current; 822 total releases (per repo).
