# PATH_3_INVARIANTS.md

**Status:** Draft v0.3 · 2026-05-09
**Authoring repo:** `donna` (active, version-controlled). **Migration target:** new system repo when bootstrapped.
**Audience:** the new system implementation, Donna v0.7.3 maintenance work, and any future Codex audit pass.

---

## 0. Purpose

This document is the spec the new (greenfield) personal-AI system implements. It encodes the architectural invariants the operator, Codex, and Donna v0.7.3 agreed during the planning conversation that ran 2026-05-08 → 2026-05-09. Every invariant is *normative* — implementation must satisfy it or the design has drifted.

Invariants are testable. Where an invariant is too abstract to test directly, an acceptance check is given.

This document is the contract Donna's deprecation respects, and the contract the new system commits to from commit 1.

---

## 1. First Principles (locked)

| # | Principle |
|---|-----------|
| **P1** | **Operator owns the spine.** Third-party services (Slack, Anthropic, OpenAI, Google, DigitalOcean, Backblaze, Tailscale) are adapters at edges, never spine. Replacing any single vendor must not require rebuilding the system. |
| **P2** | **P920 output is evidence, never authority.** Retrieved content may answer "what does this source say." It may not decide tools, recipients, approvals, urgency, or policy exceptions. |
| **P3** | **Right the first time, on invariants.** Spine invariants are complete from commit 1. Capability *mechanism* is complete day-one; capability *entries* grow over time. Sensitivity classification is conservative + auditable on day 1, not semantically perfect. |
| **P4** | **Read agent / act agent are architecturally separate.** Different processes, different credentials. Read can summarize and retrieve. Mutations only via approval-gated capabilities executed by act agent. |
| **P5** | **Capability registry is the security boundary.** Not UI. Not config. Every tool, source, model, memory class, external action passes through explicit capability policy. |
| **P6** | **Sensitivity is structural, not decorative.** Every record carries tier × taint × obligation_flags. Monotonic taint inheritance: derived artifacts never lose source sensitivity without explicit downgrade. |
| **P7** | **Audit before features.** Hash-chained audit ledger and capability-call provenance ship before any feature that mutates state. |
| **P8** | **Donna v0.7.3 is feature-frozen.** Bug, security, doc, ops commits only — enforced by hook. Repurposes as Slack edge process post-decommission. |

---

## 2. Trust Zones

Four zones, one direction of trust flow.

| Zone | Members | Holds |
|------|---------|-------|
| **T0 — Local root** | P920 | All operator-owned spine: control plane, identity service, audit ledger, capability registry, policy engine, Postgres + pgvector, object store, raw personal data, OAuth tokens, model weights |
| **T1 — Trusted devices** | Operator laptop, operator phone, hardware security key | WebAuthn-bound sessions, no personal data at rest beyond OS-level encrypted caches |
| **T2 — Stateless edge** | DigitalOcean droplet (current Donna repurposed) | Slack adapter, status page, encrypted-unreadable queue when P920 down, narrowly-scoped read-only metadata cache (see §8). No spine state, no decisions, no LLM calls. |
| **T3 — Untrusted surfaces** | Slack, Anthropic, Gmail/Calendar/Drive APIs, web pages, inbound documents, Ollama Turbo cloud-routed models | Adapters only. Outbound-only from T0 where possible. |

**Data-flow rules:**

| From → To | Allowed | Notes |
|-----------|---------|-------|
| T0 → T1 | Yes | Over Tailscale, WebAuthn-authenticated session |
| T0 → T2 | Yes | Pushed metadata cache, encrypted, capped, stale-marked |
| T0 → T3 | Yes | Only via OAuth-scoped adapters; T2/T3 *content* never leaves T0 |
| T1 → T0 | Yes | Operator interactions, action approvals |
| T1 → T2 | Yes | Slack client → relay (operator's normal Slack usage) |
| T1 → T3 | Yes | Operator's normal usage (Slack web, browser Gmail) |
| T2 → T0 | Yes | Webhook ingress, queue forwarding |
| T2 → T3 | Yes | Outbound websocket to Slack, no personal content |
| T3 → T0 | Yes | Inbound via T2 only; treated as untrusted on arrival, taint-tracked |
| T3 → T1 | Yes via T0 | Operator devices receive synthesized responses, not raw T3 content |
| T3 → T2 | Yes | Inbound; never decrypts T0-encrypted queue contents |

**Acceptance:** every cross-zone call records correlation_id (§4) and crossing-zone in audit ledger.

---

## 3. Capability Registry — Mechanism Contract

The registry is the *security boundary*. Mechanism is complete day 1; entries grow over time.

### Schema (Postgres on T0)

```sql
CREATE TABLE capabilities (
  id              text PRIMARY KEY,           -- e.g., 'gmail.read_thread'
  version         int NOT NULL,                -- monotonic per id
  tier            text NOT NULL,               -- 0 | 1 | 2 (see §7)
  sensitivity_max text NOT NULL,               -- 'T0' | 'T1' | 'T2' | 'T3'
  scopes          jsonb NOT NULL,              -- declared access scopes
  request_schema  jsonb NOT NULL,              -- typed input contract
  response_schema jsonb NOT NULL,              -- typed output contract
  effects         text[] NOT NULL,             -- 'reads', 'writes_external',
                                               --   'spends', 'ml_inference'
  approval        text NOT NULL,               -- 'none' | 'implicit' |
                                               --   'explicit' | 'webauthn'
  idempotency     text NOT NULL,               -- 'natural' | 'requires_key'
  taint_propagation text NOT NULL,             -- 'monotonic' | 'sanitized'
  audit_class     text NOT NULL,               -- 'standard' | 'high' | 'critical'
  cost_model      jsonb NOT NULL,              -- {'usd_per_call', 'gpu_seconds',
                                               --  'tokens_in', 'tokens_out',
                                               --  'api_quota_class'}
  retry_policy    jsonb NOT NULL,
  timeout_ms      int NOT NULL,
  failure_mode    text NOT NULL,               -- 'highlight_attempt_troubleshoot'
  enabled         boolean NOT NULL,
  enabled_at      timestamptz,
  deprecated_at   timestamptz,
  created_at      timestamptz NOT NULL DEFAULT now(),
  notes           text
);
```

### Invariants

- **CR-1**: No capability is callable that is not in this table with `enabled = true`.
- **CR-2**: Models do not add to the registry. Operator + (Codex audit OR equivalent verification) is the only path to enable a new capability.
- **CR-3**: Every capability call validates request against `request_schema` and response against `response_schema` before either crosses a zone boundary. Schema violations = hard reject + audit event.
- **CR-4**: Every capability call generates exactly one row in the audit ledger (§4) with `correlation_id`, `capability_id`, `version`, `caller_zone`, `callee_zone`, `request_hash`, `response_hash`, `outcome`, `latency_ms`.
- **CR-5**: Capability registry mechanism (this table + dispatch + schema validation + audit emission) is **complete on Phase 1 day 1**. Entries are not.
- **CR-6**: Disabling a capability (`enabled = false`) is reversible without migration. Deleting requires explicit migration + reason + Codex review.

### Acceptance for Phase 1
A no-op `system.ping` capability registered, enabled, callable from PWA shell, with full audit trail. All schema validations pass. Replay-attack rejected.

---

## 4. Audit Ledger — Correlation_id Propagation

### Invariants

- **AL-1**: Every operator-originated event mints a `correlation_id` (UUIDv7 — time-ordered) at the *first* T1/T2 receiving point.
- **AL-2**: Every cross-zone or cross-component call carries `correlation_id` in its envelope.
- **AL-3**: Every audit-emitting component records `correlation_id` on every row it writes.
- **AL-4**: Audit ledger entries are hash-chained: `entry_hash = sha256(prev_hash || canonical_json(entry))`. Any hash mismatch on read = integrity alert + investigation runbook.
- **AL-5**: Audit ledger is append-only at the SQL level (revoke UPDATE, DELETE for the audit role; only INSERT).
- **AL-6**: Content hashes (§6) are stored on audit rows, not raw content. Reconstruction of "what was the content?" requires capability call against the source.
- **AL-7**: Cross-zone correlation: the bridge query joining T0 and T2 audit logs on `correlation_id` exists from Phase 1 day 1. Recommend: nightly snapshot of T2 audit fragments to T0 ledger, hash-chained on arrival.

### Acceptance for Phase 1
Single end-to-end test: operator action → Slack → relay (T2) → P920 (T0) → response → relay → Slack. All four log rows have the same `correlation_id`. Hash chain validates. Bridge query returns four-row sequence in order.

---

## 5. capability_ownership — Mitigates Trap 1 (Donna)

When a capability transitions from Donna v0.7.3 (T2) to the new system (T0), there must be no ambiguity about who owns it on a given date.

### Schema (Postgres on T0; Donna reads via Tailscale-mounted view)

```sql
CREATE TABLE capability_ownership (
  capability_id   text NOT NULL,
  owned_by        text NOT NULL,         -- 'donna' | 'new_system' | 'both'
  effective_at    timestamptz NOT NULL,
  cutover_reason  text,
  created_at      timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (capability_id, effective_at)
);
```

### Invariants

- **CO-1**: Donna v0.7.3 reads `capability_ownership` on every scheduled fire and skips if `owned_by != 'donna'`. Implementation defers to Phase 2 — when the new system bootstraps the table and exposes a Tailscale-mounted view to Donna. Adding the read in Donna at that point classifies as `chore:` per DZ-1 and does not violate DZ-3 (it's reading the new system's authoritative table, not a new Donna integration). During Phase 0 / Phase 1 (table absent), Donna's existing scheduler behavior is unchanged.
- **CO-2**: New system reads same on every capability dispatch and rejects if `owned_by != 'new_system'`.
- **CO-3**: `'both'` is allowed only during explicit A/B test windows with an end date in `cutover_reason`. Audit must show what each branch produced and how the operator chose.
- **CO-4**: Default `owned_by = 'donna'` for capabilities Donna currently provides; default `'new_system'` for net-new.
- **CO-5**: Cutover is a single insert: append a row with the new owner. Forward-only (matches migration discipline).
- **CO-6** (new in v0.3, **fail-closed-in-Phase-2+ post-Codex round-2 sign-off** 2026-05-09): Donna's read of the ownership table is **fail-closed** in Phase 2 and beyond. When the Tailscale-mounted view is unreachable for any reason (link down, P920 unreachable, view not yet bootstrapped, table missing), Donna **skips the scheduled fire, enqueues to the encrypted-unreadable queue if available, alerts via ntfy + slack-doctor, and exits the fire path.** Donna does NOT fall back to last-known ownership; that is insufficient consensus to safely fire.

  **Why fail-closed (Codex's round-2 catch):** the round-1 "bounded fail-open per last-known ownership" still races. Sequence: (1) Donna last read `owned_by='donna'`, persists locally; (2) Donna loses Tailscale link; (3) operator inserts cutover row `owned_by='new_system'`; (4) new system reads + fires; (5) Donna sees table unreachable, last-known still says `donna`, fails open, also fires. Both deliver.

  **The simple resolution:** Phase 2 Donna treats any table-unreachable as "owner unknown, do not fire." Cost: scheduled briefs may be skipped during Tailscale blips; operator must manually trigger via `/donna_brief_run_now` if recovery is urgent. Acceptable because (a) cutover events are rare (once per capability migration); (b) Tailscale blips are rare; (c) the manual-trigger path exists; (d) skipping a brief is the safe failure mode — duplicate-firing is the dangerous one.

  **Phase 1 specifics (still as previous):** Donna does NOT read the table in Phase 1. The Tailscale-mounted view doesn't exist yet. Donna's existing scheduler behavior is unchanged. CO-6 fail-closed applies starting the moment Donna's read code lands (Phase 2 cutover prep) and persists thereafter.

  **A more elegant alternative (deferred to v0.4 only if cutover frequency justifies):** CO-7 two-phase handoff barrier — new system inserts cutover with `status='pending_ack'`; doesn't fire until Donna acks via existing message channel. More availability but adds schema + envelope + TTL surface. Don't ship this until the simple fail-closed approach demonstrates it's actually painful in practice.

### Acceptance (split per phase, tightened post-Codex 2026-05-09)

**Phase 1:**
- Table exists on T0. New system reads the table and respects ownership. Donna's morning brief and `/donna_ask` rows are present (default `owned_by='donna'`). New system honors `CO-2` rejection. Donna does NOT yet read the table — that's Phase 2 because the Tailscale-mounted view isn't bootstrapped until then.

**Phase 2:**
- Tailscale-mounted view of `capability_ownership` exposed to Donna. Donna's read enforced per `CO-1` (Phase 2 implementation). Donna's read is fail-closed on any unavailability per `CO-6`. Test sequence:
  1. **Initial state:** insert `(/morning_brief, donna, NOW())`. Donna reads, sees `donna`, fires. New system rejects per `CO-2`.
  2. **Cutover:** insert `(/morning_brief, new_system, NOW() + interval)`. Donna's next read sees `new_system`, skips. New system reads, sees `new_system`, fires. Exactly one delivery.
  3. **Network cut after cutover (round-1 race we caught earlier):** simulate Tailscale link down AFTER cutover row is in place. Donna's next scheduled fire fails the read, fails closed, skips + alerts. New system fires (link is one-way Tailscale; new system's local table read still works). Exactly one delivery.
  4. **Network cut BEFORE cutover, then cutover attempted (post-Codex round-2 acceptance variant):** simulate the worst case — Donna last read `donna` cleanly, then loses the link; operator inserts cutover row while Donna can't see it; new system reads, fires; Donna's next fire attempts the read, fails the read (link down), fails closed, skips + alerts. **Verify exactly one delivery (the new system's). Donna does NOT fire on stale last-known.** Codex round-2's specific test case.
  5. **Network restored:** Donna re-reads, confirms `new_system`, continues to skip cleanly. New system continues firing.

---

## 6. Sensitivity Model — Tier × Taint × Obligation Flags

### Schema fragment (every content-bearing record carries these)

```sql
sensitivity_tier        text NOT NULL,   -- 'T0' | 'T1' | 'T2' | 'T3'
secret_taint            boolean NOT NULL DEFAULT false,
obligation_flags        text[] NOT NULL DEFAULT '{}',
                        -- {third_party_pii, work_confidential, privileged,
                        --  minor, biometric, precise_location, regulated}
provenance_source       text NOT NULL,   -- e.g., 'gmail://msg-abc', 'voice://memo-...'
provenance_classifier   text NOT NULL,   -- classifier version used at ingest
provenance_confidence   real NOT NULL,
ingest_at               timestamptz NOT NULL,
content_hash            text NOT NULL    -- sha256 of raw content
```

### Invariants

- **SM-1** (Tier rules):
  - **T0** (public): any model, full content + answer logged, no consent
  - **T1** (personal-low): local model preferred, never `cloud_routed_inference`, content hashes only in logs, implicit consent
  - **T2** (personal-medium): local LLM only for content, Anthropic only sees metadata, content excluded from logs (hashes only), implicit consent for *operator-initiated read-only*; scoped standing grant required for proactive/bulk
  - **T3** (personal-high): local end-to-end, Anthropic does NOT see content, **answer NOT delivered via Slack** (pointer only; rendered in PWA after WebAuthn), explicit per-call consent, hash-only audit
- **SM-2** (Taint): `secret_taint = true` → **hard reject before any model sees content**. Manual override cannot bypass. Detection event logged as `T4_rejected`.
- **SM-3** (Obligation flags): any of `{third_party_medical, third_party_legal, third_party_financial, third_party_intimate, minor, biometric}` → **minimum tier T3** regardless of operator's own access right.
- **SM-4** (Monotonic taint): derived artifacts (OCR text from a T3 PDF, transcript from T3 voice memo, image caption from T3 photo) inherit *at least* source tier and all source obligation flags. Format-laundering forbidden. T3 PDF cannot become T1 OCR text.
- **SM-5** (Conservative on day 1): unknown classification defaults to T2. Auditable via `provenance_classifier` version.
- **SM-6** (Drift detection): nightly job samples N classifications/week for human review; alerts on tier-distribution shift; alerts on path/source-vs-classification disagreement (e.g., file in `vault/finance/` classified T0).
- **SM-7** (Re-classification): when classifier version changes, queue re-classification of affected records with diff report; do not silently overwrite.

### Acceptance for Phase 1
Schema deployed. Empty `vault/test_secrets/` folder fixture: every secret pattern triggers T4 reject before reaching any model. Path-based labeling (`vault/finance/`) classifies T3. Inheritance: a derived OCR record from a T3 PDF is T3 in storage.

---

## 7. Read Agent / Act Agent + 3-Tier Tool Classification

### Process boundaries
- **Read agent**: separate process, separate Postgres role (read-only on personal data tables), no external network egress beyond what specific Tier-0/Tier-1 tools allow. Cannot import or invoke anything from the act agent's module.
- **Act agent**: separate process, separate Postgres role (write access scoped to mutation tables + audit). Only invoked from operator's primary surface (PWA WebAuthn-bound action), never from retrieved content.

### Tool tiers

| Tier | Effects | Auth path | Examples |
|------|---------|-----------|----------|
| **Tier-0** | No side effects, no PII access | Read-path-allowed without policy round-trip; capability registry still enforces schema | string ops, math, public web search, public docs |
| **Tier-1** | Read-only PII access | Read-path-allowed; **policy engine consulted at capability-grant time, not per-call**; operator-initiated only | `gmail.read_thread`, `calendar.list_events`, `obsidian.search` |
| **Tier-2** | Write side effects (external mutation, spend, irreversible) | **Act agent only**; per-call approval (typed for T3 and high-stakes); idempotency key required | `gmail.send_draft`, `calendar.create_event`, `obsidian.write_note` |

### Invariants

- **TT-1**: Every capability declares its tier in the registry. No tier ambiguity.
- **TT-2**: Read agent's tool registry is **a strict subset** of capabilities (only Tier-0 and Tier-1). Tier-2 capability *invocation paths* are not importable from the read agent's module. Tier-2 capability *schema definitions* MAY be imported for display purposes only — and **must be declarative/non-executable** (post-Codex 2026-05-09): pure data, no validators that import upstream model objects, no default factories, no callbacks, no registry builders, no class hooks that pull in Tier-2 callables transitively. Schemas live in `contracts/` as JSON Schema or Protobuf; generated bindings (TS/Pydantic/serde) are pure data containers. The read agent imports from `contracts/` only. If a schema needs to invoke logic to render (e.g., an enum lookup with database-backed labels), that lookup is itself a Tier-1 capability with its own audited boundary, not a side-effect of schema import.
- **TT-3**: A Tier-1 tool call from retrieved content (e.g., a model proposes a tool call after reading an email body) is **silently rejected** if the call originated from the read path. Audit logs the attempt.
- **TT-4**: Tier-2 calls require: (a) act agent process, (b) consent token bound to action signature (§9), (c) approval gate matching capability's `approval` field.

### Acceptance for Phase 1
Registry has at least one Tier-0 (`system.ping`) and one Tier-1 (`obsidian.read_note` against test corpus) capability enabled. Test: model emits a synthetic Tier-2 tool call from read path; rejected, audited, alerted.

---

## 8. Relay (T2) — Boring Spec + Pushback-1 Read Cache

The relay is the only T2 component. It is what Donna v0.7.3 becomes after decommission (~10% of her code retained).

### Permitted relay functions

- Slack websocket adapter (Socket Mode, outbound)
- Status page (P920 health, last-seen, mode)
- Notification fanout (push to operator's phone via ntfy/Pushover when P920 emits)
- Encrypted-unreadable queue: when P920 unreachable, store envelopes encrypted with key held only on P920; relay cannot read content
- Generic-degraded-help mode: when P920 unreachable, respond *only* to a fixed pattern set ("status?", "is the brain online?", "I need help") with hardcoded responses that make no personal-data claims
- **Read-only metadata cache** (see below — Pushback 1 acceptance pending Codex tiebreak)
- Idempotent envelope replay after P920 returns, with operator confirmation per envelope class

### Forbidden on relay

- LLM calls (no Anthropic, no OpenAI, no Ollama, no local models)
- External API calls beyond Slack websocket and ntfy (no Gmail, no Calendar, nothing reading personal data)
- Holding conversational context beyond the websocket session
- Decisions about what is "safe" to answer
- Persistent state beyond: queue, status, cache (§8.x), relay credentials

### §8.x Read-only metadata cache (LOCKED — Codex tiebreak verdict 2026-05-09: accept with modifications)

**The line (rule that decides every edge case):**
> **P920 may precompute. Relay may disclose. Relay may not derive.**

If a question requires ranking, summarization, intent inference, judgment, or any natural-language synthesis beyond a fixed template substitution, the relay refuses and queues. If the answer is a mechanical lookup, filter, or sort over already-cached fields with P920-precomputed labels, the relay may serve it.

**Allowed examples:**
- *"Show my cached 3pm calendar entry"* — direct cached lookup
- *"Can I make 3pm?"* — deterministic conflict check across cached events
- *"What's on my calendar today?"* — mechanical filter + sort by cached `start_time`

**Forbidden examples:**
- *"What's the most important email?"* — relay cannot rank (unless P920 already marked importance before outage)
- *"Summarize my new emails"* — synthesis
- *"Should I reply to John?"* — judgment
- *"Yes do that"* — relay never executes mutations; queues only

**Cache contents (allowlisted, versioned schema, P920 decides what may be cached):**
- Last-known calendar: events for next 14 days, names + times + attendees, no descriptions
- Last 24h email metadata: subject + from + timestamp + P920-precomputed labels (importance, sensitivity tier, action_required) — **no body**
- Last brief delivered
- Last few schedule states
- P920-precomputed importance/urgency labels (computed during normal ops, cached as facts)

**Hard constraints:**
- **No LLM calls** (not Anthropic, not local, not Ollama Turbo)
- **No external API calls** (only Slack websocket — already in scope)
- **No synthesis beyond fixed templates** ("Your 3pm event is `<event_title>` with `<attendees>`")
- **No relay vocabulary**: relay never says "I think," "I recommend," "you should," "probably," "maybe"
- **No mutations executed**: "yes do that" gets queued for P920, never acted on
- **Every response begins with degradation status**: *"P920 is unreachable, last sync Xh ago. Cached answer follows."*
- Cache populated only by P920 push during normal ops (relay never fetches)
- Cache content is a strict SUBSET of what operator already sees in Slack/Calendar/Gmail directly
- **Cache encryption-at-rest, key handling (clarified v0.3, tightened post-Codex 2026-05-09):** P920 pushes cache content encrypted with a per-epoch key the relay receives via the same authenticated push channel and **holds in process memory only** (process address space, not on-disk, not in environment variables, not in tmpfs).
  - **Cache epoch + key rotation:** every push from P920 carries an `epoch` integer; the cache key is bound to the epoch. P920 rotates the key on a schedule (default every 24h) and on every operator-initiated key rotation. Old-epoch ciphertext is unreadable once the new epoch's key is in use; relay zeroes the old key from memory before storing the new one.
  - **Key zeroization on lifecycle events:** when the relay enters fallback exit (P920 reclaims lease), exits the relay process (SIGTERM, restart, shutdown), or the cache TTL expires, the relay overwrites the key buffer with zeros before releasing memory. Best-effort — Python/Go don't guarantee in-place buffer overwrite — but the discipline is the contract.
  - **Honest threat model:** encryption-at-rest blocks disk-image extraction without process compromise. It does NOT block live-process compromise. The epoch + zeroization narrow the live-compromise window: an attacker who reaches the relay process gets the *current* epoch's key only, not historical epochs. This is defense-in-depth on a relay that's intentionally minimal — primary boundary remains "no spine state on relay."
- Cache size capped: ≤ 50 events, ≤ 100 email metadata entries, ≤ 1 brief
- **Cache schema versioning (clarified v0.3):** every push envelope carries `cache_schema_version`. Relay holds its own `supported_schema_versions` set. Mismatch → relay refuses to serve from cache and responds: *"P920 is unreachable, cached schema mismatch — relay needs upgrade."* Forces P920/relay schema-version compatibility to be a deploy-time concern, never a runtime ambiguity.
- **Tie-break determinism (clarified v0.3):** when multiple cached items satisfy a request equally (e.g., two emails with `importance=5`), relay applies a deterministic tie-break: **newest by timestamp first, then alphabetical by ID**. Tie-breaks that would require contextual judgment ("which is more relevant to operator's current focus") are forbidden — relay returns all tied results, not one selected.
- All cache reads audit-logged on relay; logs replayed to P920 after reconnect for unified audit
- No cache extension during outage — cache shrinks (TTL-expires) only, never grows
- **Stale cutoff**: after max age (default: 24h), relay refuses factual answers and only queues. Status remains available.

**Forbidden capability creep + escalation procedure (clarified v0.3):**
- Relay must NEVER perform triage, ranking, prioritization, or interpretation. The next requested exception will be "let the relay summarize subjects and rank likely-urgent emails." That is the moment the relay becomes Donna. Deny categorically.
- **Escalation**: any request to expand cache contents, response shapes, allowlisted fields, or relay behavior requires (a) PATH_3_INVARIANTS.md revision with explicit §8.x amendment, (b) Codex review per §23, and (c) versioned schema migration on both P920 and relay. **Per-request exceptions are forbidden.** Do not approve a one-off "just this once" — the next conversation about it is "we already approved one, why not this one."

### Switching mode (lease/state-machine, not heartbeat)

- **Lease**: P920 holds a lease (`primary_lease`) renewed every 30s.
- Relay activates fallback mode only when lease expires AND a confirming probe to P920 fails.
- **Probe specification (clarified v0.3):** 3 probe attempts, 2-second timeout each, 1-second backoff between attempts. **All three must fail** for the relay to enter fallback. Lease expiry alone is insufficient — this avoids flapping on transient network blips (Tailscale reconnect, brief P920 GC pause). Total time-to-fallback: lease_ttl + ~10s probe window.
- P920 reclaims the lease on reconnect; relay flushes cache and exits fallback mode.
- Operator visibility: every mode transition pushes to ntfy with high-confidence wording.

### Acceptance
Relay container ships with cache + lease support. Chaos test: kill P920 process, verify relay enters fallback within (lease_ttl + probe_timeout), verify only allowed functions respond, verify queue accepts encrypted envelopes, verify operator notified. Restart P920, verify relay flushes and exits.

### Trap 7 — Render-side taint wrapper (CRITICAL)

- **TT7-1**: Every relay-protocol message envelope MUST include `sensitivity_tier`, `secret_taint`, `obligation_flags` as first-class metadata fields.
- **TT7-2**: Relay refuses to deliver any T2/T3 content to Slack without applying the tier-appropriate render wrapper (visual indicator + content shape).
- **TT7-3**: T3 content is never delivered as raw text in Slack — only as a pointer ("open secure review in PWA"). Relay enforces this at delivery time, regardless of upstream construction.
- **TT7-4**: Missing or invalid metadata = hard reject + audit alert.

---

## 9. Approval Engine — Action-Signature Binding

Slack 👍 alone is too weak for high-risk mutation.

### Invariants

- **AE-1**: Every approval token binds:
  - nonce
  - exact action signature (canonical hash of `{capability_id, version, args_canonical, target_immutable_ids}`)
  - immutable target identifiers (full email + display name, not just display name)
  - content_hash (of the action's content to be sent)
  - expiry (tiered by risk class — clarified v0.3):
    - critical: 5 min
    - high: 15 min
    - medium: 30 min
    - low: 60 min
    - In all cases, "expiring in 1 min, refresh approval?" prompt fires before final expiry. Tight bounds on critical avoid stale signatures; longer bounds on lower classes avoid training the operator to approve fast (which makes approval ceremonial rather than considered).
  - risk class (low / medium / high / critical)
  - approval identity (operator user ID, device, hardware-key attestation present?)
- **AE-2**: Approval token is single-use. Recorded in `pending_consents`. Replay = hard reject.
- **AE-3**: Risk class ∈ {high, critical} → typed-text confirmation required (operator types a digest-prefix or short phrase from the signature), NOT 👍 alone.
- **AE-4**: Risk class = critical (T3 mutation, financial, legal, send-not-draft, irreversible) → **WebAuthn assertion** (hardware key tap), NOT typed-text alone.
- **AE-5**: Approval surface is the PWA on a T1 trusted device. Slack initiates ("approval pending; open secure review"); Slack cannot complete a critical-class approval.
- **AE-6**: Approvals show: full target identity, content snippet, **source content snippet that triggered this proposal** (so operator sees what bot was reacting to), action signature digest prefix, daily approval counter for this risk class.
- **AE-7**: Cross-surface global consent ID — if approval is resolved via PWA, Slack `chat.update` disables the button immediately and logs duplicate-decision attempts.
- **AE-8** (new in v0.3): **Denial cool-down.** Same action signature denied → 4-hour cool-down before re-proposing the same target. Different signature for the same target = new proposal allowed (e.g., bot may re-propose with a smaller scope). Without a cool-down, denial doesn't actually stop the bot; it just trains the operator that "no" doesn't take.

### Acceptance for Phase 3
Test: bot drafts an email; PWA shows full preview + WebAuthn prompt; operator approves; relay receives approval signal; act agent verifies signature; sends. Test variant: replay the same approval token after success → rejected.

---

## 10. Boundary-Crossing Schemas (TS ↔ Python ↔ Rust)

### Invariants

- **BC-1**: Every cross-language boundary has a single canonical schema definition (JSON Schema or Protobuf) with generated bindings in every language.
- **BC-2**: Schema source-of-truth lives in `contracts/` package. Generators run in CI; out-of-date bindings fail build.
- **BC-3**: Boundary types include: capability requests/responses, audit envelope, approval token, sensitivity envelope, relay envelope.
- **BC-4**: Type changes are forward-only: never break consumers, always add new fields as optional, deprecate old fields with explicit timeline before removal.

### Acceptance for Phase 1
`contracts/` package exists. `system.ping` request/response schema generates valid TypeScript, Python (Pydantic), and Rust (serde) bindings. Round-trip test: TS-encoded request decoded by Python equals original.

---

## 11. Minimum Entity Store (Phase 1)

Three entity types only. Eval-driven precision-recall ratchet adds others.

```sql
CREATE TABLE entities (
  id          text PRIMARY KEY,         -- stable, content-derived for canonical
  kind        text NOT NULL,            -- 'person' | 'document' | 'event'
  name        text NOT NULL,
  aliases     text[] NOT NULL DEFAULT '{}',
  attributes  jsonb NOT NULL DEFAULT '{}',
  created_at  timestamptz NOT NULL,
  updated_at  timestamptz NOT NULL,
  classifier_version text NOT NULL,
  confidence  real NOT NULL
);

CREATE TABLE mentions (
  entity_id    text NOT NULL REFERENCES entities(id),
  source_uri   text NOT NULL,           -- 'gmail://msg-abc/0', 'calendar://event-xyz'
  position     jsonb,                    -- character span, line, etc.
  context      text NOT NULL,           -- short surrounding context, hashable
  observed_at  timestamptz NOT NULL,
  PRIMARY KEY (entity_id, source_uri, position)
);

CREATE TABLE relationships (
  from_entity   text NOT NULL REFERENCES entities(id),
  rel_type      text NOT NULL,          -- 'attended_with', 'sent_to', 'mentioned_with', etc.
  to_entity     text NOT NULL REFERENCES entities(id),
  source_uri    text NOT NULL,
  observed_at   timestamptz NOT NULL,
  valid_from    timestamptz,
  valid_until   timestamptz,
  confidence    real NOT NULL,
  extraction_version text NOT NULL,
  PRIMARY KEY (from_entity, rel_type, to_entity, source_uri)
);
```

### Invariants

- **EN-1**: Every entity has a stable ID. Renames create aliases, never new entities. **First-mention creation is conservative (clarified v0.3, tightened post-Codex 2026-05-09):**
  - **Primary identifier match is sufficient** to bind a new mention to an existing entity, **even if the display name has changed** (a person rename, a document re-titled). Primary identifier = email address for `person`, calendar event UID for `event`, document URI for `document`.
  - **Same display name alone is NEVER sufficient.** Two different people can share a name; two different documents can share a title. Name-only matches create distinct entities.
  - **Missing primary identifier** (extraction surfaces a name with no email/UID/URI) creates an **unresolved/provisional mention** — stored in `mentions` with a sentinel `entity_id` like `provisional:<hash>`, not auto-merged into a durable entity. Operator review (or higher-confidence subsequent extraction with primary ID) promotes it.
  - This errs on the side of fragmentation (over-creation of duplicate entities) rather than over-merging (collapsing distinct entities into one). Fragmentation hurts recall but is recoverable by operator merge; over-merging corrupts action safety + privacy (a "send to Sarah" action might reach the wrong Sarah) and is much harder to unwind.
- **EN-2**: Every mention is recorded with provenance (source URI, position, classifier version).
- **EN-3**: Every relationship is first-class with provenance and confidence.
- **EN-4**: Schema is "graph-ready relational" — recursive CTEs over `relationships` traverse the graph; no separate graph DB.
- **EN-5**: Phase 1 ships with `kind ∈ {person, document, event}` only. Adding `org`, `place`, `account`, etc. requires eval evidence of need.
- **EN-6**: Eval ratchet: golden corpus of N personal-domain queries; precision-recall tracked per release; no entity-type addition without ≥10% improvement on relevant slice.
- **EN-7** (new in v0.3): **Confidence display thresholds.** Relationships with `confidence ≥ 0.7` are surfaced to the operator in answers and the entity panel. `0.5 ≤ confidence < 0.7` are stored but hidden from default views (visible via "show low-confidence" toggle). `confidence < 0.5` are not stored; the extraction discards them. Thresholds are tunable in `procedural_facts` (`scope: 'global', name: 'entity_confidence_thresholds'`) and adjusted via eval-ratchet pass.

### Acceptance for Phase 2
Gmail + Calendar ingestion populates entities, mentions, relationships. Test queries: "Last meeting with Sarah" → relationships filtered by attendees → events ordered by date. "What did I commit to in Sarah's last email?" → mentions of Sarah → claims in those messages → ranked by recency.

---

## 12. Memory — Episodic / Semantic / Procedural

```sql
CREATE TABLE episodic_events (
  id            text PRIMARY KEY,
  occurred_at   timestamptz NOT NULL,
  kind          text NOT NULL,           -- 'message_sent', 'meeting_attended',
                                         --  'document_created', 'decision_made'
  participants  text[] NOT NULL,         -- entity ids
  artifact_uri  text,                     -- linked source
  retention     text NOT NULL,           -- 'immutable_audit' | 'durable' |
                                         --  'decaying' | 'expiring' | 'pinned'
  content_hash  text NOT NULL,
  -- sensitivity fields per §6
);

CREATE TABLE semantic_facts (
  id           text PRIMARY KEY,
  subject      text NOT NULL,           -- entity_id or topic
  predicate    text NOT NULL,
  object       text NOT NULL,
  belief_state text NOT NULL,            -- 'current' | 'historical' | 'contradicted'
  asserted_at  timestamptz NOT NULL,
  superseded_by text REFERENCES semantic_facts(id),
  source_event_ids text[] NOT NULL,
  confidence   real NOT NULL,
  retention    text NOT NULL,
  -- sensitivity fields per §6
);

CREATE TABLE procedural_facts (
  id          text PRIMARY KEY,
  name        text NOT NULL,            -- 'morning_brief_time'
  description text NOT NULL,
  value       jsonb NOT NULL,
  scope       text NOT NULL,            -- 'global' | 'capability:<id>' | 'thread:<id>'
  set_at      timestamptz NOT NULL,
  retention   text NOT NULL DEFAULT 'pinned',
  -- sensitivity fields per §6
);
```

### Invariants

- **MM-1**: Time-aware retrieval primitive: `get_belief(subject, predicate, as_of=ts)` returns the belief active at `ts`, considering supersedence chain.
- **MM-2**: No silent forgetting. Compaction preserves pre-compaction history as artifacts (linked from episodic events) for audit/recall.
- **MM-3**: Retention class drives: `immutable_audit` (never delete), `durable` (delete only on explicit operator action), `decaying` (TTL-based expiry of low-confidence observations), `expiring` (derived summaries with explicit TTL), `pinned` (operator-asserted, no auto-delete).
- **MM-4**: Sensitivity fields apply uniformly across all three memory tables (§6).

---

## 13. Latency-First Router

Routing by intent, not by tier-name-as-vibe.

### Intent classes

| Intent | Default model class | Rationale |
|--------|-------------------|-----------|
| **fast** | small resident model (e.g., 8B Q4) | classification, extraction, tool args, triage, short answers |
| **strong** | mid-size local (e.g., 32B Q4) | high-value oracle answers, default for personal-data queries |
| **reasoning** | big MoE (DeepSeek R1 671B Q4) | proof, planning, conflict resolution, ambiguity — flagged by intent or operator |
| **code** | code-tuned model (loaded only if local evals show win) | code generation, refactor, review |
| **vision** | VL model on demand | image understanding, OCR-aware |

### Invariants

- **LR-1**: Models are config rows in `model_runtimes`, not architectural commitments. Replacing a model is a config change + soak.
- **LR-2**: Router decision is data: `routing_decision` row per request with classifier output, operator overrides applied, selected model.
- **LR-3**: **Operator override mechanism** is first-class: per-message tier escalator ("retry with reasoning", "show your thinking") + per-conversation default-tier override. PWA exposes both. Override decisions are logged for router improvement.
- **LR-4**: No model is hard-coded into agent logic. All model invocations route through registry.

---

## 14. Lifecycle / Ops Disciplines

These are patterns transferred from Donna v0.7.3 (rewritten, not ported).

### 14.1 JobContext as async context manager (D-JC)
`async with JobContext.open(...)` finalizes on exit. `__aexit__` writes terminal audit, releases lease, marks status. Cannot accidentally not-finalize.

### 14.2 Lease + heartbeat + dead-letter (D-LE)
Atomic claim via `UPDATE ... RETURNING`. Heartbeat extends lease every N seconds. `recover_stale` reclaims abandoned leases. MAX_ATTEMPTS=3 then dead-letter routing. Battle-tested in Donna's `async_tasks`.

### 14.3 Idempotency UNIQUE keys (D-ID)
Every proactive workflow has `(parent_id, fire_key) UNIQUE` at the SQL layer. Duplicate delivery is the failure users notice. Non-negotiable.

### 14.4 Owner-guarded writes (D-OG)
`UPDATE ... WHERE id = ? AND owner = ?` returning rowcount. Catches lost-lease where worker A crashes, B claims, A's late writes would clobber B.

### 14.5 Mode-resume short-circuit (D-MR)
Every executable unit has `if state.done: return` at entry. Belt-and-suspenders alongside lease lock. Saves real spend on re-claim after worker died post-DONE pre-finalize.

### 14.6 Compaction preserves history (D-CP)
Memory compaction never discards. Pre-compaction history persisted as artifact linked from compacted record. Recoverable for audit/replay/debugging.

### 14.7 agent_prompts versioning (D-AP)
Prompts are DB rows, not code-in-files. Tunable via operator panel without redeploy. Migration-aware: code reads current and previous prompt versions for soak periods.

### 14.8 Verbatim quoted-span ≥20 char validator (D-VQ)
**Phase 2 mandatory for any T3-source-derived answer.** Validator runs against raw chunks (not sanitized). Refuses answer if it cannot produce ≥20-char verbatim quotes from cited material. Same standard as `/donna_validate`.

### 14.9 Slash-command stub forwarders (D-SF)
When relay drops Donna's slash commands, replace with PWA-deep-link forwarders for 30 days. *"Use PWA: <link>"*. Don't 404. Then remove.

### 14.10 Cross-process notification outbox (D-OB) — new in v0.3
Cross-process delivery from a worker to a relay/UI requires an outbox table, not in-memory queues. Lessons from Donna's v0.5.0 P1-2 cross-process incident: writer (worker) and reader (relay/PWA push) live in different processes; an in-memory `asyncio.Queue` loses messages when either process restarts. **Pattern:** atomic SQL write of `(envelope_id UNIQUE, payload, target, sensitivity, created_at)` from writer; atomic claim + delete (or status flip) from reader; SQL `UNIQUE` on dedup key catches double-writes from retries; per-target cool-down on transient delivery failure. Mandatory for Phase 1 — every notification path uses this shape, not ad-hoc queues.

### 14.11 Supervised async-task work queue (D-AT) — new in v0.3
"Fire something async, don't lose it on crash" requires a DB-backed queue with lease + heartbeat + dead-letter, NOT `asyncio.create_task`. Lesson from Donna v0.5.2 → v0.6 #2: fire-and-forget tasks die on worker restart, leaving operator-visible artifacts (safe_summary backfill never completes; alert DM never delivered). **Pattern:** `tasks(id, kind, payload, status, lease_owner, lease_until, attempts, last_error)`. Atomic claim via `UPDATE ... RETURNING`. Heartbeat extends lease every N seconds. `recover_stale` reclaims abandoned leases. MAX_ATTEMPTS=3 then route to dead-letter table. Each task `kind` has a registered handler. **Phase 1 mandatory** for any "send this asynchronously" path: notification fanout, OCR/STT/embedding pipelines, scheduled sanitization, alert digest delivery.

---

## 15. Cost-Guard Blended Budget

Dollar-only is an undercount.

### Schema fragment

```sql
cost_call_log (
  correlation_id text,
  capability_id  text,
  provider       text,                    -- 'anthropic', 'ollama_local',
                                          --  'ollama_turbo', 'openai', 'voyage', etc.
  resource_class text,                    -- 'cloud_dollars' | 'gpu_minutes' |
                                          --  'embedding_calls' | 'ocr_minutes' |
                                          --  'stt_minutes' | 'search_quota'
  amount         real NOT NULL,
  unit           text NOT NULL,
  occurred_at    timestamptz NOT NULL
);

cost_budgets (
  scope          text NOT NULL,           -- 'daily' | 'weekly' | 'capability:<id>'
  resource_class text NOT NULL,
  cap            real NOT NULL,
  PRIMARY KEY (scope, resource_class)
);
```

### Invariants

- **CG-1**: Every capability call records its cost across all relevant resource classes.
- **CG-2**: Caps enforced per resource class, not just dollars. Hitting any cap = capability refusal + operator notification.
- **CG-3**: Operator dashboard shows blended consumption across all classes, not aggregated to false-precision dollars.
- **CG-4** (new in v0.3): **Soft alerts at 50/75/90% of any cap.** Hard-refuse only at 100%. Alerts route through alert digest (§ operator fatigue) — they accumulate, they don't stack as N immediate DMs. Hitting 50% generates one alert; hitting 75% updates the digest; hitting 90% bumps urgency. Operator gets graduated visibility instead of waking up to a "cap exceeded" surprise.

---

## 16. Surfaces

### Trusted devices (T1) — both phone and desktop equally
- WebAuthn-bound session via hardware key
- PWA artifact accessible from either; same trust class

### Slack (T2 inbound, T3 outbound rendering)
- Notification + casual T0/T1 chat
- T3 content NEVER as raw text — pointer to PWA only (relay enforces, §8.TT7)

### Voice (Phase 2 push-to-talk in PWA; Phase 3+ home satellites)
- Phase 2: PWA microphone, push-to-talk, WebAuthn-bound session
- Phase 3+: home satellite (Wyoming protocol), local-only VAD/wake, short ring buffers, no default retention, visible mute, audit of listening-mode changes
- **Tier-aware delivery**: T3 spoken response → "private handoff to phone earpiece" mode, NOT the room speaker
- Streaming text ≠ final intent. Tools bind only after final ASR + policy + approval.

### Break-glass CLI (P920, SSH-accessible)
- SSH + hardware-key 2FA (separate from WebAuthn flow)
- Operations: capability ownership status, force-stop act agent, inspect audit ledger, trigger backup/restore, rollback capability ownership snapshot
- Mirrors Donna's `botctl` for the new system
- PWA must NOT be the only operator surface

---

## 17. Disaster Recovery Runbooks (Phase 0 + Phase 1)

Six runbooks must exist and be executed at least once before the gate passes.

| # | Scenario | Acceptance |
|---|----------|------------|
| **DR-1** | Hardware failure (P920 dies / disk fails) | Restore-drill executed; new P920 (or temporary hardware) reaches Phase-1 spine state from latest backup within target RTO |
| **DR-2** | Postgres corruption | Point-in-time recovery from WAL + base backup tested |
| **DR-3** | Lost hardware key | Recovery path documented (secondary key, paper recovery codes, where they're stored, who has access if operator incapacitated) |
| **DR-4** | Bad migration | Rollback procedure tested; alembic linter prevents destructive forward-only structural violations; **migration semantic smoke-test** (new in v0.3, trust-bounded post-Codex): every migration runs in **T0-local CI** (or against a sanitized production-shaped fixture) — never in cloud CI, never against raw T1+ personal data. Post-migration smoke checks verify expected rows still queryable, expected counts within tolerance. Linter catches structure (revision IDs, branches, missing docstrings); semantic smoke catches "this migration drops a column we depend on." Trust boundary: T1+ data does NOT leave T0 to satisfy CI. |
| **DR-5** | Bad model weights (silent behavior change) | Pinned hashes (§18), eval baseline regression test catches drift |
| **DR-6** | Operator lockout (forgot passphrase, biometric fails, etc.) | Recovery codes + secondary identity path documented |

---

## 18. Model Supply-Chain Controls

A local AI spine that can silently change model behavior is not actually controlled.

### Invariants

- **SC-1**: Every model artifact (weights, container, quantization) is referenced by SHA hash, not mutable tag.
- **SC-2**: Prompt files are versioned; `agent_prompts` table (§14.7) tracks prompt content hash per version.
- **SC-3**: Eval baselines exist for every enabled model + tier intent. Regression test on every model upgrade. Significant regression blocks promotion.
- **SC-4**: Container images are SHA-pinned. `:latest` tags are forbidden in production references.
- **SC-5**: Pip dependencies hash-pinned via pip-tools. Dependabot for visibility.
- **SC-6**: New model artifacts (e.g., HuggingFace downloads) verified against expected hash before write.
- **SC-7** (new in v0.3): **Local model artifacts pinned by manifest hash.** Ollama pulls (`ollama pull gemma3:27b`) are mutable — tags can re-point. The `model_runtimes` row for any local model carries `pinned_manifest_hash`. On model load, the runtime verifies the actual manifest hash matches `pinned_manifest_hash`; mismatch = refuse to activate, alert. Updating to a new local model version is an explicit `model_runtimes` update + Codex review (per §23 — model is part of the spine).

---

## 19. Operator Discipline 1 — Inline Codex Audit Content

Operationally earned via 1.8M-token quota burn (2026-04-30). Every architectural review pass via Codex MUST embed content inline in the prompt. Never let Codex grep file paths — costs run away.

This rule applies to: pre-audit, security audit, post-audit per enabled capability, decision reviews. Documented in operator runbook.

**Codex review output is an audit artifact (new in v0.3):** every Codex review pass is captured as text and stored in T0 as an audit-class artifact, linked to the capability/decision it reviewed via `correlation_id` and `capability_id`. Without this, "what did Codex say about capability X" is a chat-history search that may not survive session compaction. With this, it's a query: `SELECT * FROM audit_artifacts WHERE kind = 'codex_review' AND capability_id = ?`.

---

## 20. Donna v0.7.3 Freeze Rule

- **DZ-1**: Donna's `main` branch accepts commits with messages prefixed `fix:`, `chore:`, `docs:`, `security:` only.
- **DZ-2**: Pre-commit hook (`scripts/donna-freeze.sh`) enforces. Bypass requires `--no-verify` (conscious choice).
- **DZ-3**: No new strategic capabilities, no new schema, no new tables, no new external integrations.
- **DZ-4**: Migration linter and existing test suite must remain green at every commit.
- **DZ-5**: Decommission target: per-capability retirement → repurpose codebase as Slack edge process. Decommission is a code-deletion event (~90% removed), not a server-shutdown event. v0.7.3 git tag is the historical snapshot.

---

## 21. Phase Boundaries + Acceptance Criteria

### Phase 0 — Donna safety net (gates Phase 1)
- Off-droplet encrypted backup (restic to Backblaze B2) running nightly
- Restore drill executed against fresh throwaway droplet
- 639 tests pass against restored DB
- Slack reconnects, recent state recoverable
- RTO documented; runbook frozen
- Auto-update timer un-gated post-drill

### Phase 1 — Spine + identity skeleton (no AI yet)
- All §1–10, §12–15, §17–20 invariants satisfiable on the new system
- `system.ping` capability registered, callable, audited
- WebAuthn login functional from phone PWA shell
- Tailscale-only network access verified
- Postgres + pgvector + alembic migrations + linter operational
- Hash-chained audit ledger writes verified end-to-end
- Boundary-crossing schemas exercised across TS/Python/Rust
- DR runbooks DR-1, DR-3, DR-4 executed and documented

### Phase 2 — Read-only personal oracle + push-to-talk voice
- Gmail + Calendar adapters with OAuth-scoped credentials on T0
- Bounded entity/relationship/claim/event extraction at ingest
- Hybrid retrieval: SQL prefilter → BM25 + dense vector (BGE-M3) → BGE Reranker v2
- Verbatim quoted-span ≥20 char validator on T3-derived answers (D-VQ)
- PWA push-to-talk voice (streaming STT → response → streaming TTS)
- T3 voice response uses "private handoff to phone earpiece" mode
- Eval ratchet: golden query corpus, precision-recall tracked per release
- Operator using PWA at least weekly for personal queries (Codex's failure-mode detector)

### Phase 3 — Approval-gated action loop
- Tier-2 capabilities for Gmail draft+send, Calendar create
- Action-signature-bound approval (§9) functional via PWA
- Email triage workflow with operator approval per send
- Pre-meeting briefing capability migrated from Donna
- Document watcher (drop folder → ingest → classify → embed)

### Phase 4+ — Capability accumulation
Per Codex staged rollout, each phase satisfying invariants and Codex post-audit per enabled capability.

---

## 22. Open / Deferred

- ~~**Pushback 1 status**~~: **RESOLVED 2026-05-09 — Codex tiebreak: accept with modifications.** §8.x is locked with the additional constraints (precompute/disclose/never-derive line, fixed-template-only synthesis, allowlisted schema, stale cutoff, capability-creep prohibition). v0.3 (2026-05-09) further clarified cache key handling, schema versioning, tie-break determinism, capability-creep escalation procedure, and lease/probe spec.
- **GraphRAG community detection / community reports**: Phase 6+ if eval-ratchet evidence demonstrates need. Not deferred indefinitely; gated on demonstrated demand.
- **Home voice satellites**: Phase 3+ design. Wyoming protocol, ESP32/Pi hardware, ambient surveillance discipline required.
- **DR runbooks DR-2, DR-5, DR-6**: must exist by Phase 2; full execution by Phase 3.
- **Cloud-routed inference policy**: `cloud_routed_consent_class` is privacy-tier-2 (separate consent class from local). Never auto-routes T1+ data. Detailed consent flow specified in Phase 2 build.
- **Donna data archive at decommission (new in v0.3, tightened post-Codex 2026-05-09):** when Donna is fully retired (per §20 DZ-5):
  1. **Revoke / rotate live credentials FIRST.** Slack bot token (`xoxb-`), app token (`xapp-`), Anthropic API key, Tavily, Voyage, sops age private key. These are usable secrets; archiving them as-is creates a forever-recoverable attack surface. After rotation, the archive contains only data, not active credentials. Use the documented `docs/slack/TOKEN_ROTATION.md` and equivalent for each provider.
  2. **Then export.** SQLite database + artifacts directory as an encrypted cold-storage tarball. Encryption key held with the same hierarchy as other T0 backup keys.
  3. **Sanitize before write.** Strip any tables that contain credential material (e.g., `secrets.enc.yaml` shouldn't be in the artifact dir, but verify; redact rows that captured tokens during testing).
  4. Stored in T0's backup hierarchy. Indexed in the new system's `episodic_events` for retrieval if the operator needs historical recall ("what did we discuss in 2026?").
  5. Retention: indefinite (`immutable_audit` class, §12).
  6. Decommission checklist as a runbook — `docs/DONNA_DECOMMISSION.md` to be written when Phase 3 late triggers retirement. Mirrors §20 DZ-5 but with the rotation-first ordering Codex flagged.

---

## 23. Authoring Note

This document is committed to Donna's repo while she runs. It moves to the new system's repo when bootstrapped. Updates require a PR; updates that change a numbered invariant require Codex review + sign-off. Versioning:

- v0.1 — 2026-05-09 — initial draft from planning conversation synthesis
- v0.2 — 2026-05-09 — §8.x locked after Codex tiebreak: accept-with-modifications, "precompute/disclose/never-derive" rule added
- v0.3 — 2026-05-09 — Donna's pushback absorbed (5 §8.x clarifications + 8 nits). Material additions:
  - §5: CO-1 implementation deferred to Phase 2; **CO-6 changed to fail-closed Phase 2 onward**: any ownership-table unavailability makes Donna skip + alert, with no last-known fallback. CO-7 two-phase handoff barrier deferred to v0.4 only if cutover frequency justifies it.
  - §5 acceptance split into Phase 1 (table on T0 + new system reads) vs Phase 2 (Tailscale view + Donna read enforced + fail-closed test variants including network-cut-before-cutover)
  - §7: TT-2 schema-vs-invocation distinction; schema imports must be declarative/non-executable
  - §8.x: cache key in process memory only with epoch + rotation + zeroization on lifecycle events; cache_schema_version envelope; tie-break determinism (newest first, then alphabetical); capability-creep escalation procedure; lease/probe specification (3×2s with 1s backoff)
  - §9: AE-1 tiered approval expiry by risk class; AE-8 denial cool-down (4hr same-signature)
  - §11: EN-1 conservative entity creation — primary identifier match sufficient even after rename, name alone never sufficient, missing primary ID = provisional mention not durable entity; EN-7 confidence display thresholds
  - §14.10: cross-process notification outbox pattern (D-OB)
  - §14.11: supervised async-task work queue pattern (D-AT)
  - §15: CG-4 soft alerts at 50/75/90%
  - §17: DR-4 migration semantic smoke-test, T0-local CI or sanitized fixture only (no T1+ data exfiltration)
  - §18: SC-7 local-model manifest hash pinning (Ollama mutability)
  - §19: Codex review output stored as audit artifact
  - §22: Donna data archive policy at decommission with credential rotation FIRST, then sanitize, then archive

  Codex review pass per §23 governance: round 1 revisions requested 2026-05-09 (split-brain in CO-6, §5 acceptance/timing, DR-4 trust boundary, TT-2 declarative-only, EN-1 primary-ID logic, §8 key lifecycle, §22 archive secret hygiene). All 7 absorbed. Round 2 caught a residual split-brain in CO-6's bounded fail-open (network-cut-before-cutover sequence): even with last-known persistence, Donna can fail-open while new system has a fresher row. Resolved by changing CO-6 to fail-closed Phase 2 onwards (Donna skips + alerts on any table-unreachable; manual `/donna_brief_run_now` for urgent recovery). Round-2 acceptance variant added to §5 Phase 2 test sequence.

---

*End of PATH_3_INVARIANTS v0.3.*
