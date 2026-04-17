# Donna

A personal AI assistant bot. Always-on Discord, runs on a DigitalOcean droplet, powered by Claude.

**Scope:** solo-user, single-droplet, foundation-first. Designed to grow into multi-specialist agents with scoped knowledge bases.

See [`docs/PLAN.md`](docs/PLAN.md) for the full architectural plan.

## Quick start (local dev)

```bash
# 1. Clone + install
git clone git@github.com:GlobalCan/donna.git
cd donna
python3.12 -m venv .venv && . .venv/Scripts/activate  # Windows
# or:  source .venv/bin/activate                      # Linux/macOS
pip install -e ".[dev]"

# 2. Copy env template, fill in keys
cp .env.example .env
# edit .env with your Anthropic / Discord / Tavily / Voyage keys

# 3. Run migrations
alembic upgrade head

# 4. Smoke test (no live APIs)
pytest tests/

# 5. Run the bot (requires real keys)
python -m donna.main          # Discord adapter + orchestrator
# in another terminal:
python -m donna.worker        # job worker
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

v1 foundation — under active initial build.
