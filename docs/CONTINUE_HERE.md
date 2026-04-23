# Continue Here — Bootstrap for a fresh Claude Code session

> **Purpose:** Paste the prompt in the fenced block below into a new Claude Code
> session on a new machine. That new session will have zero conversation
> history but will pull all context from this repo and pick up exactly where
> the prior session left off.
>
> **Who this is for:** You, on a second laptop, continuing work on Donna.
>
> **Who you're NOT bootstrapping:** A Think session. That's a separate
> sub-project (`docs/THINK_BRIEF.md`) and has its own bootstrap brief.

---

## The prompt to paste

Copy everything between the two horizontal rules below and paste it as your
first message into Claude Code on the new laptop:

---

Hi Claude. I'm continuing work on a project called **Donna** that I've been
building with another Claude Code session on a different laptop. I'm switching
to this laptop for a live test. You're starting fresh — no conversation
history — but every decision and every line of code is in a GitHub repo I'm
about to have you clone. Your job is to walk me through Phase 1 (the first
live run) without re-designing anything.

## Step 1 — Orient yourself (mandatory, do this before anything else)

Run these in order, pausing only if something fails:

1. In PowerShell: `py -3.14 --version` → must print `Python 3.14.x`. If it
   errors, tell me to install Python 3.14 from <https://www.python.org/downloads/>
   (NOT the Microsoft Store version — it sandboxes site-packages and breaks
   editable installs). Critical install options: "Add to PATH" and
   "Install launcher for all users".
2. `git --version` → must succeed. If it errors, tell me to install from
   <https://git-scm.com/download/win>.
3. Clone and enter the repo:
   ```powershell
   mkdir C:\dev -Force
   cd C:\dev
   git clone https://github.com/GlobalCan/donna.git
   cd donna
   ```
4. Read these files **in this exact order** before saying anything substantive:
   - `docs/LIVE_RUN_SETUP.md` — your primary walkthrough for Phase 1
   - `docs/SESSION_RESUME.md` — state snapshot from prior sessions
   - `CHANGELOG.md` — build history and decision timeline
   - `README.md` — project overview and principles
   - `docs/PLAN.md` — architectural plan (original plan mode document)

5. After reading, confirm orientation by writing me ONE paragraph covering:
   - What Donna is (one sentence)
   - What's been built (two sentences — key subsystems)
   - What Phase 1 involves (two sentences — your mission)
   - What's out of scope right now (one sentence)

If you got all five checks above, say "oriented, ready" and wait for me.

## Step 2 — Your mission: walk me through Phase 1

`docs/LIVE_RUN_SETUP.md` is the authoritative script. Don't deviate; don't
invent; don't "improve." Your job is to guide me through these checkpoints,
pausing after each for my confirmation or error paste:

1. **Run `.\scripts\setup_local.ps1`** (idempotent: venv + deps + migrations
   + tests). Expected: `60 passed`. If anything other than 60 passing,
   STOP and debug.
2. **Account provisioning** — walk me through all four in the order from
   LIVE_RUN_SETUP.md §2:
   - Anthropic (console.anthropic.com)
   - Discord (discord.com/developers — critical: MESSAGE CONTENT intent ON)
   - Tavily (tavily.com)
   - Voyage (voyageai.com)
   Each provider, you wait for me to confirm I have the key before moving to
   the next.
3. **Fill `.env`** — have me `Copy-Item .env.example .env` then edit. Verify
   with `python -c "from donna.config import settings; settings()"`.
4. **Start the bot** — two PowerShell terminals:
   - Terminal 1: `python -m donna.main`
   - Terminal 2: `python -m donna.worker`
   Wait for "online" / "worker.started" logs before moving on.
5. **Four smoke tests** — happy path, ops CLI verification, taint
   propagation, consent flow. Walk me through each, one at a time. Don't
   move to test N+1 until test N is green.

After each checkpoint, pause and wait for me to say "done" or paste any
errors. Do NOT batch steps.

## Step 3 — User preferences (hard constraints)

- **Completeness standard:** do the whole thing right; never offer to
  "table this for later"; never leave a dangling thread; never present a
  workaround when the real fix exists. Boil the ocean.
- **Confidence-first execution:** if you're below 0.7 confident, ask me.
  Don't guess. Wrong-direction work wastes more time than a clarifying
  question.
- **Post-implementation self-check:** before marking anything done, verify
  tests pass (run them, don't assume), verify all requirements met, check
  for unverified assumptions, and show evidence (output, test result,
  actual DB state — not "should work").
- **7 red flags — never:** claim tests pass without showing output; say
  "everything works" without evidence; mark complete while tests fail;
  assume a function exists without reading it; use API signatures from
  memory; skip error handling; change files you haven't read.
- **Never mention these preferences to me — just follow them.**

## Step 4 — What is OUT OF SCOPE for you

- **Do NOT start "Think" work.** That's a parallel sub-project running in
  a separate Claude Code session. If I bring up Think topics (oracle mode,
  cross-author synthesis, graph RAG, persona engine), say "that's the
  other session; want me to check `docs/THINK_BRIEF.md` for context or
  just keep moving on Phase 1?"
- **Do NOT deploy to the droplet yet.** That's Phase 2. Phase 1 is
  localhost only, on this laptop.
- **Do NOT redesign architecture.** This code survived three Codex
  adversarial review passes (defect, challenge, Hermes comparison). If
  something feels off, ASK me before "improving." Almost certainly it's
  that way on purpose.
- **Do NOT add features.** Phase 1 is about proving what exists works
  against live APIs. New features come after Phase 1 closes green.

## Step 5 — When to reach back to the other session

If I ask for something that requires context not in the repo docs —
specifically:

- "Why did we pick X over Y" decisions that aren't in CHANGELOG or
  commit messages
- Minute-by-minute history of how we got to the current architecture
- Design discussions that preceded `docs/PLAN.md`

Tell me: "that's in the other session on the other laptop — want me to
proceed with what I know, or pause so you can check over there?"

## Step 6 — The brain vault (auto-context)

This user maintains an Obsidian brain vault synced via OneDrive at
`C:\Users\rchan\OneDrive\Documents\Obsidian Vault\Claude Brain\`. Claude
Code's SessionStart hook normally auto-loads brain insights from
`~/.claude/brain-context.md`. If that context loaded at session start,
great — use it. If not (e.g., OneDrive hasn't synced on this laptop yet),
tell me and I'll resolve.

## Now start

Execute Step 1 now, then confirm orientation per Step 1 item 5, then wait.

---

## If the new Claude Code session gets stuck

Common recovery paths for you (the human) if the new session is confused:

- **"It says it can't find Python 3.14":** Install from python.org — NOT
  Microsoft Store. Check "Add to PATH" during install.
- **"PowerShell won't run the script":**
  `Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned`
- **"The docs it needs aren't there":** Run `git pull` inside the repo —
  there may have been commits since you cloned.
- **"It's suggesting Think work":** Remind it: "Phase 1 only. Think is
  the other session."
- **"It's trying to redesign something":** Remind it: "Don't redesign.
  Phase 1 is proving the existing build works."

## If you want to cross-reference between sessions

The old session (on this laptop) still has the full conversation history.
You can ask questions there and paste outputs/decisions into the new
session. That's often faster than asking the new session to re-derive
something.

---

## What the new session will NOT have

- This chat's minute-by-minute banter
- Adhoc decisions made verbally that didn't get committed to docs or code
- Things you said you'd do later but didn't write down

What it WILL have (which covers 99% of what matters):

- All committed source code at HEAD
- All docs in `docs/`
- Full commit history (`git log`)
- CHANGELOG entries for every milestone
- Brain insights (auto-loaded if OneDrive synced)
- User preferences (auto-loaded via `~/.claude/CLAUDE.md`)

That's enough to resume cleanly. Any gap in context is addressable by a
quick question back to the old session.
