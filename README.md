# Donna

A personal AI assistant bot. Always-on Discord, runs on a DigitalOcean droplet, powered by Claude.

**Scope:** solo-user, single-droplet, foundation-first. Designed to grow into multi-specialist agents with scoped knowledge bases.

See [`docs/PLAN.md`](docs/PLAN.md) for the full architectural plan.

## Quick start (local dev)

**Fresh laptop, continuing prior work?** Open [`docs/CONTINUE_HERE.md`](docs/CONTINUE_HERE.md) and paste its bootstrap prompt into Claude Code.

**Just setting up?** Follow [`docs/LIVE_RUN_SETUP.md`](docs/LIVE_RUN_SETUP.md) for the full walkthrough including account provisioning and smoke tests. The short version:

```powershell
# Windows (PowerShell)
git clone https://github.com/GlobalCan/donna.git C:\dev\donna
cd C:\dev\donna
.\scripts\setup_local.ps1     # idempotent: venv + deps + migrations + tests
notepad .env                   # fill in 6 required keys (see LIVE_RUN_SETUP.md §2)

# Terminal 1
.\.venv\Scripts\Activate.ps1
python -m donna.main

# Terminal 2
.\.venv\Scripts\Activate.ps1
python -m donna.worker
```

```bash
# Linux/macOS (no bootstrap script yet; follow LIVE_RUN_SETUP.md manually)
git clone https://github.com/GlobalCan/donna.git
cd donna
python3.14 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env && $EDITOR .env
alembic upgrade head
pytest                         # expect 60 passed
python -m donna.main           # Terminal 1
python -m donna.worker         # Terminal 2
```

## Production (droplet)

See [`scripts/harden-droplet.sh`](scripts/harden-droplet.sh) and `docker-compose.yml`.

Deploy pipeline: GitHub push → GitHub Actions builds + signs image → pushes to GHCR → droplet systemd timer pulls → container restarts.

## Layout

```
src/donna/
  adapter/       Discord gateway + slash commands + reactions + threads
  agent/         Agent loop, prompt composition, model tier routing
  tools/         @tool decorator + v1 tools (web, memory, artifacts, exec, knowledge)
  memory/        SQLite primitives: facts, artifacts, knowledge, permissions
  security/      Taint tracking, dual-call sanitization, consent, grounding validator
  jobs/          Durable job runner with lease/heartbeat/checkpoint + cron scheduler
  ingest/        URL/PDF/text → chunk → dedupe → embed → store
  modes/         Grounded, speculative, debate
  observability/ OpenTelemetry + cost ledger
  cli/           botctl ops CLI
```

## Principles

- **Foundation first** — v1 is one agent; every infra piece gold-plated so specialists slot in later
- **Hand-rolled** — direct `anthropic` SDK, no framework. V1 is Anthropic-shaped; the `AnthropicAdapter` class is a boundary, not a vendor-agnostic protocol (be honest about this until we need OpenAI).
- **Strictly personal** — hardcoded Discord user allowlist. `agent_scope` is for per-persona knowledge isolation (e.g. `author_lewis` vs. `author_dalio`), **not** multi-tenancy.
- **Agent-first, unified execution** — every mode (chat / grounded / speculative / debate) shares the same `JobContext` primitives: model step, tool step, consent wait, checkpoint, compact, finalize.
- **Structural safety** — taint tracking (pre-scan before parallel tool batches) + dual-call sanitization on all untrusted content (fetch_url, search snippets, attachments) + citation-validated grounding with verbatim quoted-span requirement + egress allowlist.
- **Cron-only triggers in v1** — explicit, inspectable, operator-authored. Watchers/reflections/self-scheduled deferred; when they land they'll have their own queue + dedupe key, not just "another schedule source."

## Status

**v0.3.3** · Python 3.14 · 102 tests green · **live in production on DO**, fully smoke-tested, three-layer backups live, Jaeger traces, all 9 Codex adversarial-scan findings closed.

- Foundation built and survived three Codex review passes (defect, adversarial
  challenge, Hermes comparison)
- Unified execution graph (`JobContext`), persistent consent, taint tracking on
  every untrusted path, quoted-span grounded validator
- ModelRuntime registry (vendor abstraction as data, not slogan)
- Compaction audit trail preserves pre-compaction history as artifact
- Stuck-job watchdog + cache-hit rate telemetry
- **Phase 1 local end-to-end pass** against real Anthropic / Discord / Tavily /
  Voyage APIs (2026-04-22)
- **Phase 2 production deploy to DigitalOcean** (2026-04-23) — hardened Ubuntu
  droplet (`bot` user + ufw + fail2ban + unattended-upgrades), Docker compose
  bot + worker, sops+age encrypted secrets, SQLite at `/data/donna/donna.db`,
  `ghcr.io/globalcan/donna:latest` pulled from GHCR. All four smoke tests green
  against the live deploy.
- **Current limitations:** Phoenix observability temporarily disabled (upstream
  image broken 2026-04-23); auto-deploy timer not yet enabled; no off-droplet
  backups yet.

**Next planned addition:** extract the knowledge / retrieval / graph-RAG layer
into a sibling `src/think/` package inside this monorepo. The oracle mode
("what would Michael Lewis say about X?") and cross-author synthesis ("where
do Lewis and Dalio overlap?") are the target use cases. See
`docs/THINK_BRIEF.md` for the full bootstrap brief.

**History:** see `CHANGELOG.md` for the full v0.1.0 → v0.2.0 evolution.
