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
