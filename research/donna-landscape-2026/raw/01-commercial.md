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

## Friend (friend.com / Avi Schiffmann)

- Primary sources: https://www.friend.com ; Wikipedia (product article) https://en.wikipedia.org/wiki/Friend_(product) ; founder profile https://sfstandard.com/2025/11/16/avi-schiffmann-friend-ai-pendant-loneliness-profile/
- One-line: $129 always-listening AI necklace pitched as a chatty, opinionated "companion" rather than a productivity assistant.
- Architecture signals: BLE pendant tethered to iPhone; cloud-processed; Wikipedia and reviews report it is built on Anthropic's Claude (originally Claude 3.5; Tom's Guide's Oct 2025 review says it now uses Gemini 2.5 via the phone). Audio is encrypted on-device, sent to Friend's servers, transcribed and processed; users cannot view raw transcripts, neither can the company (per founder claim). No self-host, no API, no developer surface. Communication channel back to user is an SMS-style chat, not voice.
- Features (claimed vs. confirmed): "Companion who comments on your life." Hands-on reviews (Fortune, WIRED, Tom's Guide) describe it as snarky, hostile, and forgetful mid-conversation; multiple testers were socially flagged as wearing a wire.
- Pricing / self-host: $129 one-time (with cloud-tethered service); not self-hostable.
- Post-mortems / controversies: Major privacy backlash; subway-ad campaign in NYC (2024) was vandalized. Shipping was delayed multiple times in 2025. Significant negative press in 2025/2026.
- Scope gaps: Not a productivity tool. No memory inspection, no task execution, no integrations.
- Relevance to Donna: Anti-pattern. Confirms Donna's tenet that "always-listening companion" is a separate market from "personal oracle." Useful only as a privacy/UX foil.

---

## Day.ai

- Primary sources: https://day.ai/ ; https://day.ai/pricing ; https://www.day.ai/resources/series-a-and-the-beginning-of-the-shift-in-crm ; https://www.day.ai/resources/introducing-day-ai-assistants
- One-line: AI-native CRM that auto-ingests email, calendar, and meeting audio into a structured customer system-of-record you can talk to.
- Architecture signals: Cloud SaaS. Built by ex-HubSpot leaders. Closed-source; stack not disclosed in public docs. Day announced a $20M Series A led by Sequoia (TechCrunch / Upstarts, March 2026). Integrates with Claude as an MCP-style data surface ("query and update Day AI from inside Claude; Claude mobile is your Day AI mobile app"). State model: structured CRM entities (accounts, contacts, opportunities) auto-derived from comms.
- Features (claimed vs. confirmed): Auto-capture from email/meetings; conversational queries; opportunity tracking; "Day AI Assistants" (March 2026) that act on your CRM data. Folk's review (folk.app/articles/day-ai-review) confirms ingestion works but flags rough edges in mid-sized teams.
- Pricing / self-host: Per-seat SaaS (Pro tier; enterprise tier). Not self-hostable. Multi-tenant cloud with SOC 2.
- Post-mortems: None notable.
- Scope gaps: Targets B2B revenue/customer-facing teams. Not a personal/solo assistant; not a general-purpose memory layer; no labeled extrapolation. Source provenance shown only at the entity level.
- Relevance to Donna: Adjacent. The "system of record you can talk to" pattern (structured entities auto-derived from raw comms, conversational query layer) is directly relevant to Donna's semantic memory. Day's MCP-into-Claude integration is a useful precedent for Donna-as-tool surface.

---

## SANA AI (now Workday Sana)

- Primary sources: https://sana.ai/ ; https://sanalabs.com/ ; https://newsroom.workday.com/2025-11-04-Workday-Completes-Acquisition-of-Sana ; Josh Bersin analysis https://joshbersin.com/2026/03/workday-and-sana-unveil-a-bold-new-strategy-for-ai/
- One-line: Enterprise knowledge assistant + agent platform that searches across company tools, summarizes meetings, and triggers actions; now Workday's flagship AI surface.
- Architecture signals: Cloud SaaS, multi-tenant. Stockholm-based; acquired by Workday Sept 2025 for ~$1.1B, closed Nov 4, 2025. "Sana Enterprise" requires upgraded licensing and connects Salesforce, Teams, Slack, SharePoint, Google Drive. Stack not disclosed; agents framed as workflow executors. Memory is enterprise-context driven (your company's documents), not first-class personal memory.
- Features (claimed vs. confirmed): RAG-style Q&A over company knowledge, meeting transcription, learning-platform module. Cybernews 2026 review and Workday press confirm enterprise-deployment focus.
- Pricing / self-host: Enterprise per-seat licensing through Workday; no self-host; no individual tier.
- Post-mortems: Acquisition closure consolidated the consumer-facing brand into Workday's enterprise catalog — effectively the end of standalone Sana for non-enterprise users.
- Scope gaps: Not solo-operator. No personal-data ownership story. Provenance is corpus-bounded, not claim-level.
- Relevance to Donna: Foil. Same agent + knowledge framing at enterprise scale; demonstrates that without solo-operator focus, the design ends up shaped by IT-buyer constraints (SSO, RBAC, compliance) rather than personal-oracle ergonomics.

---

## Rewind.ai (now sunset by Limitless / Meta)

- Primary sources: https://www.rewind.ai/pendant ; sunset coverage 9to5Mac https://9to5mac.com/2025/12/05/rewind-limitless-meta-acquisition/ ; https://techcrunch.com/2025/12/05/meta-acquires-ai-device-startup-limitless/
- One-line: Mac/iPhone "rewind your screen" recall app from Dan Siroker; rebranded to Limitless in 2024, acquired by Meta Dec 5 2025, app sunset.
- Architecture signals: Originally a local Mac app: continuous screen + audio capture, on-device OCR/transcription, vector index, queries against a locally-stored personal corpus. Cloud-LLM calls for Q&A. Closed-source. After Limitless rebrand, processing shifted heavily server-side.
- Features (claimed vs. confirmed): "Photographic memory" of everything you saw / heard on your Mac. Demos real; multiple reviewers confirmed search worked. Privacy posture leaned local-first relative to peers.
- Pricing / self-host: Was $19/mo Rewind Pro; never self-hostable but local-first. Now sunset.
- Post-mortems / shutdowns: Dec 5 2025 Meta acquisition → screen + audio capture disabled Dec 19 2025; service unavailable in EU, UK, Brazil, China, Israel, South Korea, Turkey from Dec 5 (https://winbuzzer.com/2025/12/05/meta-acquires-ai-wearables-startup-limitless-kills-pendant-sales-and-sunsets-rewind-app-xcxwbn/). Existing pendant users supported "at least one more year." Substack post-mortem (https://p4sc4l.substack.com/p/limitlessai-a-case-study-in-how-small) treats this as a case study in Big-Tech-absorption killing privacy promises.
- Scope gaps: Was screen-recall only, not an action-taking agent. No external tool use, no public-web grounding.
- Relevance to Donna: Cautionary tale. Validates Donna's tenet that local-first ownership matters — a third-party-controlled "memory" tool is one acquisition away from being deleted. Also a warning against ambient continuous capture as core architecture: it makes the product a privacy lightning rod and a strategic-control liability.

---

## Limitless (Pendant + app)

- Primary sources: https://www.limitless.ai/ ; https://help.limitless.ai/en/articles/9124757-pendant-faq ; Meta acquisition https://techcrunch.com/2025/12/05/meta-acquires-ai-device-startup-limitless/
- One-line: $99 wearable mic pendant + companion app from Dan Siroker / Brett Bejcek that records meetings/conversations and produces searchable "lifelog" transcripts.
- Architecture signals: Bluetooth pendant → phone app → cloud transcription/summarization. "Consent mode" on-device — blanks audio from speakers who haven't consented (per Limitless help center). Cloud-only memory. Stack not disclosed. After Meta acquisition the product is being absorbed into Meta's wearable AI roadmap (Ray-Ban Meta).
- Features (claimed vs. confirmed): 100hr battery, summaries, action-item extraction, transcript search. Reviews confirm the basic pipeline; criticism focuses on unreliable transcription in multi-speaker rooms and over-eager summaries.
- Pricing / self-host: Was $99 hardware + subscription tiers. Pendant sales halted Dec 5 2025. Existing customers grandfathered to free Unlimited Plan for ≥12 months. No self-host.
- Post-mortems / shutdowns: Service withdrawn from EU/UK and several other markets Dec 2025. Acquisition is the de-facto shutdown of the standalone product roadmap.
- Scope gaps: Capture-and-summarize only. No agent loop, no external tool use, no labeled extrapolation, no validation surface. Does not own its own destiny post-acquisition.
- Relevance to Donna: Source-feed precedent, not a competitor. Donna can ingest Limitless-style transcripts via API while owning the memory layer. Reinforces "Donna ingests wearables; Donna is not a wearable."

---

## Granola

- Primary sources: https://www.granola.ai ; https://www.granola.ai/pricing ; https://www.granola.ai/docs/docs/FAQs/granola-plans-faq ; Series C announcement https://techcrunch.com/2026/03/25/granola-raises-125m-hits-1-5b-valuation-as-it-expands-from-meeting-notetaker-to-enterprise-ai-app/
- One-line: Bot-free meeting note app for Mac/Windows/iOS that captures device audio locally, transcribes in real time, and produces shaped notes from your hand-typed scaffold.
- Architecture signals: Local audio capture (no meeting-bot joins the call); real-time on-device transcription on macOS/Windows; iOS uses temporarily-cached audio. Raw audio is discarded after transcription ("architectural deletion"); transcripts + user notes stored on AWS US. Feb 2026 added an MCP server; March 2026 added personal API and enterprise API for piping meeting context into other AI workflows. Stack not fully disclosed.
- Features (claimed vs. confirmed): 90-92% transcription accuracy in independent reviews (tl;dv 2026, max-productive.ai 2026). Speaker ID weak with 5+ participants. No cross-meeting analytics — each note is an island unless you manually link.
- Pricing / self-host: Free Basic, Business $14/user/mo, Enterprise $35/user/mo. Not self-hostable but locally-rooted (audio never leaves device). Solo-operator viable on free or business tier.
- Post-mortems: None. $125M Series C at $1.5B valuation March 2026; enterprise customers include Vanta, Gusto, Asana, Cursor, Lovable, Decagon, Mistral.
- Scope gaps: Meetings only. No long-horizon memory, no agent actions, no public-web grounding, no labeled extrapolation. Audio-discard policy means no source-of-truth audit beyond transcript.
- Relevance to Donna: Strong precedent. The "local capture + cloud LLM + MCP server out" architecture is exactly the shape Donna wants for its transcript ingestor. The MCP server is a model for Donna's tool surface. Deletion-by-architecture matches Donna's data-ownership stance.

---
