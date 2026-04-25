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

