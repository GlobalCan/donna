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

