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

