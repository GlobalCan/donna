# PHASE_1_ARCHITECTURE.md

**Status:** Locked v1.0.1 · 2026-05-10
**Companion to:** PATH_3_INVARIANTS.md v0.3.2 (the spec); this is the tooling lock for Phase 1 build.
**Governance:** tooling decisions DO NOT require §23 invariant-change governance; they may evolve via PR + soak. Numbered invariants in PATH_3_INVARIANTS take precedence over any picks here.

---

## 0. Purpose

PATH_3_INVARIANTS defines what must be true. This document defines what we are using to make it true in Phase 1. Tools may change later (especially local model serving — see §11 monitoring plan). Invariants do not.

This document is the build-target. When the operator clears the three Phase 0 gates (freeze hook installed, restore drill executed, auto-update timer enabled), Phase 1 build starts against this lock.

---

## 1. Language Stack — Locked

| Surface | Language | Rationale |
|---------|----------|-----------|
| Control plane (API, orchestration, capability registry, policy, audit, MCP, relay) | Python 3.13+ | Operator-fluent, Pydantic v2 ecosystem, FastAPI, MCP Python SDK |
| ML pipelines (embeddings, OCR, STT, RAG, ingestion) | Python | Native ecosystem; same runtime as control plane |
| PWA (frontend) | TypeScript | Forced by web tech ecosystem |
| Generated client types in PWA | TypeScript | From contracts package |
| Future Rust components | (none in Phase 1) | Preserved as future option via canonical audit test vectors stored alongside Python implementation. Rust gets added later only if a specific narrow component proves it. |

**Two toolchains, one cross-language boundary** (Python control plane ↔ TypeScript PWA). All cross-zone calls within the spine are Python-native; only PWA crosses a language boundary.

### Package managers

- **Python: `uv`** (modern, lockfile-first, ~10× faster than pip-tools, hash-pinning native)
- **Node: `pnpm`** (deterministic, content-addressed store, monorepo workspace support)

---

## 2. Data Layer — Locked

### Postgres 18.3 (with pgvector)
- Current supported major; pgvector packages it natively
- Single core DB on T0 per §3 of invariants doc
- Hosted in WSL2 Ubuntu on P920 (see §10 host)
- WAL backups via point-in-time recovery (DR-2 acceptance)

### Migration framework: alembic
- Forward-only discipline mirroring Donna's
- Linter: `alembic_linter` ports Donna's patterns (no destructive ops, revision graph valid, docstrings required, semantic smoke per DR-4)
- T0-local CI only — never cloud CI for migrations against T1+ data (DR-4)

### Object store: filesystem with content-addressing
- Layout: `/var/spine/objects/sha256/<aa>/<bb>/<full-hash>` (two-byte sharding for performance)
- Atomic write: `write to .tmp → fsync → rename` (POSIX atomicity guarantee)
- Postgres holds metadata + refcounts + sensitivity envelope per §6
- No MinIO in Phase 1 — operator is solo, ops surface matters

### Backup tooling: restic to Backblaze B2
- Matches Phase 0 drill on Donna
- Encryption-at-rest with key held separately from B2 credentials
- Nightly snapshots of Postgres (pg_dump --custom) + objects/ + secrets bundle

---

## 3. Web Layer — Locked

### API framework: FastAPI
- Async-native, Pydantic v2-aligned, OpenAPI generation
- Operator-familiar (Donna uses adjacent patterns)
- Routes serve PWA + capability dispatch + WebAuthn endpoints

### PWA framework: React 19 + Vite
- SPA only; no SSR (no Next.js complexity for solo)
- Service worker for offline shell; not for caching personal-data
- Generated TS types from `contracts/` package
- Build artifact deployed to T0 nginx (or FastAPI static mount)

### UI kit: shadcn/ui + Tailwind
- Source components copied into repo (no runtime kit dependency)
- Tailwind utility-first; no design system overhead Phase 1

### WebAuthn libraries
- Browser: `@simplewebauthn/browser` (TypeScript)
- Server: `py-webauthn` (Python, duo-labs maintained)
- Resident keys preferred (passwordless flow); allow non-resident as fallback
- FIDO2 PIN required on hardware key for critical-class approvals (per AE-4)

---

## 4. MCP Layer — Locked

### Server: FastMCP from official Python MCP SDK
- Hosted in the Python control plane process
- Capability registry per §3 of invariants doc IS the MCP tool list
- MCP transport: HTTP+SSE over Tailscale (operator devices) or stdio (when control-plane-internal)
- HMAC auth per §10 boundary-crossing (operator-device → control-plane authenticated session)

---

## 5. Local Model Serving — Hybrid

| Model class | Runtime | Reason |
|-------------|---------|--------|
| Daily models (Qwen 7B/32B, Llama 8B, Gemma, etc.) | Ollama | Mature, easy, hot-swap |
| DeepSeek R1 671B (Q4 GGUF, MoE expert offload to RAM) | llama.cpp server directly | Ollama doesn't expose `--moe-experts-on-cpu` flags |
| Embeddings (BGE-M3) + reranker (BGE Reranker v2) | TEI container | Higher throughput than Ollama for embeddings |

**Excluded:** vLLM (Pascal compute capability 6.1 not supported per current vLLM docs); SGLang (similar).

**Manifest hash pinning per SC-7:** every `model_runtimes` row carries `pinned_manifest_hash`. Runtime verifies on load; mismatch = refuse to activate.

**Windows-native Ollama loopback hardening (added v1.0.1 post-Codex):** Ollama runs Windows-native for Pascal driver fidelity but the control plane lives in WSL2. The HTTP boundary between them is T0-to-T0 only when these constraints hold:
- Ollama bound to `127.0.0.1` (or `localhost`) ONLY — never `0.0.0.0` or LAN-routable.
- Windows Defender Firewall rule explicitly denying inbound Ollama port from non-loopback interfaces.
- Every WSL2 → Ollama call carries the request's `correlation_id` so the cross-OS hop appears in the audit ledger.
- Calls flow through the capability registry / router code path; no direct adapter imports from elsewhere in the control plane.
- SC-7 manifest hash verified on every model load — the Windows-side Ollama doesn't get a trust bypass.

If Ollama is ever reachable from LAN or any process other than the WSL2 control plane, the loopback IS a trust-zone crossing and the architecture is broken. Phase 1 acceptance includes a `nmap` check of Ollama's listening surface from another LAN host (must show no open port).

---

## 6. Notifications — Locked

### Push to operator phone: Pushover (third-party adapter)
- **Strictly pointer-only, opaque payloads** (tightened v1.0.1 post-Codex). Payload must contain NONE of: email snippets, message subjects, sender names or addresses, recipient names, target user/account identities, action arguments, file/document names, capability arguments, or any text derived from personal data classified T1+. Permitted content: opaque category label (e.g. `"approval_pending"`, `"status_changed"`, `"brief_ready"`), a UUIDv7 pointer the PWA resolves under WebAuthn, optional non-identifying severity badge (`info` / `warn` / `urgent`).
- Wire format: `{category, pointer_id, severity, ts}`. NO `body`, NO `subject`, NO free-form text.
- Examples: ✅ `{category: "approval_pending", pointer_id: "...", severity: "urgent"}`. ❌ `{message: "Sarah just emailed about the contract"}`.
- Spine principle holds because the PWA does ALL personal-data rendering after WebAuthn; the push surface stays a T3-safe trigger.
- Cheaper, reliable, mobile-native delivery vs. self-hosting ntfy + APNs/FCM relay.

### Internal control-plane notifications: D-OB outbox table per §14.10
- Writer commits row; reader claims atomically
- No in-memory queues for cross-process delivery

---

## 7. Sensitivity Classifier — Locked

Pipeline order at ingestion:

1. **Deterministic secret detectors** (gitleaks-like patterns + entropy threshold) — handles `secret_taint` per SM-2
2. **Path/source-label rules** — file path conventions, Gmail labels
3. **Distilled small classifier** (TBD model, calibrated to operator corpus) — handles tier (T0–T3) + obligation flags
4. **Uncertainty escalation**: any classification with confidence < 0.5 promotes to a higher tier (default T2) and queues for operator review

**NOT zero-shot LLM** — non-deterministic, hard to audit, expensive. Distillation target: ~100M-200M params, fine-tuned on a small operator-curated dataset.

---

## 8. Repo Layout — L2 Locked

### New monorepo (TBD repo name; suggest `spine` or `sovereign`)

```
new-monorepo/
  contracts/           # canonical schemas (JSON Schema), versioned
                       # generates Python types (Pydantic) and TS types
  control-plane/       # Python package
    api/               # FastAPI app
    capability/        # registry + dispatch + policy engine
    audit/             # hash-chained ledger writer/verifier
    identity/          # WebAuthn server (py-webauthn)
    memory/            # episodic/semantic/procedural tables
    entity/            # universal entity store
    router/            # latency-first router + model_runtimes
    storage/           # object store + Postgres adapters
    relay/             # T2 relay code (when migrated from donna)
    workers/           # D-AT supervised task workers
  pwa/                 # React + Vite + shadcn/ui
    src/
    public/
  evals/               # golden corpus + precision-recall harness per EN-6
  ml/                  # model adapters (Ollama, llama.cpp, TEI client)
  runbooks/            # DR-1..DR-6 runbooks
  migrations/          # alembic
  scripts/             # ops scripts (backup, restore, drill)
  docs/
    PATH_3_INVARIANTS.md  (migrated from donna repo at bootstrap)
    PHASE_1_ARCHITECTURE.md (this doc; migrates with invariants)
  pyproject.toml
  package.json
  pnpm-workspace.yaml
```

### Donna repo
- Stays frozen at v0.7.3 + maintenance commits per DZ-1/DZ-2
- Decommission per DZ-5: code deletion event, ~90% removed; the remaining ~10% (Slack edge process) migrates into `new-monorepo/control-plane/relay/`
- v0.7.3 git tag preserved as historical snapshot

### contracts/ versioning
- Semver: major.minor.patch
- Published as Python package + npm package (PWA consumes the npm)
- Phase 1 starts at v0.1.0; v1.0.0 only when Phase 2 GA

---

## 9. Phase 1 Internal Sequence — Locked

Build the smallest end-to-end loop first; every step exercises spine invariants.

```
End-to-end loop:
  Phone PWA over Tailscale
    → WebAuthn login
    → FastAPI session
    → capability registry dispatch
    → system.ping
    → policy check
    → hash-chained audit write
    → Postgres outbox
    → supervised async worker
    → PWA pointer/result render
```

Step order:

| # | Step | Acceptance |
|---|------|-----------|
| 1 | Repo + `contracts/` package + canonical schemas + correlation_id format + generated TS types + JCS canonicalization helper | `contracts/` builds; Python and TS bindings round-trip a `system.ping` envelope |
| 2 | Postgres 18 + pgvector + alembic + migration linter + audit/outbox/task tables | First migration applies cleanly; linter rejects a known-bad migration; alembic upgrade head succeeds |
| 3 | FastAPI auth/session skeleton + WebAuthn (py-webauthn + SimpleWebAuthn) | Hardware key enrolled; session cookie issued; WebAuthn assertion verified |
| 4 | Capability registry with only `system.ping` | DB row inserted; dispatch validates request schema; emits audit event |
| 5 | Hash-chain writer + verifier | Audit ledger entries chain-validate; tamper test fails as expected; domain separation confirmed |
| 6 | PWA shell (React + Vite + shadcn/ui): login + device state + ping call + audit pointer view | Operator can sign in via WebAuthn from phone, call ping, see entry in audit view |
| 7 | D-OB notification outbox + D-AT supervised work queue (both Postgres-backed) | Async ping fires through worker; lease + heartbeat + dead-letter validated under chaos test |
| 8 | Minimal T2 relay harness: encrypted-unreadable queue, lease, probe, pointer-only Slack response | Relay activates fallback after lease+probe fail; queue stores opaque envelopes; Slack receives "open PWA" pointer |
| 9 | Tailscale/firewall verification | All inbound paths Tailscale-only; Slack websocket outbound; BitLocker confirmed; service accounts segregated |
| 10 | DR-1, DR-3, DR-4 rehearsed; outputs stored as audit artifacts | Each runbook executed end-to-end; results filed via §19 audit-artifact mechanism |

**What does NOT belong in Phase 1:** RAG, entity-store population, model routing logic, OCR, Slack polish, voice, image generation, R1 batch reasoning. All Phase 2+.

**Soak before Phase 2:** 7 days of `system.ping` round-trips with hash-chain integrity checks every 6 hours, no operator-visible failures.

---

## 10. Host OS / Runtime on P920 — Locked

**WSL2 Ubuntu on P920** as the runtime host.

| Layer | Runs in |
|-------|---------|
| Postgres 18, pgvector | WSL2 Ubuntu (native, not Docker) |
| FastAPI control plane | WSL2 Ubuntu (Python venv) |
| TEI embeddings + reranker | WSL2 Ubuntu (Docker container, GPU passthrough) |
| Ollama (daily models) | Windows-native (best NVIDIA Pascal driver support) |
| llama.cpp server (DeepSeek R1) | Windows-native or WSL2 (test both, pick latency winner) |
| ComfyUI (image gen, Phase 4+) | Windows-native (deferred; isolated user account per supply-chain rule) |
| PWA build artifact | WSL2 Ubuntu, served by FastAPI static mount or local nginx |

WSL2 GPU passthrough confirmed for Ada/Ampere; Pascal P6000 should also work via NVIDIA WDDM. **Phase 1 acceptance for GPU passthrough is split (post-Codex v1.0.1):** either (a) passthrough verified end-to-end (`nvidia-smi` inside WSL2 shows the P6000s, TEI container hits GPU), in which case Phase 1 progresses normally; OR (b) passthrough fails on Pascal, in which case Phase 1 progresses with an **explicit waiver** filed as an audit artifact noting "model/vision tiers gated until Pascal passthrough resolved." Waiver path delays the vision capability tier (Phase 4+) but does NOT block Phase 1 ingest/audit/identity infrastructure work, which doesn't require GPU. Either outcome is documented; silent failure is not allowed.

Service supervisor: **systemd in WSL2** (Ubuntu 24.04 supports it natively). Each service (postgres, fastapi, tei, llama-cpp-server, ollama-bridge) is a unit file. No Docker Desktop required for Phase 1.

### Why not Docker Desktop on Windows?

- Heavy resource overhead (always-on Hyper-V VM)
- WSL2 backend dependency anyway
- Operator is solo; native systemd in WSL2 is simpler

Docker may be added later for ComfyUI isolation per supply-chain rules (no third-party custom nodes — Codex's audit flagged this).

---

## 11. Local Model Serving — Monitoring Plan (Codex's "most likely wrong")

Quarterly check (calendar reminder):
- vLLM Pascal support status — currently excluded; if compute capability 6.1 lands, reconsider
- SGLang status — similar
- Ollama new MoE/expert-offload flags — would simplify the llama.cpp split
- HuggingFace `text-generation-inference` Pascal support
- New quantization formats that improve Pascal throughput

If any of the above changes materially, the local model serving stack swaps via `model_runtimes` config update + soak per LR-1. No invariant change required.

---

## 12. Hardware Enrollment Order — Locked

Day-of YubiKey 5 NFC arrival (×2):

```
1. 1Password root vault
   - Enroll BOTH keys in same session
   - Print Emergency Kit
   - Test sign-in with both keys
   - Set FIDO2 PIN on each key

2. Google primary email/recovery account
   - Enroll BOTH keys
   - Disable SMS 2FA fallback
   - Print recovery codes; seal in fire safe

3. GitHub
   - Enroll BOTH keys

4. DigitalOcean
   - Enroll BOTH keys

5. Tailscale
   - Enroll BOTH keys
   - THEN switch off Google SSO (verify hardware-key-only login works first)

6. Donna droplet SSH
   - Enroll BOTH keys (sk-ed25519 keypair stored on each YubiKey)

7. Slack admin
   - Enroll BOTH keys

8. Anthropic
   - Enroll BOTH keys (when supported; otherwise rely on TOTP via 1Password)

9. (Future Phase 1) P920 SSH + local WebAuthn
```

**Rule:** never leave an account with only one enrolled key. Enroll primary and spare in same session, test both, move on.

**Storage:**
- Primary YubiKey — daily carry
- Spare YubiKey — offline + offsite, FIDO2 PIN set, quarterly test (calendar reminder)
- Recovery codes — sealed paper at home + sealed duplicate offsite, NEVER in daily 1Password vault
- Emergency Kit (1Password) — sealed paper, separate location from recovery codes

---

## 13. Test Strategy

| Layer | Framework | Coverage target |
|-------|-----------|-----------------|
| Python unit | pytest | ≥80% on capability/audit/identity/router |
| Python integration | pytest + testcontainers Postgres | end-to-end on every capability + DR drill |
| Migration linter | alembic_linter (ported) | every migration |
| TS unit (PWA) | Vitest | components + state |
| E2E (auth + capability call) | Playwright | WebAuthn flow + ping round-trip + audit view |
| Chaos | manual playbooks Phase 1; automated Phase 2+ | lease expiry, network blip, Postgres restart |
| Schema/contract round-trip | pytest fixture | Python ↔ TS for every contract type |

Pre-commit hooks:
- ruff (Python)
- biome or eslint (TS)
- alembic_linter on changed migrations
- contract regen check (stale generated bindings fail)
- Donna-style commit-msg prefix enforcement (`fix:`/`chore:`/`docs:`/`security:`/`feat:` for new system; donna repo stays restricted)

---

## 14. Secrets Architecture

| Secret class | Storage | Rotation cadence |
|-------------|---------|------------------|
| OAuth refresh tokens (Gmail/Calendar/Drive) | Postgres encrypted column via T0 secret broker; encryption key in DPAPI on Windows. **Records marked `secret_taint` per SM-2 and `model_forbidden` (never appear in model context).** Every decrypt audit-logged with correlation_id, caller capability_id, and outcome. Never decrypted into environment variables or shell env; broker exposes a request-scoped session interface only. | Per-provider TTL |
| Anthropic / OpenAI API keys | sops+age bundle on T0; loaded at process start, held in memory | Quarterly rehearsed |
| Slack tokens | sops+age bundle on T2 droplet (relay only) | Quarterly rehearsed |
| Postgres role passwords | sops+age bundle on T0 | Annual |
| Backblaze B2 keys | 1Password (operator-fetchable) + sops+age (automated backup script) | Annual |
| age private key | Hardware-key-protected; offline paper backup | Never in same vault as encrypted bundle |
| WebAuthn credentials | Database (public-key only); private keys live on YubiKey | n/a (YubiKey replacement = re-enrollment) |

Donna's `docs/slack/TOKEN_ROTATION_REHEARSAL.md` discipline ports to new system: quarterly rehearsal of full rotation procedure against staging.

---

## 15. Document Versioning

- v1.0 — 2026-05-09 — initial lock from Codex architecture-lock pass
- v1.0.1 — 2026-05-10 — four advisory tightenings from Codex ratification pass: §5 Windows-native Ollama loopback hardening (localhost-only bind, firewall denial of LAN ingress, correlation_id propagation through capability registry, SC-7 manifest verify, nmap acceptance check); §6 Pushover payloads strictly opaque-pointer (explicit blocklist of personal-data fields, schema specified); §14 OAuth refresh token records marked `secret_taint` + `model_forbidden` with audit-every-decrypt via T0 broker; §10 GPU passthrough acceptance split into verified-or-explicit-waiver paths. Companion PATH_3_INVARIANTS bumped to v0.3.2 (SC-5 amended to tool-neutral hash-pinning with `uv` as Phase 1 implementation).
- Updates require PR review (no §23 governance — these are tooling, not invariants)
- Material runtime changes (e.g., switching Postgres major, swapping Ollama for vLLM) require entry in this document AND a soak window

---

*End of PHASE_1_ARCHITECTURE v1.0.1.*
