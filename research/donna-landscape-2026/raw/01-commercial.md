# Commercial Personal-AI Assistants — Landscape Scan (April 2026)

Subagent: 01-commercial
Scope: Consumer/prosumer personal-AI assistants and adjacent products.
Frame: How each compares to Donna's "oracle, not scholar" stance, memory model, solo-operator fit.

---

## Poke (The Interaction Company)

- Primary sources: https://poke.com/ ; https://poke.com/docs ; TechCrunch launch coverage https://techcrunch.com/2026/04/08/poke-makes-ai-agents-as-easy-as-sending-a-text/
- One-line: SMS/iMessage-native proactive AI agent that performs everyday tasks (calendar, smart home, health, photos) by texting you.
- Architecture signals: Cloud-only SaaS. Lives behind iMessage/SMS/Telegram/WhatsApp; no public stack disclosure. The Interaction Company is Palo Alto-based, raised $10M on top of a $15M seed at a $300M post-money valuation (Spark Capital, General Catalyst). No self-host. Architecture/LLM provider not public. Tool shape is implicit (calendar, smart home, browsing) routed inside Poke's backend; the user surface is a single chat thread.
- Features (claimed vs. confirmed): Proactive nudges, multi-channel messaging, persistent memory across threads. ProductHunt review reports near-perfect retention from beta; 750k+ messages from "first few thousand" users (https://www.producthunt.com/p/poke-by-interaction-co/a-week-with-poke-review-a-promising-start-for-a-proactive-ai-assistant). Hands-on review notes proactive feature is "promising" but error-prone on complex tasks.
- Pricing / self-host: Subscription (paid tiers post-beta); not self-hostable; multi-tenant cloud.
- Post-mortems / controversies: None major as of April 2026; product is fresh.
- Scope gaps: No local mode, no claim/source provenance, no memory inspection UI, no validation surface. Conversational-only — not a structured assistant.
- Relevance to Donna: Foil. Same "personal AI assistant" framing but opposite tenets: cloud-only, opaque memory, no labeled extrapolation. Useful as a UX reference for "ambient agent in messaging" — Donna explicitly is not this.

---
