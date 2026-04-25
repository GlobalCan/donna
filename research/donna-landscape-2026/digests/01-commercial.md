# Commercial Personal-AI Assistants — digest

## Per-product table

| product | one-line | arch (lang/store/llm/tool/state) | pricing | self-host | notable | URL |
|---|---|---|---|---|---|---|
| Poke | SMS/iMessage proactive agent for everyday tasks | Cloud SaaS; stack undisclosed; messaging-channel surface; implicit tools (calendar/smart home); single-thread state | Paid sub post-beta | No | $25M raised, $300M post; 750k msgs early; opaque memory | https://poke.com/ |
| Friend | $129 always-listening AI necklace "companion" | BLE pendant→iPhone→cloud; Claude 3.5 → Gemini 2.5 (per Tom's Guide); SMS-style chat back; no transcripts viewable | $129 one-time | No | Privacy backlash; NYC ad vandalism; reviewers flagged as wearing a wire | https://www.friend.com |
| Day.ai | AI-native CRM auto-ingesting email/calendar/meetings | Cloud SaaS; structured CRM entities; MCP-into-Claude surface; stack undisclosed | Per-seat Pro/Enterprise | No | $20M Series A (Sequoia, Mar 2026); SOC 2 | https://day.ai/ |
| Sana AI (Workday) | Enterprise knowledge agent across company tools | Cloud SaaS; multi-tenant; corpus-bounded RAG; agent workflow executors; stack undisclosed | Workday enterprise per-seat | No | Acquired Nov 4 2025 for ~$1.1B; standalone consumer brand effectively retired | https://sana.ai/ |
| Rewind.ai | Mac/iPhone screen+audio "rewind" recall | Local capture, on-device OCR/transcription, vector index; cloud LLM Q&A; closed-source | Was $19/mo Pro | No (local-first) | Sunset Dec 19 2025 after Meta acquired Limitless | https://9to5mac.com/2025/12/05/rewind-limitless-meta-acquisition/ |
| Limitless | $99 mic pendant + lifelog app | BT pendant→phone→cloud transcription; on-device "consent mode"; cloud-only memory | Was $99 + sub | No | Pendant sales halted Dec 5 2025; Meta acquired; pulled from EU/UK | https://techcrunch.com/2025/12/05/meta-acquires-ai-device-startup-limitless/ |
| Granola | Bot-free meeting note app w/ scaffolded notes | Local audio capture, on-device real-time transcription (mac/win); audio discarded; transcripts on AWS US; MCP server (Feb 2026); personal+enterprise APIs (Mar 2026) | Free / $14 / $35 per user/mo | No (locally-rooted) | $125M Series C, $1.5B valuation Mar 2026 | https://www.granola.ai |
| Personal.ai | Per-user SLM + memory platform pivoted to telco edge | Per-user SLM on private corpus; memory/context/identity layers; vector+KV; edge on NVIDIA RTX PRO 6000 / Comcast AI Grid | Business plans; consumer deprioritized | No (partner-hosted edge) | Pivoted from consumer "AI twin" thesis | https://www.personal.ai/ |
| Mem.ai (Mem 2.0) | AI-organized notes "second brain" w/ agentic chat | Cloud SaaS iOS/macOS/web; semantic vector search; LLM provider undisclosed; Mem 2.0 added offline + voice + agent layer | Free (25/25) / $12 Pro | No | Oct 2025 free-tier tightening backlash | https://get.mem.ai/ |
| Humane AI Pin | $700 lapel pin w/ projected display | Cloud-only; CosmOS proprietary; Snapdragon SoC; no on-device LLM; voice+projection only | Was $699 + $24/mo | No | Shut Feb 28 2025; HP bought IP for $116M; ~$230M burned; units bricked | https://techcrunch.com/2025/02/18/humanes-ai-pin-is-dead-as-hp-buys-startups-assets-for-116m/ |
| NotebookLM | Source-grounded research notebook w/ Audio Overviews | Cloud-only; Gemini 3 Flash for audio, 2.5/3 stack for retrieval; strict passage-cited RAG; Enterprise API; bidirectional Gemini Notebooks sync | Free / $19.99 One AI / $14 Workspace / $9 Enterprise | No | ~95% citation accuracy, ~13% hallucination vs ChatGPT 40% on same corpus | https://notebooklm.google/ |

## Three patterns to steal

1. **Local capture + cloud LLM + MCP server out.** (a) Capture/transcribe locally, discard raw audio, expose memory via MCP. (b) Granola. (c) Matches Donna's self-hostable tenet and tool-surface story for transcript ingestion. (d) https://www.granola.ai
2. **Claim→passage drilldown for the validation surface.** (a) Every assertion clicks back to the cited passage in source. (b) NotebookLM. (c) Donna's "oracle, not scholar" needs exactly this UX, then layers a "this part is inference" overlay on top. (d) https://notebooklm.google/
3. **Memory/context/identity taxonomy with persistent layers.** (a) Split lived/episodic, static documents, and emergent identity into distinct memory layers. (b) Personal.ai. (c) Maps directly to Donna's episodic/semantic/procedural model and supports temporal versioning. (d) https://www.personal.ai/memory

## Three patterns to avoid

1. **Cloud-only "personal AI" with no fallback.** (a) Server-tethered device with no on-device mode or developer surface; when cloud dies, user owns nothing. (b) Humane AI Pin. (c) Validates Donna's self-host tenet — a third-party-controlled assistant is one shutdown away from gone. (d) https://failure.museum/humane-ai-pin/
2. **Local-first product absorbed and deleted by acquirer.** (a) Privacy-leaning local memory tool gets bought and sunset, killing the privacy promise. (b) Rewind.ai/Limitless under Meta. (c) Reinforces operator-owned data store as non-negotiable. (d) https://p4sc4l.substack.com/p/limitlessai-a-case-study-in-how-small
3. **Always-listening companion as core form factor.** (a) Continuous capture wearable as the product, not an input. (b) Friend pendant. (c) Confirms wearables are a privacy lightning rod; Donna ingests transcripts but is not a wearable. (d) https://sfstandard.com/2025/11/16/avi-schiffmann-friend-ai-pendant-loneliness-profile/

## Cross-cutting observations

- Stack opacity is the norm; LLM provider, memory schema, tool list usually hidden.
- MCP is the emerging interop surface (Day.ai into Claude; Granola server out).
- Wearable consolidation Dec 2025 (Meta/Limitless, HP/Humane) collapsed the consumer-AI-hardware category.
- Enterprise gravity: Sana, Day, Personal.ai, Granola all drift B2B despite consumer roots.
- Provenance UX maxes out at NotebookLM's passage-citing; nobody ships labeled extrapolation.

## Unresolved

- Personal.ai individual-tier pricing post-pivot — affects whether the "consumer twin" thesis is monetizable solo.
- Day.ai exact tiers and stack — needed to compare solo-operator viability.
- Sana standalone availability post-Workday — determines if it remains a foil or fully enterprise-only.
- Mem.ai LLM provider — relevant to memory/extraction architecture comparison.
- Friend's current LLM (Claude 3.5 vs Gemini 2.5) — affects companion-device LLM-routing precedent.
- Poke architecture, tool list, agent loop — docs returned 403; can't compare loop shape.
- Granola MCP server schema — needed to copy the tool-surface pattern faithfully.
- Limitless post-Meta roadmap — whether Donna can still rely on its API as a source feed.
