# Donna v0.5 — Context for Market Research Subagents

This file is the shared brief for all market-research subagents working on the
Donna v0.5 landscape scan (April 2026). Read it before researching your
category. Use it to decide what is "relevant context for Donna" vs. noise.

## What Donna is

Donna is a personal AI assistant for a solo operator. The design center is
**oracle, not scholar**: Donna is allowed to extrapolate beyond what is
strictly cited, but every extrapolation is **explicitly labeled** as such, and
the operator can drill into the underlying evidence. The opposite stance —
hedge-everything, cite-everything, refuse-without-source — is rejected as
unhelpful for a personal assistant who has to make calls under uncertainty.

## Design tenets

- **Solo-operator first.** Single user, single trust boundary. Not multi-tenant.
  No team features. No "AI for the enterprise."
- **Self-hostable / local-friendly.** The operator owns the data store and
  the model routing. Cloud LLM calls are allowed; cloud state is not the
  default.
- **Constrained extrapolation with labels.** Donna may infer, predict, and
  opine, but inference is rendered distinctly from cited fact. The UI must
  make the gap legible.
- **Memory is first-class.** Donna remembers across sessions: episodic
  (what happened), semantic (what's true), and procedural (how the operator
  works). Temporal versioning matters — facts change, and Donna must know
  *when* they changed.
- **Tool use is sandboxed.** Donna calls tools (web fetch, transcript pull,
  fact-check APIs, etc.) but does so under a security model that assumes
  prompt injection is the default state of the open web.
- **Validation surface.** When Donna asserts something the operator cares
  about, the operator can pull on the thread: counter-evidence, source
  bias, claim-level provenance. This is the "oracle, not scholar" payoff.

## What Donna is NOT

- Not a chat companion / waifu / persona product.
- Not a team knowledge base.
- Not a no-code agent builder for non-technical users.
- Not a wearable / always-listening recorder (though it can ingest those
  transcripts).
- Not an enterprise compliance product.

## What we want from this research

For every product in your category, we want to know:

1. **Where it sits relative to Donna's design tenets.** Is it solving the
   same problem? An adjacent problem? A subset?
2. **What it gets right that Donna should learn from.**
3. **What it gets wrong / where it has failed publicly.**
4. **Architectural signals we can borrow or avoid.** Especially:
   memory model, tool shape, agent loop, provider abstraction, security
   posture, state/checkpointing.
5. **Solo-operator viability.** Pricing, self-host story, single-user
   ergonomics. A $20k/yr enterprise SaaS is interesting only as a foil.

## Currency

It is **April 2026**. Anything older than April 2025 should be flagged as
potentially stale. The agent-framework and memory-system spaces in
particular have moved fast — LangGraph v1, Claude Agent SDK GA, the
OpenClaw skill-store post-mortem (Nov 2025), and the NCSC prompt-injection
paper (Dec 2025) are all recent enough to matter.

## Output rules

- Cite every claim with a primary-source URL (repo, official docs, product
  site, vendor blog). Avoid secondary reviews and listicles.
- If architecture isn't public, say so explicitly — do not invent.
- Cap each product entry at ~200 words.
- Write incrementally to disk as you go, not in one final dump.
- End your file with a "## Scope gaps I couldn't resolve" section.
