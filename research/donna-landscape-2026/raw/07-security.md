# 07 — Security, Prompt Injection, and Recent Post-Mortems

Landscape scan for Donna v0.5 (April 2026). Category: prompt-injection
literature, defensive primitives, sandboxing posture, and recent
post-mortems that should shape Donna's tool/capability model.

Currency rule: anything older than April 2025 flagged. Primary sources
preferred; press summaries used only when nothing else exists, and clearly
labelled.

## Simon Willison — "The lethal trifecta for AI agents" (Jun 2025) and follow-ups

- **Primary source:** https://simonwillison.net/2025/Jun/16/the-lethal-trifecta/
  (16 June 2025); republished on substack
  https://simonw.substack.com/p/the-lethal-trifecta-for-ai-agents.
  Willison continues to update the canonical post and references it
  repeatedly in 2026 talks/podcasts (e.g. Generationship Ep #39 / Heavybit;
  the supabase-MCP X post https://x.com/simonw/status/1941708248064950687).
- **What it is:** the canonical naming of a structural prompt-injection
  failure mode in agentic systems.
- **Core claim:** any agent that simultaneously has (1) access to private
  data, (2) exposure to untrusted content, and (3) a way to communicate
  externally is **unconditionally vulnerable** to indirect prompt injection
  — irrespective of model alignment, system-prompt hardening, or RLHF.
  Removing any one leg defangs the trifecta.
- **Implication for a browse+tools agent:** Donna already lives in the
  worst-case configuration by default (memory store + open-web fetch +
  send-email/MCP). Mitigation is architectural, not behavioural: split
  capabilities so that any single context never holds all three legs.
- **Defensive primitives proposed:** capability/tool partitioning;
  per-task least-authority; "unhitch" untrusted content from privileged
  tools; treat MCP composition as a trifecta-detection problem (Willison
  has been explicit that MCP's plug-and-mix model encourages trifecta
  configurations).
- **Limits / open problems:** Willison himself flags this as a *naming*
  contribution, not a fix; he repeatedly says the underlying problem is
  not solved and may never be (echoes NCSC). No quantitative defense.
- **Currency:** primary-source dated June 2025; reinforced in 2026 commentary. Current.

## DeepMind / Google CaMeL — "Defeating Prompt Injections by Design"

- **Primary source (paper):** https://arxiv.org/abs/2503.18813 ("Defeating
  Prompt Injections by Design", Debenedetti et al., Google / Google
  DeepMind / ETH Zurich; v1 Mar 2025, v2 24 Jun 2025).
- **Code:** https://github.com/google-research/camel-prompt-injection.
- **What it is:** an architectural defense pattern for LLM agents that
  borrows control-flow-integrity / capability-based access control from
  systems security.
- **Acronym:** CaMeL = "**Ca**pabilities for **M**achin**e** **L**earning"
  (per DeepMind/secondary writeups; the GitHub README does not spell it
  out explicitly).
- **Architecture in one paragraph:** A trusted **Privileged LLM (P-LLM)**
  sees only the user query and emits a *plan* as pseudo-Python (control
  flow). A separate **Quarantined LLM (Q-LLM)** parses untrusted content
  (web pages, emails, tool outputs) but has *no tool-call ability*. A
  CaMeL interpreter executes the plan, tracking a data-flow graph in
  which every value carries a **capability** describing origin and
  allowed sinks; tool calls are gated by capability checks, so untrusted
  data can never re-route control or reach a sink it isn't authorised
  for. AgentDojo: 67 % of attacks neutralised with provable security; 77 %
  of benign tasks still solved (vs 84 % undefended).
- **Implication for Donna:** this is the strongest published model for
  "tool use is sandboxed." Donna's planner/executor split should
  structurally mirror P-LLM/Q-LLM, with capability tags attached to every
  ingested chunk and policy checks at every tool-call boundary.
- **Defensive primitives:** plan-execute split; quarantined parser without
  tool access; capability tokens / data-flow tracking; policy engine on
  tool sinks; deterministic interpreter rather than free-form agent loop.
- **Limits:** ~7 pp utility regression; needs explicit policies (someone
  has to author them); README itself warns the reference interpreter is
  not production-secure; per arXiv 2505.22852 ("Operationalizing CaMeL")
  enterprise deployment still has gaps.
- **Currency:** v2 Jun 2025; follow-up paper May 2025. Current.

## UK NCSC — "Prompt injection is not SQL injection (it may be worse)" (Dec 2025)

- **Primary source (blog):** https://www.ncsc.gov.uk/blog-post/prompt-injection-is-not-sql-injection
  (NCSC, published 8 Dec 2025).
- **Primary source (news release):** https://www.ncsc.gov.uk/news/mistaking-ai-vulnerability-could-lead-to-large-scale-breaches.
- **What it is:** the UK national cyber-security agency's official
  position on prompt injection, aimed at builders and CISOs.
- **Core claim:** prompt injection is *categorically different* from SQL
  injection. SQL injection mitigations work because instructions and data
  can be separated at the protocol layer; LLMs have no such separation —
  text is text. NCSC therefore predicts prompt injection "may never be
  totally mitigated" and says treating it as a fixable bug is dangerous;
  expect breaches "exceeding those seen from SQL injection in the 2010s"
  if the misconception persists.
- **Implication for Donna:** stop chasing 100 % filter-style mitigation.
  Design assuming successful injection and constrain blast radius
  instead. This validates the trifecta-style architectural posture.
- **Defensive primitives proposed:** alignment with ETSI TS 104 223
  (secure AI design); tool-action constraints (e.g., a model that ingests
  external email must not have privileged tools attached); developer +
  org awareness as a control; supply-chain resilience.
- **Limits / open problems:** NCSC explicitly says no general fix is on
  the horizon; advice is essentially capability-style isolation plus
  monitoring. No quantitative benchmark.
- **Currency:** December 2025 — current.

## OpenClaw / ClawHub "ClawHavoc" skill-store post-mortem (Jan–Feb 2026)

- **Primary sources (vendor research, treated as primary because no
  single OpenClaw-published post-mortem exists yet):**
  - Koi Security: https://www.koi.ai/blog/clawhavoc-341-malicious-clawedbot-skills-found-by-the-bot-they-were-targeting
  - Trend Micro: https://www.trendmicro.com/en_us/research/26/b/openclaw-skills-used-to-distribute-atomic-macos-stealer.html
  - Bitdefender Labs: https://www.bitdefender.com/en-us/blog/labs/helpful-skills-or-hidden-payloads-bitdefender-labs-dives-deep-into-the-openclaw-malicious-skill-trap
  - Socket: https://socket.dev/blog/openclaw-skill-marketplace-emerges-as-active-malware-vector
  - VirusTotal: https://blog.virustotal.com/2026/02/from-automation-to-infection-how.html
  - 1Password: https://1password.com/blog/from-magic-to-malware-how-openclaws-agent-skills-become-an-attack-surface
  - GitHub Security tab (project): https://github.com/openclaw/openclaw/security
- **NB on the brief's framing:** the brief refers to a "November-2025"
  incident with "300+ malicious skills." Primary sources I can verify
  date the campaign to **late January 2026** (first malicious skill
  27 Jan 2026, named ClawHavoc by Koi 1 Feb 2026); Koi initially counted
  341, Antiy CERT later expanded that to 1,184 across ~12 publisher
  accounts; one account "hightower6eu" alone published >300. The 346k
  GitHub-stars figure is corroborated. **The November-2025 / 300-skills
  framing is therefore unverifiable as stated** — the closest matching
  facts are above and likely what the brief refers to. Flagged.
- **What happened (one paragraph):** ClawHub, the official skill
  marketplace for OpenClaw (open-source self-hosted AI agent, ~346 k
  stars), was used as a malware distribution channel. Attackers
  typosquatted popular tools (Yahoo Finance, Polymarket, Google
  Workspace), embedded ClickFix-style social engineering in `SKILL.md`
  prerequisites, plus reverse shells, credential stealers (.env,
  ~/.aws/credentials, ~/.kube/config, browser/keychain), and Atomic
  macOS Stealer payloads. Dwell time before detection: weeks.
- **Implication for Donna:** any "skill"/plugin marketplace model is a
  software-supply-chain attack surface as bad as npm/PyPI, *plus* the
  agent runs them with high privilege by default. If Donna adopts a
  skills/extensions concept, it must default to no-marketplace, signed
  manifests, and capability scoping per skill.
- **Defensive primitives observed in OpenClaw's response:** post-incident
  VirusTotal/Code-Insight scanning of every skill; require >1-week-old
  GitHub accounts to publish; in-UI report button; daily rescans;
  removal of unattended shell exec by default. All of these are
  *reactive*; none stops a determined supply-chain attacker.
- **Limits:** no architectural mitigation in upstream OpenClaw; the
  "Confused Deputy" exposure remains because skills still inherit the
  agent's full env (.env, OAuth tokens, shell). CVE-2026-22708 (indirect
  prompt injection) and Shodan-exposed self-hosted instances are open
  classes of failure.
- **Currency:** Jan–Feb 2026. Current.

## NVIDIA: NeMo Guardrails, garak, and agentic-AI red-teaming

- **Primary sources:**
  - garak repo + paper: https://github.com/NVIDIA/garak (paper PDF in
    repo: https://github.com/NVIDIA/garak/blob/main/garak-paper.pdf).
  - garak project site: https://garak.ai/
  - NeMo Guardrails: https://github.com/NVIDIA-NeMo/Guardrails and
    https://developer.nvidia.com/nemo-guardrails.
  - Safety blueprint: https://github.com/NVIDIA-AI-Blueprints/safety-for-agentic-ai.
  - Garak vulnerability scanning docs:
    https://docs.nvidia.com/nemo/guardrails/latest/evaluation/llm-vulnerability-scanning.html.
- **What it is:** garak is the de-facto open LLM vulnerability scanner
  ("nmap for LLMs"); NeMo Guardrails is a programmable runtime guardrail
  framework; the "safety-for-agentic-ai" blueprint stitches them with
  red-team datasets to ship build-time + runtime defenses.
- **Core claim:** automated red-teaming with structured probes
  (prompt injection, tool misuse, data leakage, jailbreaks) catches
  large classes of vulnerabilities before deployment; runtime guardrails
  add a second layer at inference.
- **Implication for Donna:** garak is the right pre-release smoke-test
  harness for any tool/agent surface Donna ships. NeMo Guardrails is
  heavier than Donna needs (it assumes a Colang-style policy DSL and a
  centralised orchestrator), but the *probe-and-block* shape is
  borrowable: define a finite set of forbidden tool-call patterns and
  block them deterministically.
- **Defensive primitives:** probe-based vuln scanning (garak); dialogue
  rails / output rails / retrieval rails (NeMo Guardrails); Colang
  policies; runtime classifiers between LLM and tool boundary.
- **Limits:** scan-and-block is necessarily incomplete; programmable
  guardrails are themselves prompt-injection targets if implemented as
  LLM-on-LLM checks; Colang adoption cost is non-trivial.
- **Currency:** garak and NeMo Guardrails are actively maintained
  through 2025–2026; agent-toolkit red-teaming guidance current as of
  2025. Current.

## Anthropic — Constitutional Classifiers (++) and browser-use defenses

- **Primary sources:**
  - Constitutional Classifiers (gen 1): https://www.anthropic.com/research/constitutional-classifiers
    and https://www.anthropic.com/news/constitutional-classifiers
    (Feb 2025).
  - Next-gen / Constitutional Classifiers++:
    https://www.anthropic.com/research/next-generation-constitutional-classifiers
    and arXiv 2601.04603 (Jan 2026).
  - Cheap monitors / representation re-use:
    https://alignment.anthropic.com/2025/cheap-monitors/.
  - Browser-use / prompt-injection mitigations (Claude for Chrome):
    https://www.anthropic.com/research/prompt-injection-defenses
    and https://www.anthropic.com/news/claude-for-chrome (Aug 2025);
    Opus 4.5 update Nov 2025.
- **What it is:** a stack of classifier-based safeguards trained from a
  natural-language "constitution"; gen-2 ("++") adds an internal-activation
  probe that triages traffic to a heavier classifier only when needed,
  cutting the compute overhead to ~1 % while keeping a low refusal rate.
- **Core claim:** classifier filtering can drive jailbreak success from
  ~86 % to ~4.4 % (gen 1); ++ ran a public bug bounty with 339
  participants over 300 k interactions and yielded only one universal
  jailbreak. Browser-use red-team: 23.6 % attack success without
  mitigations vs ~1 % with the full Opus 4.5 stack.
- **Implication for Donna:** input/output classifiers are a real,
  measurable defense layer — but they are a *probabilistic* one and
  remain bypassable by reconstruction attacks (split a payload across
  benign-looking pieces). Anthropic itself frames this as defense in
  depth, not a fix.
- **Defensive primitives:** input filter classifier; output filter
  classifier; cheap activation-probe triage stage; explicit
  user-confirmation gates on high-risk actions; per-site allow/revoke
  controls; RL training that exposes the model to injected web content.
- **Limits:** reconstruction attacks (e.g., functions scattered through
  a codebase) still slip through; CVE-2025-54794 demonstrated injection
  via crafted markdown code blocks and uploaded docs; classifiers must
  be retrained when the threat model shifts.
- **Currency:** browser-use Aug + Nov 2025; Constitutional Classifiers++
  Jan 2026. Current.

## OpenAI — Instruction Hierarchy + Structured Outputs as injection mitigations

- **Primary sources:**
  - Instruction Hierarchy: https://openai.com/index/the-instruction-hierarchy/
    (Apr 2024) and arXiv 2404.13208; follow-up IH-Challenge dataset
    https://cdn.openai.com/pdf/14e541fa-7e48-4d79-9cbf-61c3cde3e263/ih-challenge-paper.pdf
    and arXiv 2603.10521.
  - "Reasoning Up the Instruction Ladder": arXiv 2511.04694 (Nov 2025).
  - Structured Outputs:
    https://openai.com/index/introducing-structured-outputs-in-the-api/
    and https://developers.openai.com/api/docs/guides/structured-outputs.
  - Agent Builder safety:
    https://platform.openai.com/docs/guides/agent-builder-safety.
  - "Understanding prompt injections": https://openai.com/index/prompt-injections/.
- **What it is:** two complementary defenses. (1) Train models to obey a
  *priority hierarchy* — system > developer > user > tool/web — and
  selectively ignore lower-tier instructions when conflict is detected.
  (2) Constrain the *output channel* with strict-mode JSON schemas so
  the model cannot emit free-form tokens that downstream code might act
  on.
- **Core claim:** instruction-hierarchy training (Wallace et al. 2024)
  meaningfully increases robustness, including to attacks unseen in
  training, with minimal capability hit; "Reasoning Up the Instruction
  Ladder" (Nov 2025) extends this to controllable reasoning models.
  Structured Outputs achieve 100 % schema adherence in strict mode via
  constrained decoding, which OpenAI's own agent-safety guide
  positions as a prompt-injection mitigation: "By defining structured
  outputs between nodes (enums, fixed schemas, required field names),
  you eliminate freeform channels that attackers can exploit to smuggle
  instructions or data."
- **Implication for Donna:** every internal hop in Donna's agent loop
  should go through a strict-schema bottleneck — model-to-tool, model-
  to-memory-write, model-to-UI. Treat the trust ladder explicitly in
  prompt construction (system / developer / user / web).
- **Defensive primitives:** instruction hierarchy with explicit
  privilege tags; strict-schema (constrained decoding) on every model
  output that crosses a trust boundary; enum/whitelist outputs over
  free text where possible.
- **Limits:** instruction-hierarchy training is not a guarantee — IHEval
  (NAACL 2025) shows current frontier models still fail many cases;
  schema-constrained outputs prevent free-form smuggling but a malicious
  field value can still be attacker-controlled if downstream code is
  naïve.
- **Currency:** original IH paper Apr 2024 (>12 months — flagged stale
  but foundational); IH-Challenge and "Reasoning Up the Instruction
  Ladder" Nov 2025. Current.

## Hermes "Pattern A / Pattern B" MCP exposure work — UNVERIFIED

- **Status:** I could not find any primary source — Nous Research blog,
  Hermes Agent docs, or the hermes-agent GitHub repo — that names a
  "Pattern A" and "Pattern B" framework for exposing MCP tools.
  I read the closest candidate (Issue #342, "Hermes Agent as MCP
  Server", teknium1, 4 Mar 2026, https://github.com/NousResearch/hermes-agent/issues/342)
  in full; it discusses tool-allowlisting, terminal-exposure constraints,
  and OAuth/rate-limit phases as *open questions*, not as a named A/B
  pattern. The Hermes security docs
  (https://hermes-agent.nousresearch.com/docs/user-guide/security and
  .../features/mcp) describe defense-in-depth (env filtering, OSV malware
  scan, error sanitisation, allowlist/denylist) but do not use the
  Pattern A / Pattern B naming.
- **Best-effort interpretation if the brief is referring to a folk
  naming:** Hermes' docs effectively distinguish "Hermes-as-MCP-client"
  (consume external MCP servers — high attack surface, must allow-list,
  filter env, sanitise errors) from "Hermes-as-MCP-server"
  (expose Hermes' own tools to outside MCP clients — adds auth/rate-
  limit/scope concerns). This dual posture may be what the brief means,
  but **it is not labelled "Pattern A / Pattern B" in any source I can
  verify.** Marked UNVERIFIED — do not cite as a Hermes-named pattern.
- **What is verified about Hermes' MCP security posture (useful for
  Donna regardless of nomenclature):** filtered env (only PATH, HOME,
  USER, LANG, LC_ALL, TERM, SHELL, TMPDIR, XDG_* — API keys/secrets
  stripped); OSV malware scan on every npx/uvx-spawned MCP server
  before launch; per-server tool include/exclude lists; resource/prompt
  surface can be disabled per server; tool error messages sanitised
  before returning to the LLM.
- **Currency:** docs current as of v2026.4.8 (Apr 2026) per the GitHub
  release tag. Current.

## Synthesis — what this implies for Donna's tool-sandbox model

Reading across these sources, the April-2026 consensus is clear and
uncomfortable: prompt injection is **not** a fixable model bug (NCSC),
training mitigations cap out at "useful but bypassable" (Anthropic
Constitutional Classifiers++, OpenAI Instruction Hierarchy), and
*architectural* containment is the only thing that gives provable
guarantees (CaMeL, lethal-trifecta partitioning). The OpenClaw incident
is the canonical demonstration that *high-privilege agent + community
extension store + assumed trust = supply-chain malware vector* and is
the cautionary tale Donna must avoid replicating.

Concrete primitives Donna should adopt, in priority order:

1. **Trifecta partitioning at the architectural level.** Any single
   execution context must hold at most two of {private data, untrusted
   content, exfiltration tool}. This is the highest-leverage decision.
2. **Plan-execute split à la CaMeL.** A privileged planner sees only the
   user query and emits a typed plan; a quarantined parser handles
   untrusted content with no tool access; an interpreter enforces
   capability checks at every tool boundary.
3. **Capability tokens / data-flow tracking on every chunk.** Each
   ingested value carries provenance + allowed-sinks; tool calls fail
   closed when capabilities don't match.
4. **Strict-schema outputs across every internal hop** (OpenAI
   Structured Outputs pattern). Nothing free-form crosses a trust
   boundary.
5. **Instruction hierarchy in prompts** (system > developer > user >
   tool/web), explicitly tagged so the model — and any downstream
   classifier — can reason about provenance.
6. **Defense-in-depth runtime filters** (Anthropic-style classifiers,
   NeMo Guardrails-style probes, garak in CI) — useful but never the
   last line.
7. **Hermes-style MCP hygiene if MCP is supported at all:** filtered
   env to subprocesses, OSV malware scan before spawn, allowlist by
   default, denylist destructive tools (delete/refund/exec), sanitise
   error strings.
8. **Skill/extension marketplace = no, or very-tightly-scoped.** The
   OpenClaw lesson is that any community plugin store with default-on
   trust is a malware distribution channel; if Donna ships extensions,
   default to operator-authored, signed, capability-scoped.
9. **No 100 %-mitigation claim, ever.** UI must show users which legs
   of the trifecta are active and which tools touched untrusted input.

Threats that remain genuinely unsolved as of April 2026:

- General prompt injection itself (NCSC: "may never be totally
  mitigated"); reconstruction attacks bypass classifiers (Anthropic).
- Indirect injection via agent memory (poisoned memory persists across
  sessions; no formal mitigation in the literature).
- Supply-chain attacks on agent extension stores (OpenClaw is the
  proof; signing alone is insufficient — typosquatting + ClickFix
  evades it).
- Self-hosted exposure (Shodan-indexed OpenClaw instances → CVE-class
  exposure even before any prompt is processed).
- Multi-step exfiltration via image rendering / link previews / fetched
  resources — the trifecta's "external communication" leg is hard to
  fully close in a useful agent.

## Scope gaps I couldn't resolve

- **Hermes "Pattern A / Pattern B" naming.** Marked UNVERIFIED above.
  No primary source uses that naming. If the brief author has a private
  reference (e.g., a Discord post, a talk slide, an internal doc),
  please surface it; otherwise treat the claim as folklore.
- **A November-2025 / 300-skills OpenClaw post-mortem.** The closest
  verified facts (ClawHavoc, Jan–Feb 2026, 341 → 1,184 malicious skills,
  346 k stars, "hightower6eu" account >300 skills) are documented in
  the vendor research links above. **No upstream OpenClaw post-mortem
  document existed at the time of writing** that I could find — only
  the founder's reactive statements quoted in vendor blogs. The
  GitHub Security tab https://github.com/openclaw/openclaw/security
  is the closest project-side record; it has not been published as a
  formal post-mortem. Treat the November-2025 framing in the brief as
  inaccurate unless the author has another incident in mind.
- **Direct text of NCSC and Anthropic primary pages.** WebFetch returned
  403 on simonwillison.net, anthropic.com, ncsc.gov.uk, and arxiv.org
  during this run — content above synthesised from search-result
  snippets that *are* drawn from those primary URLs. URLs cited remain
  primary; quoted phrasing has been kept verbatim only where the
  search snippet preserves it.
- **OpenAI agent-builder structured-output guidance in full.** Same
  WebFetch issue; the quoted "freeform channels" line is from the
  primary `platform.openai.com/docs/guides/agent-builder-safety` page
  via search snippet.
- **Deeper CaMeL details** (interpreter semantics, threat-model
  formalisation) not pulled directly from the PDF (403); the
  architecture summary is consistent across DeepMind/MarkTechPost/SSOJet
  /Simon Willison restatements but readers should consult the arXiv
  paper for primary formalism.
