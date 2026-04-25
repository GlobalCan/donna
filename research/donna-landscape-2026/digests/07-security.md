# Security, Prompt Injection, and Post-Mortems — digest

## Per-product table

| product | one-line | arch | primitive proposed | self-host | notable | URL |
|---|---|---|---|---|---|---|
| Willison Trifecta (Jun 2025) | Names injection failure mode | conceptual | Cap/tool partitioning; unhitch untrusted | n/a | Private data + untrusted + ext comms = unconditionally vulnerable | https://simonwillison.net/2025/Jun/16/the-lethal-trifecta/ |
| DeepMind CaMeL (2025) | Arch CFI/cap defense | P-LLM + Q-LLM split; cap-tagged data-flow | Plan-exec split; quarantined parser; cap-gated sinks | research code | AgentDojo 67% blocked w/ proof; 77% benign | https://arxiv.org/abs/2503.18813 |
| UK NCSC (Dec 2025) | Policy: injection ≠ SQLi | policy | ETSI TS 104 223; tool-action constraints | n/a | "May never be totally mitigated" | https://www.ncsc.gov.uk/blog-post/prompt-injection-is-not-sql-injection |
| OpenClaw ClawHavoc (Jan–Feb 2026) | Skill-marketplace supply-chain malware | self-host ~346k stars; SKILL.md ClickFix | Reactive: VT scans, >1wk acct, daily rescan | yes | 341→1,184 skills; CVE-2026-22708; Atomic macOS Stealer | https://www.koi.ai/blog/clawhavoc-341-malicious-clawedbot-skills-found-by-the-bot-they-were-targeting |
| NVIDIA garak | LLM vuln scanner | Python probes | Pre-release probe scan | OSS | De-facto OSS red-team | https://github.com/NVIDIA/garak |
| NeMo Guardrails | Runtime guardrails | Colang; in/out/retrieval rails | Probe-and-block | OSS | Heavy for solo; LLM-on-LLM injectable | https://github.com/NVIDIA-NeMo/Guardrails |
| Anthropic Const. Classifiers++ (Jan 2026) | Classifier + activation-probe triage | in/out classifier; cheap probe | DiD filter; confirm gates; per-site allow | API | 86%→4.4% gen1; bounty 1 universal jailbreak | https://www.anthropic.com/research/next-generation-constitutional-classifiers |
| Anthropic Claude for Chrome (2025) | Browser-use defenses | classifier + RL on injected web | User-confirm; per-site controls | API | 23.6%→~1% w/ Opus 4.5; CVE-2025-54794 | https://www.anthropic.com/news/claude-for-chrome |
| OpenAI Instruction Hierarchy (2024/Nov 2025) | Priority-ladder training | system>dev>user>tool tags | Privilege tags in prompt | API | 2024 stale; IH-Challenge + Reasoning-Up-Ladder Nov 2025 | https://openai.com/index/the-instruction-hierarchy/ |
| OpenAI Structured Outputs | Constrained-decoding JSON as mitigation | strict schema | Schema bottleneck on trust boundaries | API | 100% adherence; eliminates freeform channels | https://openai.com/index/introducing-structured-outputs-in-the-api/ |
| Hermes "Pattern A/B" — UNVERIFIED | Alleged MCP framework | no source uses naming | Verified: env filter, OSV scan, allowlist, sanitised errors | yes | Folk naming; not in docs/repo/#342 | https://github.com/NousResearch/hermes-agent/issues/342 |

## Three patterns to steal

1. **Plan-execute split w/ capability-tagged data flow.** (a) Privileged planner emits typed plan from user query only; quarantined parser handles untrusted content w/o tool access; interpreter enforces caps at every sink. (b) CaMeL; echoed by Willison + NCSC. (c) Donna's "tool use is sandboxed" tenet + memory-first design needs provable containment of open-web fetch. (d) https://arxiv.org/abs/2503.18813
2. **Strict-schema bottleneck at every trust boundary.** (a) Constrained-decoding JSON schemas at model→tool, model→memory, model→UI eliminate freeform smuggling. (b) OpenAI Structured Outputs + Agent Builder; complements Instruction Hierarchy. (c) Donna's validation surface + labeled-extrapolation UX need typed outputs; gates memory writes against poisoned ingestion. (d) https://developers.openai.com/api/docs/guides/structured-outputs
3. **Pre-release probe scan + runtime defense-in-depth.** (a) garak in CI against every tool surface; Anthropic-style classifiers at runtime, never last line. (b) garak + NeMo Guardrails + Constitutional Classifiers++. (c) Solo-op Donna can't manually audit every path; probe + activation-probe triage fit self-host budget. (d) https://github.com/NVIDIA/garak

## Three patterns to avoid

1. **Default-trust community skill/plugin marketplace.** Typosquatted ClawHub skills w/ ClickFix prereqs + reverse shells + stealers ran weeks; 341→1,184 malicious; signing alone won't stop typosquatting. https://www.koi.ai/blog/clawhavoc-341-malicious-clawedbot-skills-found-by-the-bot-they-were-targeting
2. **Skills inheriting full agent env (Confused Deputy).** OpenClaw skills inherited .env, AWS/kube creds, browser/keychain — exfil trivial once a malicious skill loaded. https://www.trendmicro.com/en_us/research/26/b/openclaw-skills-used-to-distribute-atomic-macos-stealer.html
3. **Public-internet-exposed self-hosted agent w/o cap scoping.** Shodan-indexed OpenClaw + CVE-2026-22708 = pre-prompt CVE exposure atop supply-chain risk. https://socket.dev/blog/openclaw-skill-marketplace-emerges-as-active-malware-vector

## Cross-cutting observations

- Consensus: injection unfixable at model layer; training mitigations bypassable; architectural containment is only provable layer.
- Reconstruction attacks defeat classifier filters (CVE-2025-54794).
- Memory-poisoning across sessions has no formal mitigation — relevant to Donna.
- All vendors frame as defense-in-depth; none claims 100%.

## Unresolved

- **Hermes "Pattern A / Pattern B" UNVERIFIED.** No primary source — Nous blog, Hermes docs, hermes-agent repo, or issue #342 — uses that naming. Closest interpretation (Hermes-as-MCP-client vs Hermes-as-MCP-server) isn't labelled A/B anywhere verifiable. Matters: synthesis must not cite folk naming as Hermes-authored.
- **Brief's "OpenClaw Nov-2025 / 300+ skills" framing unverifiable.** Verified incident is ClawHavoc, late Jan–Feb 2026; first malicious skill 27 Jan 2026; Koi named 1 Feb 2026; counts 341→1,184 across ~12 publishers; "hightower6eu" >300. No upstream OpenClaw post-mortem doc exists; vendor research is de-facto primary record. Matters: date/scale citations will be wrong if brief framing is preserved.
- General injection, indirect injection via memory, exfil via image/link previews, Shodan-exposed self-host instances remain genuinely open Apr 2026.
- WebFetch 403s blocked direct text extraction from Anthropic/NCSC/arXiv/Willison primaries; URLs primary but quoted phrasing is snippet-mediated.
