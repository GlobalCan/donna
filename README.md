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

**v0.4.4** · Python 3.14 · 381 tests green · **live in production on DO**, grounded mode end-to-end validated, unified mode delivery, overflow-to-artifact security pattern, three-layer backups live, Jaeger traces, mobile-friendly Discord rendering, session memory across DM threads (including tainted-with-warning rendering for web-tool exchanges), **scheduler smoke-tested live end-to-end**.

- Foundation built and survived four Codex review passes (defect, adversarial
  challenge, Hermes comparison, round-2 same-class hunt) plus one self-run
  adversarial+polish sweep — plus the **2026-04-29 cross-vendor review pass**
  (Claude Opus 4.7 + Codex GPT-5 + Codex GPT-5.3-codex), seven follow-up PRs
  shipped in v0.4.1, four "feels like it works" fixes in v0.4.2, and three
  v0.4.3 fixes for shipping bugs the first live scheduler smoke test surfaced
  (delivery `thread_id` propagation, plain-DM memory dedup, entrypoint
  auto-migrate)
- Unified execution graph (`JobContext`), persistent consent, taint tracking on
  every untrusted path, quoted-span grounded validator with smart-quote +
  Unicode NFC normalization (content-strict, rendering-tolerant)
- **Internal retrieval taint propagation** — every mode handler (chat, grounded,
  speculative, debate) flips `ctx.state.tainted` when retrieved chunks come
  from tainted sources. Closes the most-actionable security gap from the
  cross-vendor review.
- **Session memory** — chat mode injects last-8 messages from the same Discord
  thread as a `## Prior conversation` block in the volatile prompt. Tainted
  jobs don't pollute clean future jobs' context.
- **Mobile-friendly Discord rendering** — 1400-char chunks (was 1900) hit the
  thumb-scroll sweet spot on iOS portrait. `_normalize_for_mobile` collapses
  blank-line runs and strips trailing whitespace on the inline path.
- **Eval ratchet** — `tests/test_evals_smoke.py` is now a CI gate over the
  golden suite. Tri-state PASS / FAIL / SKIP. Tainted-corpus regressions
  flip the suite red.
- **Unified mode delivery** — grounded / speculative / debate all write to
  `outbox_updates` atomically with the DONE status flip inside
  `JobContext.finalize()`. Mode-resume short-circuit prevents double-execution
  on lease-loss recovery.
- **Overflow-to-artifact** — long answers split to multi-part Discord messages
  up to a cap; past it, full text → artifact, Discord gets a 📎 pointer + preview
  + `botctl artifact-show <id>`. Tainted content uses a much tighter cap so
  attacker output doesn't flood scrollback.
- **Grounded mode robustness** — parser absorbs markdown code fences, preamble
  text, and postamble commentary; renders `prose` field as the user-visible
  answer (not raw JSON); validator reports single `malformed_json` on
  unparseable input instead of split-on-period noise
- ModelRuntime registry (vendor abstraction as data, not slogan)
- Compaction audit trail preserves pre-compaction history as artifact
- Stuck-job watchdog + cache-hit rate telemetry + cost-ledger concurrency
  invariants pinned
- Full `botctl` surface: jobs / job / cost / cache-hit-rate / teach / artifacts
  / artifact-show / forget-artifact / heuristics (list | approve | retire) /
  schedule / traces / migrate
- **Phase 1 local end-to-end pass** against real Anthropic / Discord / Tavily /
  Voyage APIs (2026-04-22)
- **Phase 2 production deploy to DigitalOcean** (2026-04-23) — hardened Ubuntu
  droplet (`bot` user + ufw + fail2ban + unattended-upgrades), Docker compose
  bot + worker, sops+age encrypted secrets, SQLite at `/data/donna/donna.db`,
  `ghcr.io/globalcan/donna:latest` pulled from GHCR
- **Phase 3 grounded-mode end-to-end** (2026-04-24) — real `/ask` query against
  the 402-chunk Huck Finn corpus returning clean prose with `✅ validated`
  badge and multi-chunk citation
- **Phase 4 scheduler end-to-end** (2026-04-30) — `/schedule * * * * *`
  → `• SCHED_OK` arrives in DM after the v0.4.3 fix; closes a v0.2.0+
  shipping bug where every scheduled job ran but had no Discord
  destination.
- **Current limitations:** Phoenix observability disabled (upstream image
  broken); auto-deploy timer not yet enabled; no off-droplet backups yet (DO
  snapshots + droplet cron + laptop→OneDrive are the three layers); speculative
  and debate modes never smoke-tested in prod.

**Next planned addition:** extract the knowledge / retrieval / graph-RAG layer
into a sibling `src/think/` package inside this monorepo. The oracle mode
("what would Michael Lewis say about X?") and cross-author synthesis ("where
do Lewis and Dalio overlap?") are the target use cases. See
`docs/THINK_BRIEF.md` for the full bootstrap brief.

**History:** see `CHANGELOG.md` for the full v0.1.0 → current evolution.
