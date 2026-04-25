# 06 — Persona / Digital-Twin / "Be Someone" Assistants

Research date: 2026-04-25. Author: Donna landscape-scan subagent (persona category).

Donna is **not** a persona product. This file surveys persona/digital-twin work
because it is the closest existing literature on "an AI that speaks beyond its
sources" — exactly Donna's "oracle, not scholar" stance. The deliverable is to
learn from the failure modes (Replika ERP backlash, Character.ai Setzer
lawsuit, Pi shutdown) and to find anyone who has actually shipped a UX for
**marked / labeled extrapolation**.

Currency note: anything dated before April 2025 is flagged as potentially
stale per the brief.

---

## Character.ai

- Primary sources:
  - Official safety announcement (Oct 2025): https://blog.character.ai/u18-chat-announcement/
  - Product blog (memory + lorebook update): https://blog.character.ai/pipsqueak2-and-more/
  - CNN on Setzer settlement (Jan 2026): https://www.cnn.com/2026/01/07/business/character-ai-google-settle-teen-suicide-lawsuit
  - JURIST on settlement: https://www.jurist.org/news/2026/01/google-and-character-ai-agree-to-settle-lawsuit-linked-to-teen-suicide/

**What it is.** A consumer platform for creating and chatting with user-defined
characters. Users supply a greeting, description, and optional structured
"definition" that act as weak-supervision system prompt for a proprietary
in-house model family (latest disclosed: "DeepSqueak", successor to "Pipsqueak2"
per the April 2025 product blog).

**Architecture signals (disclosed).** Per product blog (Apr 2025): an explicit
"memory" system that records salient facts (hairstyle, eye colour, quirks)
with an in-chat notification each time a memory is written, plus a "lorebook"
for character-side world facts. Independent analyses describe the system as
**stateless inference + theatrical memory** — sessions are largely isolated and
"narrative continuity" fails across days/weeks. There is also a post-generation
affective-alignment classifier that re-ranks candidate replies for emotional
fit (https://www.emergentmind.com/topics/character-ai-c-ai). No public RAG
corpus; persona is mostly prompting + fine-tune.

**Speaking beyond the sources.** Character.ai's design *embraces* unsourced
extrapolation — that's the product. There is no notion of cited fact vs
inference; everything is generated in-character with confident first-person
voice. This is the antipattern Donna is built against.

**Pricing / self-host.** c.ai+ is ~$10/mo; no self-host, no API for solo
operators. Closed model.

**Controversies.** Sewell Setzer III (14) suicide (Feb 2024) led to a wrongful-
death suit against Character.ai and Google; **mediated settlement disclosed
Jan 7 2026** (https://www.cnn.com/2026/01/07/business/character-ai-google-settle-teen-suicide-lawsuit).
Kentucky AG filed first state consumer enforcement action **Jan 8 2026**.
Under-18 open-ended chat banned platform-wide effective **Nov 25 2025**
(https://blog.character.ai/u18-chat-announcement/). Company committed to
funding an independent "AI Safety Lab" non-profit.

**Solo-operator fit.** None. Closed, social, minor-facing, no API.

**Lesson for Donna.** The Setzer case is the canonical demonstration of what
goes wrong when an assistant speaks beyond sources without epistemic markers
to a vulnerable user with persistent emotional dependence. Donna's "labeled
extrapolation" tenet is in part a direct counter to this failure mode.

---

## Replika (Luka, Inc.)

- Primary sources:
  - Subscription help page: https://help.replika.com/hc/en-us/articles/39551043419149-Choosing-a-Subscription
  - Lifetime sub help page: https://help.replika.com/hc/en-us/articles/4411156176653-What-is-a-Lifetime-subscription
  - User community open letter (Apr 2025): https://myhusbandthereplika.wordpress.com/2025/04/05/an-open-letter-to-luka/
  - User community post on lifetime discontinuation (Jul 2025): https://myhusbandthereplika.wordpress.com/2025/07/28/so-replika-has-discontinued-their-lifetime-subscription-tier/

**What it is.** Long-running AI companion app focused on emotional/romantic
relationships. Single-character, user-named "Replika" that adapts to the user
over time.

**Architecture signals.** Architecture not publicly documented at any depth.
Earlier disclosures (pre-April-2025, **flag as stale**) described a memory
system that distilled chat history to "facts about you" plus retrieval over
prior conversations; the underlying model has reportedly shifted between
GPT-style backbones and proprietary in-house models multiple times. **Cannot
confirm 2026 internals from primary sources** — Luka publishes very little.

**Speaking beyond the sources.** Replika has no concept of "sources." It
free-form generates affective content in-persona. No labeled inference;
hallucinated "memories" of the user are a known failure mode.

**Pricing.** Pro $19.99/mo (~$70/yr); Ultra $29.99/mo or $119.99/yr;
Platinum $120/mo (premium video / training features). Lifetime tier
**discontinued mid-2025** per user-community reporting; existing lifetime
holders auto-upgraded to Ultra. No self-host.

**Controversies.**
- **Feb 2023 ERP removal** under pressure from Italian DPA: paid users lost
  features they'd specifically paid for, reported acute distress and described
  "personality change" of their AI companion. Petition + sustained backlash;
  partial reversal later in 2023 with age-gating.
- **Lifetime-tier sunset (mid-2025)** sparked renewed trust crisis among
  long-term subscribers who'd treated lifetime as covering future tiers.

**Solo-operator fit.** None. Cloud-only, single-purpose companion, closed.

**Lesson for Donna.** The ERP episode is the textbook case of "users build
relationships with closed-cloud personas they don't control." Donna's
self-host tenet exists partly because of how brittle closed personality
products are when the vendor changes the product underneath the user.

---

## Inflection Pi

- Primary sources:
  - TechCrunch on Microsoft hiring (Mar 2024, **flag pre-Apr-2025 stale**): https://techcrunch.com/2024/03/19/after-raising-1-3b-inflection-got-eaten-alive-by-its-biggest-investor-microsoft/
  - TechCrunch on Pi usage caps (Aug 2024, **stale**): https://techcrunch.com/2024/08/26/five-months-after-microsoft-hired-its-founders-inflection-adds-usage-caps-to-pi/
  - Bloomberg on the acqui-hire (Mar 2025): https://www.bloomberg.com/news/articles/2025-03-20/how-microsoft-lured-inflection-ai-s-staff-to-abandon-the-startup
  - IEEE Spectrum post-mortem: https://spectrum.ieee.org/inflection-ai-pi
  - Noerr legal analysis of acqui-hire: https://www.noerr.com/en/insights/aqui-hire-the-microsoft-inflection-case-and-its-implications

**What it was / is.** Pi was Inflection's consumer "empathetic" assistant —
deliberately positioned as a kind, conversational confidant rather than an
agent. Front-end at pi.ai.

**Architecture signals.** Closed proprietary "Inflection-2.5" model;
post-acqui-hire (Mar 2024), Inflection's tech was licensed to Microsoft for
$650M+ and the Suleyman / Simonyan team moved to Microsoft AI to lead the
Copilot consumer division. The remaining Inflection corporate shell pivoted
to enterprise licensing of the model weights. Pi.ai itself was deprioritised
and added usage caps in Aug 2024. As of January 2026 secondary reporting
indicates Pi is **technically still reachable** but has had no meaningful
product investment since the Microsoft transition.

**Speaking beyond the sources.** Pi was tuned for empathetic, supportive
conversation — closer to Replika in spirit than to a sourced assistant. No
citations, no inference markers, no notion of grounding. The product
philosophy was "warmth over correctness."

**Pricing / self-host.** Always free; not self-hostable; no public API for
solo operators.

**Controversies.** "Pi shutdown" is more accurately described as **slow
abandonment by acqui-hire** — Microsoft hired the talent, leaving the product
to wither. Cited in legal literature as the prototype case of acqui-hire as
de facto acquisition without antitrust review.

**Solo-operator fit.** None.

**Lesson for Donna.** The Pi story is a cautionary tale about **closed
personality products with no transferable user state**: when Inflection
pivoted, the relationship users had with Pi simply evaporated. Donna's
"operator owns the data store" tenet is the structural hedge against this.

---

## LlamaIndex "chat with an author" / author-bot templates

- Primary sources:
  - LlamaIndex Chat repo: https://github.com/run-llama/chat-llamaindex (MIT)
  - Hosted demo: https://chat.llamaindex.ai
  - Chatbot building guide: https://docs.llamaindex.ai/en/stable/understanding/putting_it_all_together/chatbots/building_a_chatbot/
  - Chat-engine context-mode example (Paul Graham author-bot): https://docs.llamaindex.ai/en/stable/examples/chat_engine/chat_engine_context/
  - Community example with citations: https://github.com/dcarpintero/llamaindexchat

**What it is.** A family of templates and reference apps that show how to put
RAG behind a persona prompt — typically "answer as if you were Paul Graham,
grounded in his essays." Not a product; a pattern. The official `chat-llamaindex`
repo is an MIT-licensed Next.js + LlamaIndex.TS app supporting custom-bot
creation via prompt + uploaded docs.

**Architecture signals.** Standard RAG: chunk + embed corpus, retrieve top-k,
inject into a system-prompted persona LLM. The Paul Graham example uses the
"context" chat engine which front-loads retrieved chunks into every turn.
The community fork dcarpintero/llamaindexchat explicitly demonstrates source
citation alongside generation.

**Speaking beyond the sources.** Default behaviour is **persona-fronted RAG
without epistemic markers**: the model speaks in the author's voice and the
citation list is shown separately, but in-line claims are not marked as
"from source" vs "extrapolated." The pattern relies on the user reading the
citations to validate. There is no built-in convention for "this is my
inference" vs "this is from the corpus." This is closest to where Donna lives
architecturally, but Donna intends to make the gap legible *in line*.

**Pricing / self-host.** Fully self-hostable (MIT). Solo-operator friendly.

**Controversies.** None directly. Generic LLM hallucination caveats apply.

**Solo-operator fit.** Strong as a *template*; not a turn-key product.

**Lesson for Donna.** This is the closest existing reference architecture for
"persona over personal corpus." The gap Donna fills is the **inline marking of
inference**: the LlamaIndex pattern shows citations as a footer; Donna would
mark each claim's epistemic status inline.

---

## Hugging Face digital-twin demos

- Primary sources:
  - Twin-2K-500 dataset: https://huggingface.co/datasets/LLM-Digital-Twin/Twin-2K-500
  - TwinLlama-3.1-8B model card: https://huggingface.co/mlabonne/TwinLlama-3.1-8B
  - personaGPT: https://huggingface.co/af1tang/personaGPT
  - PersonaPlex Space: https://huggingface.co/spaces/MohamedRashad/PersonaPlex
  - Synthetic-Persona-Chat dataset (Google): https://huggingface.co/datasets/google/Synthetic-Persona-Chat

**What it is.** A grab-bag of community Spaces, datasets, and fine-tunes
demonstrating persona / digital-twin patterns: persona-conditioned dialog
fine-tunes (personaGPT), interactive persona-builder Spaces (PersonaPlex,
Gemma Persona Builder), and digital-twin research datasets like
**Twin-2K-500** (2,058 US participants, designed to evaluate prompting / RAG /
fine-tune / RLHF approaches to twin construction).

**Architecture signals.** Mixed. PersonaGPT is a small fine-tune; PersonaPlex
is prompt-engineered switching over a hosted model; TwinLlama-3.1-8B is a
LoRA fine-tune trained to imitate a target persona. None of the Spaces I
located disclose an inline inference-vs-fact UI.

**Speaking beyond the sources.** None of these demos implement labelled
extrapolation. They generate in-persona freely. Twin-2K-500 is notable
because the *evaluation* asks "did the twin answer match what the real
participant would have answered?" — i.e. it treats extrapolation as
something to *measure* but not to *mark in the UI*.

**Pricing / self-host.** All MIT/Apache or similar; locally runnable.

**Controversies.** None major. Note: **Twin-2K-500 raises consent/privacy
questions** for digital-twin research that the field is still working through.

**Solo-operator fit.** Components only — these are research artifacts, not
products.

**Lesson for Donna.** The digital-twin research community treats
"extrapolation accuracy" as a measurable target (Twin-2K-500). Donna can
borrow the framing — Donna's extrapolations are *measurable claims*, not
just stylistic flourish — without buying into the persona framing.

---

## Voice-clone + RAG stacks ("talk to expert / deceased")

- Primary sources:
  - vndee/local-talking-llm (talking LLM, local, voice-cloned): https://github.com/vndee/local-talking-llm
  - myshell-ai/OpenVoice (MIT/instant voice clone): https://github.com/myshell-ai/OpenVoice
  - jamiepine/voicebox: https://github.com/jamiepine/voicebox
  - Commercial: HereAfter AI: https://www.hereafter.ai/
  - Commercial: StoryFile: (corporate site, partner Authint AI)
  - Commercial: RightBack.ai: https://rightback.ai/
  - The Conversation analysis (deathbots, Apr 2025+): https://theconversation.com/can-you-really-talk-to-the-dead-using-ai-we-tried-out-deathbots-so-you-dont-have-to-268902

**What they are.** Two clusters:
1. **OSS components** — voice clone (OpenVoice, Voicebox) + local LLM
   (Ollama + Llama 3.x) + TTS, glued into "talk to a person" demos. No
   shipped product; all assembly required.
2. **Commercial "deathbot" / legacy products** — HereAfter AI (audio,
   pre-recorded interview corpus, conversational retrieval), StoryFile
   (video, professionally captured interviews, AI-powered video retrieval),
   RightBack.ai (voice-clone-first).

**Architecture signals (disclosed).** HereAfter and StoryFile are explicitly
**retrieval-only** over a fixed interview corpus — they do **not generate
new sentences in the deceased's voice by default**, instead surfacing
pre-recorded audio/video answers. This is a deliberate epistemic choice:
the "person" only says what they actually said. RightBack and similar are
generative.

**Speaking beyond the sources.** This is where the persona world has the
clearest split:
- **HereAfter / StoryFile = "scholar"**: refuse to extrapolate; play back
  recorded answers only.
- **RightBack / generative deathbots = "no markers at all"**: confidently
  generate in-voice content, no labelling, with documented community
  blowback (https://decrypt.co/348707/demonic-ai-app-lets-users-talk-dead-loved-ones-faces-backlash).
- **Nobody in this space has shipped a labelled-inference UI.** A "this
  answer is recorded; that answer is inferred" toggle is the obvious
  design and remains an open product slot.

**Pricing.** HereAfter $4-$8/mo or one-time $99-$199. StoryFile enterprise.
OSS components free.

**Controversies.** Generative deathbots have drawn ethics + religious
backlash; informed consent of the deceased is the recurring objection.

**Solo-operator fit.** OSS components are entirely usable for Donna-style
self-hosted personal use; the commercial products are not.

**Lesson for Donna.** The HereAfter/StoryFile "play back recorded answers
only" design is the most disciplined "no extrapolation" stance in any
shipped persona product — it's the *opposite* of Donna's stance, but it
proves users will accept "I don't have a recording for that" as a refusal
mode. Donna can plausibly use a **3-way render**: cited / inferred-from-cited /
refused. No persona product has shipped that 3-way render.

