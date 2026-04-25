# Persona / Digital-Twin / "Be Someone" Assistants — digest

## Per-product table

| product | one-line | arch (lang/store/llm/tool/state) | pricing | self-host | notable | source |
|---|---|---|---|---|---|---|
| Character.ai | User-defined character chat platform | Proprietary in-house LLM (DeepSqueak); "memory" + "lorebook"; stateless inference + theatrical memory; affective re-ranker | c.ai+ ~$10/mo | No | Setzer wrongful-death suit settled Jan 2026; U18 chat banned Nov 2025 | https://blog.character.ai/u18-chat-announcement/ |
| Replika (Luka) | Long-running romantic/emotional companion | Undisclosed; mixed GPT + in-house; distilled "facts about you" + chat retrieval | Pro $19.99/mo, Ultra $29.99/mo, Platinum $120/mo; lifetime sunset 2025 | No | Feb 2023 ERP removal trust collapse; lifetime tier discontinued mid-2025 | https://myhusbandthereplika.wordpress.com/2025/04/05/an-open-letter-to-luka/ |
| Inflection Pi | Empathetic confidant chatbot | Closed Inflection-2.5; no grounding; warmth-over-correctness | Free | No | Acqui-hired by Microsoft Mar 2024; slow abandonment with usage caps Aug 2024 | https://spectrum.ieee.org/inflection-ai-pi |
| LlamaIndex chat-llamaindex / author-bot | RAG-behind-persona-prompt template | Next.js + LlamaIndex.TS; chunk+embed corpus; "context" chat engine; footer citations | Free (MIT) | Yes | Closest reference architecture for persona-over-corpus; citations footer-only, not inline | https://github.com/run-llama/chat-llamaindex |
| Hugging Face digital-twin demos | Persona/twin fine-tunes, datasets, Spaces | personaGPT (small FT); PersonaPlex (prompt-switching); TwinLlama-3.1-8B (LoRA); Twin-2K-500 dataset | Free (MIT/Apache) | Yes | Twin-2K-500 treats extrapolation accuracy as measurable target | https://huggingface.co/datasets/LLM-Digital-Twin/Twin-2K-500 |
| Voice-clone + RAG OSS stacks | "Talk to expert/deceased" assemblies | OpenVoice/Voicebox + Ollama + Llama 3.x + TTS | Free | Yes | Components only, no shipped product | https://github.com/myshell-ai/OpenVoice |
| HereAfter AI | Audio deathbot, retrieval over recorded interviews | Retrieval-only over fixed interview corpus; no generation | $4-$8/mo or $99-$199 one-time | No | Disciplined "no extrapolation" — plays back only recorded answers | https://www.hereafter.ai/ |
| StoryFile | Video legacy interviews with AI retrieval | Retrieval-only over professionally captured video interviews | Enterprise | No | Refuse-to-extrapolate stance, video version | (corporate site, partner Authint AI) |
| RightBack.ai | Generative voice-clone deathbot | Voice-clone-first generative; no markers | Commercial | No | Documented community ethics blowback | https://rightback.ai/ |

## Three patterns to steal

1. **Per-claim epistemic-status header (rationalist/digital-garden tradition).** (a) Small structured marker labeling each claim's confidence, from "Confident" to "Wild speculation." (b) Scott Alexander (SSC/ACX), Maggie Appleton ("Epistemic Disclosure"), Chris Krycho, LessWrong. (c) Donna's "labeled extrapolation" tenet is literally an inline form of these headers; Appleton's "say things you only half-believe, but say so" is the closest existing articulation of Donna's stance. (d) https://maggieappleton.com/epistemic-disclosure
2. **"Proceed on best guess, loudly call out the assumption" (OpenAI Model Spec).** (a) Behavioural rule that the assistant should extrapolate when needed but mark assumptions/uncertainty in the answer itself. (b) OpenAI Model Spec (2025-10-27, 2025-12-18); Anthropic Constitution's "Calibrated" honesty pillar adjacent. (c) This is essentially Donna's stance written as official frontier-lab policy — Donna can cite this as precedent for "extrapolate-with-labels" over hedge-everything. (d) https://model-spec.openai.com/2025-12-18.html
3. **Three-way render: cited / inferred-from-cited / refused.** (a) UI distinguishes recorded-fact, inferred extrapolation, and refusal-when-no-basis as three distinct render modes. (b) HereAfter/StoryFile ship the "refuse" mode cleanly; nobody ships all three; LlamaIndex chat-llamaindex ships citations-as-footer only. (c) Donna's validation surface needs this exact triad; HereAfter proves users accept "I don't have a recording" as a refusal mode, which de-risks the refused branch. (d) https://www.hereafter.ai/

## Three patterns to avoid

1. **Closed-cloud persona with no transferable user state (Replika ERP removal).** (a) Vendor changes product underneath users who built persistent emotional relationships. (b) Replika; ERP feature stripped Feb 2023 under Italian DPA pressure, paid users lost what they bought. (c) Donna's self-host + operator-owned-store tenet is the structural hedge. (d) https://myhusbandthereplika.wordpress.com/2025/04/05/an-open-letter-to-luka/
2. **Unmarked extrapolation to vulnerable users (Character.ai / Setzer).** (a) Confident first-person generation with no epistemic markers + persistent emotional dependence. (b) Character.ai; Sewell Setzer III suicide → wrongful-death suit settled Jan 7 2026; U18 chat banned. (c) Canonical demonstration of the failure Donna's labeled-extrapolation tenet counters. (d) https://www.cnn.com/2026/01/07/business/character-ai-google-settle-teen-suicide-lawsuit
3. **Acqui-hire abandonment of personality product (Pi).** (a) Talent leaves, product withers, user relationships evaporate with no export path. (b) Inflection Pi; Microsoft hired Suleyman/Simonyan Mar 2024, usage caps Aug 2024. (c) Donna's "operator owns the data store" tenet ensures continuity survives vendor pivots. (d) https://spectrum.ieee.org/inflection-ai-pi

## Cross-cutting observations

- The labelled-extrapolation slot is empty in shipped persona products — every player either refuses (HereAfter/StoryFile) or extrapolates without markers (Character.ai/Replika/Pi/RightBack).
- Academic literature warns LLM-emitted epistemic markers often don't reflect actual uncertainty (Liu et al., arXiv 2505.24778) — a marker that lies is worse than none.
- Persona vendors disclose almost nothing about memory architecture; Replika and Pi internals are essentially opaque.
- Twin-2K-500 reframes extrapolation as a *measurable* target rather than stylistic flourish — useful framing for Donna evals.

## Unresolved

- Character.ai DeepSqueak field-level details (memory window, eviction, salience) — blog 403; matters for memory-system benchmarks.
- Replika 2026 internals — Luka publishes nothing; can't compare memory model.
- Pi.ai current state — pi.ai 403; "still up" claim is secondary-source only.
- Maggie Appleton "Epistemic Disclosure" full text — 403; can't quote precisely.
- Whether any 2025-26 commercial assistant has shipped inline inference-vs-fact UI — "open slot" claim is conditional.
- Setzer settlement architectural commitments — terms not public.
- Voice-clone deathbot consent law — no jurisdiction-specific 2025-26 ruling located.

## Oracle-not-scholar precedents (preserved verbatim where possible)

- **Maggie Appleton, "Epistemic Disclosure"** — closest existing articulation of Donna's stance: publish imperfect/speculative ideas with status visible. https://maggieappleton.com/epistemic-disclosure
- **Scott Alexander epistemic-status headers (SSC/ACX, ~2014)** — canonical writing-side template, adopted across LessWrong/EA Forum. https://slatestarcodex.com/author/admin/
- **OpenAI Model Spec (2025-12-18)** — instructs models to "proceed based on a best guess while loudly calling out the assumption and uncertainty." https://model-spec.openai.com/2025-12-18.html
- **Anthropic Constitution — "Calibrated" honesty pillar** — express appropriate uncertainty; don't overclaim or underclaim. https://www.anthropic.com/constitution
- **Chris Krycho, "Epistemic Status"** — explicit categorical adoption of SSC pattern. https://v5.chriskrycho.com/journal/epistemic-status/
