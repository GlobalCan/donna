# Commercial Personal-AI Assistants — digest

## Per-product table

| product | one-line | arch (lang/store/llm/tool/state) | pricing | self-host | notable | URL |
|---|---|---|---|---|---|---|
| Poke | SMS/iMessage proactive agent | Cloud SaaS; stack undisclosed; messaging surface; implicit tools | Paid sub post-beta | No | $25M raised, $300M post; opaque memory | https://poke.com/ |
| Friend | $129 always-listening AI necklace | BLE pendant→iPhone→cloud; Claude 3.5/Gemini 2.5; SMS chat back | $129 one-time | No | Privacy backlash; NYC ad vandalism | https://www.friend.com |
| Day.ai | AI-native CRM auto-ingesting comms | Cloud SaaS; structured CRM entities; MCP-into-Claude; stack undisclosed | Per-seat Pro/Enterprise | No | $20M Series A Sequoia Mar 2026 | https://day.ai/ |
| Sana AI (Workday) | Enterprise knowledge agent | Cloud SaaS; corpus-bounded RAG; workflow agents; stack undisclosed | Workday enterprise | No | Acquired Nov 2025 ~$1.1B | https://sana.ai/ |
| Rewind.ai | Mac/iPhone screen+audio recall | Local capture, on-device OCR/transcription, vector index; cloud LLM Q&A | Was $19/mo | No (local) | Sunset Dec 19 2025 post-Meta | https://9to5mac.com/2025/12/05/rewind-limitless-meta-acquisition/ |
| Limitless | $99 mic pendant + lifelog | BT pendant→phone→cloud transcription; on-device consent mode | Was $99+sub | No | Sales halted Dec 5 2025; pulled EU/UK | https://techcrunch.com/2025/12/05/meta-acquires-ai-device-startup-limitless/ |
| Granola | Bot-free meeting notes | Local capture, on-device transcription; audio discarded; AWS US transcripts; MCP server | Free / $14 / $35 | No (local) | $125M Series C, $1.5B Mar 2026 | https://www.granola.ai |
| Personal.ai | Per-user SLM + memory platform | Per-user SLM; memory/context/identity layers; vector+KV; NVIDIA edge | Business; consumer deprioritized | No | Pivoted from consumer "twin" | https://www.personal.ai/ |
| Mem.ai | AI-organized notes "second brain" | Cloud SaaS; semantic vector search; LLM undisclosed; Mem 2.0 offline+voice+agent | Free / $12 Pro | No | Oct 2025 free-tier backlash | https://get.mem.ai/ |
| Humane AI Pin | $700 lapel pin + projected display | Cloud-only; CosmOS; Snapdragon; no on-device LLM | Was $699+$24/mo | No | Shut Feb 2025; HP $116M; ~$230M burned | https://techcrunch.com/2025/02/18/humanes-ai-pin-is-dead-as-hp-buys-startups-assets-for-116m/ |
| NotebookLM | Source-grounded research notebook | Cloud-only; Gemini 3 Flash/2.5; passage-cited RAG; Enterprise API | Free / $19.99 / $14 / $9 | No | ~95% citation, ~13% halluc vs ChatGPT 40% | https://notebooklm.google/ |

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
