# Security, Prompt Injection, and Post-Mortems — digest

## Per-product table

| product | one-line | arch (lang/store/llm/tool/state) | primitive proposed | self-host | notable | URL |
|---|---|---|---|---|---|---|
| Willison "Lethal Trifecta" (Jun 2025) | Names structural prompt-injection failure mode | conceptual; no code | Capability/tool partitioning; unhitch untrusted content from privileged tools | n/a | Any agent with private data + untrusted content + external comms is unconditionally vulnerable | https://simonwillison.net/2025/Jun/16/the-lethal-trifecta/ |
| DeepMind/Google CaMeL (Mar–Jun 2025) | Architectural CFI/capability defense for LLM agents | Python interpreter; P-LLM + Q-LLM split; data-flow graph w/ capability tokens | Plan-execute split; quarantined parser w/o tool access; capability-gated tool sinks | research code (not prod-secure per README) | AgentDojo: 67% attacks neutralised w/ provable security; 77% benign solved | https://arxiv.org/abs/2503.18813 |
| UK NCSC (Dec 2025) | National-agency position: prompt injection ≠ SQLi | policy doc | ETSI TS 104 223 alignment; tool-action constraints; capability isolation | n/a | Predicts breaches "exceeding SQLi 2010s"; "may never be totally mitigated" | https://www.ncsc.gov.uk/blog-post/prompt-injection-is-not-sql-injection |
| OpenClaw/ClawHub "ClawHavoc" (Jan–Feb 2026) | Skill-marketplace supply-chain malware | OpenClaw self-hosted, ~346k stars; SKILL.md ClickFix + reverse shells/stealers | Reactive: VirusTotal scans, >1wk account rule, daily rescan, no unattended shell exec | yes (self-hosted) | 341→1,184 malicious skills; "hightower6eu" >300; CVE-2026-22708; Atomic macOS Stealer payloads | https://www.koi.ai/blog/clawhavoc-341-malicious-clawedbot-skills-found-by-the-bot-they-were-targeting |
| NVIDIA garak | "nmap for LLMs" vuln scanner | Python; structured probes (injection, tool misuse, leakage, jailbreak) | Probe-based pre-release scanning | OSS | De-facto open LLM red-team tool | https://github.com/NVIDIA/garak |
| NVIDIA NeMo Guardrails | Programmable runtime guardrail framework | Colang DSL; dialogue/output/retrieval rails; runtime classifiers | Probe-and-block at LLM↔tool boundary | OSS | Heavy for solo use; LLM-on-LLM checks themselves injectable | https://github.com/NVIDIA-NeMo/Guardrails |
| Anthropic Constitutional Classifiers++ (Jan 2026) | Classifier-based safeguards w/ activation-probe triage | input + output classifier; cheap activation probe | Defense-in-depth filter; user-confirm gates; per-site allow/revoke | API only | Jailbreak success 86%→4.4% gen1; bug bounty 339 ppl, 1 universal jailbreak | https://www.anthropic.com/research/next-generation-constitutional-classifiers |
| Anthropic Claude for Chrome (Aug/Nov 2025) | Browser-use prompt-injection defenses | classifier stack + RL on injected web content | User-confirm on high-risk; per-site controls | API only | 23.6%→~1% attack success w/ Opus 4.5 stack; CVE-2025-54794 markdown bypass | https://www.anthropic.com/news/claude-for-chrome |
| OpenAI Instruction Hierarchy (Apr 2024 / Nov 2025) | Train models to obey priority ladder | system>developer>user>tool/web tagging | Explicit privilege tags in prompt construction | API only | Foundational Apr 2024 (stale-flagged); IH-Challenge + Reasoning-Up-Ladder Nov 2025 | https://openai.com/index/the-instruction-hierarchy/ |
| OpenAI Structured Outputs | Constrained-decoding JSON schemas as injection mitigation | strict-mode JSON schema; constrained decoding | Strict-schema bottleneck on every trust-boundary hop | API only | 100% schema adherence; "eliminates freeform channels" per agent-builder safety guide | https://openai.com/index/introducing-structured-outputs-in-the-api/ |
| Hermes "Pattern A/B" — UNVERIFIED | Alleged MCP exposure framework | n/a — no source uses this naming | Closest verified: env filter, OSV scan, allowlist, sanitised errors | yes | Folk naming; not in Hermes docs/repo/issue #342 | https://github.com/NousResearch/hermes-agent/issues/342 |

## Three patterns to steal

1. **Plan-execute split with capability-tagged data flow (CaMeL).** (a) Privileged planner emits a typed plan from user query alone; quarantined parser reads untrusted content with no tool access; interpreter enforces capability checks at every sink. (b) DeepMind CaMeL; echoed by Willison's trifecta partitioning and NCSC's tool-action constraints. (c) Donna's tenet "tool use is sandboxed" + memory-first design demands provable containment of the open-web fetch leg; CaMeL is the strongest published model. (d) https://arxiv.org/abs/2503.18813
2. **Strict-schema bottleneck on every trust boundary.** (a) Constrained-decoding JSON schemas at model-to-tool, model-to-memory-write, model-to-UI hops eliminate freeform smuggling channels. (b) OpenAI Structured Outputs + Agent Builder safety guide; complements OpenAI Instruction Hierarchy tagging. (c) Donna's validation surface and labeled-extrapolation UX both require typed outputs; this also gates memory writes against poisoned ingestion. (d) https://developers.openai.com/api/docs/guides/structured-outputs
3. **Pre-release probe scanning + runtime defense-in-depth.** (a) Run garak in CI against every tool surface; layer Anthropic-style input/output classifiers at runtime — never as the last line. (b) NVIDIA garak + NeMo Guardrails; Anthropic Constitutional Classifiers++. (c) Solo-operator Donna can't audit every tool path manually; automated probes + cheap activation-probe triage fit a self-host budget. (d) https://github.com/NVIDIA/garak

## Three patterns to avoid

1. **Default-trust community skill/plugin marketplace.** Typosquatted skills with ClickFix prereqs + reverse shells + stealers ran for weeks across ClawHub; 341→1,184 malicious skills, one account >300. Signing alone doesn't stop typosquatting. https://www.koi.ai/blog/clawhavoc-341-malicious-clawedbot-skills-found-by-the-bot-they-were-targeting
2. **Skills inheriting full agent env (Confused Deputy).** OpenClaw skills inherited .env, ~/.aws/credentials, ~/.kube/config, browser/keychain — exfil was trivial once a malicious skill loaded. https://www.trendmicro.com/en_us/research/26/b/openclaw-skills-used-to-distribute-atomic-macos-stealer.html
3. **Self-hosted agent exposed to the public internet w/o capability scoping.** Shodan-indexed OpenClaw instances + CVE-2026-22708 (indirect prompt injection) = pre-prompt CVE-class exposure on top of skill supply-chain risk. https://socket.dev/blog/openclaw-skill-marketplace-emerges-as-active-malware-vector

## Cross-cutting observations

- Consensus: injection unfixable at model layer (NCSC); training mitigations bypassable; architectural containment is the only provable layer.
- Reconstruction attacks defeat classifier filters (CVE-2025-54794 markdown bypass).
- Memory-poisoning across sessions has no formal mitigation — directly relevant to Donna.
- All vendors frame work as defense-in-depth; none claims 100%.
- Hermes-style MCP hygiene (env filter, OSV scan, allow/deny, sanitised errors) borrowable regardless of naming dispute.

## Unresolved

- **Hermes "Pattern A / Pattern B" is UNVERIFIED.** No primary source — Nous blog, Hermes docs, hermes-agent repo, or issue #342 — uses that naming. Closest interpretation (Hermes-as-MCP-client vs Hermes-as-MCP-server) is not labelled A/B anywhere verifiable. Matters because synthesis must not cite a folk name as a Hermes-authored framework.
- **Brief's "OpenClaw November-2025 / 300+ skills" framing is unverifiable.** Verified incident is ClawHavoc, late Jan–Feb 2026; first malicious skill 27 Jan 2026; Koi named it 1 Feb 2026; counts 341 (Koi) → 1,184 (Antiy CERT) across ~12 publishers; "hightower6eu" alone >300. 346k stars corroborated. No upstream OpenClaw post-mortem document exists; vendor research is the de-facto primary record. Matters because date/scale citations downstream will be wrong if the brief's framing is preserved.
- General prompt injection, indirect injection via memory, exfil via image/link previews, and self-hosted Shodan exposure remain genuinely open as of April 2026.
- WebFetch 403s prevented direct text extraction from Anthropic/NCSC/arXiv/Simon Willison primary pages during raw research; URLs are primary but quoted phrasing is search-snippet-mediated.
