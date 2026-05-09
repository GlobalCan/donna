# PATH_3_INVARIANTS.md

**Status:** Draft v0.1 · 2026-05-09
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

- **CO-1**: Donna v0.7.3 reads `capability_ownership` on every scheduled fire and skips if `owned_by != 'donna'`.
- **CO-2**: New system reads same on every capability dispatch and rejects if `owned_by != 'new_system'`.
- **CO-3**: `'both'` is allowed only during explicit A/B test windows with an end date in `cutover_reason`. Audit must show what each branch produced and how the operator chose.
- **CO-4**: Default `owned_by = 'donna'` for capabilities Donna currently provides; default `'new_system'` for net-new.
- **CO-5**: Cutover is a single insert: append a row with the new owner. Forward-only (matches migration discipline).

### Acceptance for Phase 1
Table exists. Donna's morning brief and `/donna_ask` rows present. Both Donna and the new system query and respect the table. Test: insert `(/morning_brief, new_system, NOW())`; Donna's next fire is skipped (logged); new system fires.

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
- **TT-2**: Read agent's tool registry is **a strict subset** of capabilities (only Tier-0 and Tier-1). Tier-2 capabilities are not even *importable* from the read agent's module.
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
- Cache encrypted at rest with key held by P920 (relay decrypts only for serving)
- Cache size capped: ≤ 50 events, ≤ 100 email metadata entries, ≤ 1 brief
- Cache schema is allowlisted (versioned), and P920 controls what fields are populated
- All cache reads audit-logged on relay; logs replayed to P920 after reconnect for unified audit
- No cache extension during outage — cache shrinks (TTL-expires) only, never grows
- **Stale cutoff**: after max age (default: 24h), relay refuses factual answers and only queues. Status remains available.

**Forbidden capability creep:**
- Relay must NEVER perform triage, ranking, prioritization, or interpretation. The next requested exception will be "let the relay summarize subjects and rank likely-urgent emails." That is the moment the relay becomes Donna. Deny categorically.

### Switching mode (lease/state-machine, not heartbeat)

- **Lease**: P920 holds a lease (`primary_lease`) renewed every 30s.
- Relay activates fallback mode only when lease expires AND a confirming probe to P920 fails.
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
  - expiry (≤ 5 min)
  - risk class (low / medium / high / critical)
  - approval identity (operator user ID, device, hardware-key attestation present?)
- **AE-2**: Approval token is single-use. Recorded in `pending_consents`. Replay = hard reject.
- **AE-3**: Risk class ∈ {high, critical} → typed-text confirmation required (operator types a digest-prefix or short phrase from the signature), NOT 👍 alone.
- **AE-4**: Risk class = critical (T3 mutation, financial, legal, send-not-draft, irreversible) → **WebAuthn assertion** (hardware key tap), NOT typed-text alone.
- **AE-5**: Approval surface is the PWA on a T1 trusted device. Slack initiates ("approval pending; open secure review"); Slack cannot complete a critical-class approval.
- **AE-6**: Approvals show: full target identity, content snippet, **source content snippet that triggered this proposal** (so operator sees what bot was reacting to), action signature digest prefix, daily approval counter for this risk class.
- **AE-7**: Cross-surface global consent ID — if approval is resolved via PWA, Slack `chat.update` disables the button immediately and logs duplicate-decision attempts.

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

- **EN-1**: Every entity has a stable ID. Renames create aliases, never new entities.
- **EN-2**: Every mention is recorded with provenance (source URI, position, classifier version).
- **EN-3**: Every relationship is first-class with provenance and confidence.
- **EN-4**: Schema is "graph-ready relational" — recursive CTEs over `relationships` traverse the graph; no separate graph DB.
- **EN-5**: Phase 1 ships with `kind ∈ {person, document, event}` only. Adding `org`, `place`, `account`, etc. requires eval evidence of need.
- **EN-6**: Eval ratchet: golden corpus of N personal-domain queries; precision-recall tracked per release; no entity-type addition without ≥10% improvement on relevant slice.

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
| **DR-4** | Bad migration | Rollback procedure tested; alembic linter prevents destructive forward-only violations |
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

---

## 19. Operator Discipline 1 — Inline Codex Audit Content

Operationally earned via 1.8M-token quota burn (2026-04-30). Every architectural review pass via Codex MUST embed content inline in the prompt. Never let Codex grep file paths — costs run away.

This rule applies to: pre-audit, security audit, post-audit per enabled capability, decision reviews. Documented in operator runbook.

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

- ~~**Pushback 1 status**~~: **RESOLVED 2026-05-09 — Codex tiebreak: accept with modifications.** §8.x is locked with the additional constraints (precompute/disclose/never-derive line, fixed-template-only synthesis, allowlisted schema, stale cutoff, capability-creep prohibition).
- **GraphRAG community detection / community reports**: Phase 6+ if eval-ratchet evidence demonstrates need. Not deferred indefinitely; gated on demonstrated demand.
- **Home voice satellites**: Phase 3+ design. Wyoming protocol, ESP32/Pi hardware, ambient surveillance discipline required.
- **DR runbooks DR-2, DR-5, DR-6**: must exist by Phase 2; full execution by Phase 3.
- **Cloud-routed inference policy**: `cloud_routed_consent_class` is privacy-tier-2 (separate consent class from local). Never auto-routes T1+ data. Detailed consent flow specified in Phase 2 build.

---

## 23. Authoring Note

This document is committed to Donna's repo while she runs. It moves to the new system's repo when bootstrapped. Updates require a PR; updates that change a numbered invariant require Codex review + sign-off. Versioning:

- v0.1 — 2026-05-09 — initial draft from planning conversation synthesis
- v0.2 — 2026-05-09 — §8.x locked after Codex tiebreak: accept-with-modifications, "precompute/disclose/never-derive" rule added

---

*End of PATH_3_INVARIANTS v0.1.*
