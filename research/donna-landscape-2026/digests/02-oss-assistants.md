# OSS Self-Hosted AI Assistants / Chat UIs / RAG Stacks — digest

## Per-product table

| product | one-line | arch (lang/store/llm/tool/state) | pricing | self-host | notable | source |
|---|---|---|---|---|---|---|
| LibreChat | Multi-user ChatGPT-style UI w/ agents, MCP, RAG | TS / Mongo+Redis+Meili / multi-provider+OAI-compat / MCP+Agents Marketplace / per-conversation, no persistent semantic memory | MIT; optional paid Code Interpreter add-on | Docker/compose; Railway/Zeabur | Multi-tenant default adds friction for solo; 4,059 commits; active | https://github.com/danny-avila/LibreChat |
| AnythingLLM | All-in-one desktop+Docker doc workspaces + no-code agents | JS / LanceDB default + 8 swappable + SQLite metadata / 30+ providers / no-code agent builder + MCP / workspace chat+RAG, no operator memory | MIT; hosted Cloud exists | Desktop binaries (solo) + Docker (multi-user) | "Skill Selection" claims 80% token reduction; v1.12.1 2026-04-22 | https://github.com/Mintplex-Labs/anything-llm |
| Open WebUI | Polished Ollama/OAI-compat chat UI w/ pipelines+RAG | Py+Svelte / SQLite/PG + 9 vector backends / Ollama-first+OAI-compat / Pipelines+native funcs+MCP+artifact KV / per-conv + opt-in flat "Memories" | Custom "Open WebUI License" (NOT OSI) since Apr 2025; CLA required; 50-user branding wall | Docker/pip/Helm | License pivot drew HN backlash; v0.9.2 2026-04-24 | https://github.com/open-webui/open-webui |
| LocalAI | Self-host OAI/Anthropic-compat inference engine — substrate, not assistant | Go / none (PG+NATS in distributed mode) / 36+ backends (llama.cpp, vLLM, MLX...) / OAI tools+MCP / none, inference only | MIT | Single binary, Docker (CPU/CUDA/ROCm/Vulkan/Apple), P2P | Drop-in API replacement; v4.1.3 2026-04-06 | https://github.com/mudler/LocalAI |
| Khoj | Self-host "AI second brain" over notes/Notion/Obsidian | Py+TS / Postgres+pgvector / Llama/Qwen/OAI/Claude/Gemini / agents+web+deep research; MCP unconfirmed / long-term memory in v2.0.0-beta.25 (buggy) | AGPL-3.0; cloud subscription | Docker, desktop, Obsidian/Emacs plugins | Only entry advertising long-term memory; perpetual beta; AGPL constrains forks | https://github.com/khoj-ai/khoj |
| Flowise | Drag-and-drop visual builder for LangChain agents+RAG | TS / SQLite default + swap + user vector DB / LangChain providers / visual nodes incl. Tool/Func/MCP / per-flow memory nodes | Apache-2.0; Cloud exists | npm/Docker, AWS/Azure/GCP/HF Spaces | Visual paradigm hits complexity wall ~20 nodes; v3.1.2 2026-04-14 | https://github.com/FlowiseAI/Flowise |
| Onyx (ex-Danswer) | OSS enterprise search + AI assistant, 50+ connectors | Py+TS / PG+Vespa+Redis+MinIO (Lite mode <1GB) / Anthropic/OAI/Gemini+Ollama/LiteLLM/vLLM / Custom Agents+MCP+connectors-via-MCP / per-user chat, agent-scoped knowledge | MIT Community + Enterprise Edition + Cloud (free tier) | Docker one-line; k8s/Helm/Terraform | YC-backed $10M seed Mar 2025; team-first; v3.2.11 2026-04-24 | https://github.com/onyx-dot-app/onyx |
| PrivateGPT | LlamaIndex offline RAG-over-docs reference | Py / Qdrant default + SQLite / LlamaCPP/Ollama/OAI/Azure/Gemini/SageMaker/vLLM / none / chat history only | Apache-2.0; commercial successor Zylon | Docker, Gradio, local Py | STALE: v0.6.2 2024-08-08, 18+ months old; team moved to Zylon | https://github.com/zylon-ai/private-gpt |
| continue.dev | OSS IDE coding assistant pivoting to CLI+CI agent platform | TS+Kotlin+Rust+Py / local `.continue/` + workspace indices / pluggable / MCP Registry + markdown-defined agents in `.continue/checks/` / per-repo, no global memory | Apache-2.0; Continue Hub | VS Code+JetBrains+CLI | Source-controlled markdown agent specs; v1.2.22-vscode 2026-03-27 | https://github.com/continuedev/continue |

## Three patterns to steal

1. **Source-controlled, markdown-defined agent specs.** (a) Agents/policies stored as markdown in repo, diffable and reviewable via PR. (b) continue.dev (`.continue/checks/`). (c) Donna's tenets call for legible operator-controlled behavior; markdown specs match the solo-coder design center and let operators version Donna's procedural memory in git. (d) https://github.com/continuedev/continue
2. **Desktop-app distribution for clean solo trust boundary.** (a) Ship a single-user desktop binary that skips multi-tenant auth scaffolding entirely. (b) AnythingLLM Desktop, Khoj-Obsidian. (c) Donna is solo-operator first / single trust boundary; default-auth installs (LibreChat/Onyx/OWUI) impose team friction Donna's user pays for nothing. (d) https://github.com/Mintplex-Labs/anything-llm
3. **Protocol-mimicry inference layer (OpenAI + Anthropic API drop-in).** (a) Expose stable upstream APIs so the assistant can swap model substrates without UI changes. (b) LocalAI. (c) Donna's "self-host / local-friendly + cloud LLM allowed" tenet needs swap-out flexibility; layering Donna over a LocalAI-style routing tier preserves it. (d) https://github.com/mudler/LocalAI

## Three patterns to avoid

1. **CLA + restrictive license pivot on a popular OSS chat UI.** (a) BSD/MIT → source-available with branding wall + mandatory CLA. (b) Open WebUI (Apr 2025 license change). (c) Erodes contributor trust; Donna should pre-commit a license stance. (d) https://github.com/open-webui/open-webui — license documented in primary-source repo; HN/Lobsters threads referenced in raw but direct fetches returned 403, so this is the only verifiable post-mortem link in the raw file.

(Other candidates — Flowise visual-canvas debuggability, Khoj perpetual-beta memory, LibreChat/Onyx default-multi-tenant friction — are flagged in the raw file but without a specific post-mortem URL, so per the rules they are dropped.)

## Cross-cutting observations

- MCP is table stakes (LibreChat, AnythingLLM, OWUI, LocalAI, Onyx, continue.dev, Flowise); not differentiating.
- Memory is an afterthought everywhere except Khoj (whose subsystem is buggy); nobody documents temporal versioning or episodic/semantic/procedural separation.
- Zero competitors surface intent-of-claim ("oracle vs scholar") labeling.
- Multi-user posture leaks into solo installs (LibreChat, Onyx, OWUI, AnythingLLM-Docker).
- LocalAI is the only pure inference substrate; others conflate routing+UI+state+tools.

## Unresolved

- Khoj 2.0.0-beta.28 release date (2025 vs 2026) — cadence implies 2026 but unconfirmed; matters for staleness flag.
- Khoj self-host datastore not confirmed in primary source (docs returned 403); pgvector inferred from community.
- AnythingLLM app-metadata datastore (SQLite) not in README excerpt; inferred from prisma layout.
- LibreChat persistent cross-conversation memory in v0.7.x — not surfaced in README.
- Onyx Cloud / Enterprise pricing not on README; Flowise Cloud pricing likewise.
- continue.dev current LLM provider list not enumerated in fetched content.
- OWUI "Memories" storage shape (vector/KV/scoped) — docs site 403-blocked.
- HN/Lobsters threads on OWUI license — direct fetches returned 403; relied on secondary summary, weakening the post-mortem citation.
