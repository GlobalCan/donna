# Scheduler smoke-test runbook

Donna has had a working cron scheduler since v0.2.0 (`src/donna/jobs/scheduler.py`,
slash commands `/schedule` + `/schedules`, CLI `botctl schedule add|list|disable`),
but it's never been live-smoke-tested in production. The operator reported in
2026-04-30 that they thought scheduled tasks didn't exist — a discoverability
gap that this runbook closes by walking the first end-to-end fire.

## Goal

Confirm that:

1. `/schedule` accepts a cron expression and persists a row.
2. The scheduler thread (running inside `donna-worker`) ticks once a minute.
3. At the next-fire time, a job is enqueued and runs to completion.
4. The job's final_text is delivered to Discord.

## Pre-flight

Run on the laptop, not the droplet. The smoke test only requires Discord
access — it doesn't need SSH.

```text
1. Bot is online (Discord shows Donna#3183 as Online)
2. You are listed in DISCORD_ALLOWED_USER_ID (you can DM the bot at all)
3. Current UTC time + 2 minutes ≤ a cron tick you'll wait for
```

## The test

### Step 1 — schedule a 1-minute-from-now task

In the Discord DM with Donna, send:

```text
/schedule cron_expr:"* * * * *" task:"Reply with exactly the words SCHED_OK and nothing else."
```

Donna should respond within ~1s with:

```text
📅 scheduled sched_<id> — `* * * * *`
   next fire: <UTC timestamp> UTC
   task: Reply with exactly the words SCHED_OK and nothing else.
```

If you see `❌ invalid cron expression`, the cron was rejected at parse time.
The format is `minute hour day month dayOfWeek`. `* * * * *` = every minute.

### Step 2 — wait for the next minute boundary

Look at the `next fire` timestamp in the response. Wait until at least
60s after that time. The scheduler ticks every 60s, so worst case is one
minute lag between the fire time and the actual job creation.

### Step 3 — verify the bot replied

Within ~30s of the next-fire time, Donna should DM you:

```text
• SCHED_OK
```

(The `•` prefix is the standard outbox marker for non-tainted updates.)

If you see SCHED_OK: **the scheduler is fully working.** Update PR #36's
KNOWN_ISSUES table to flip "Scheduler — never smoke-tested in prod" from
OPEN to ✅ FIXED.

If you don't see anything within 2 minutes:

- **Check `/schedules`** — does the schedule still appear with a
  `last fired: never` line? If so the tick didn't fire. Likely the
  scheduler thread isn't running. SSH to the droplet and look at
  `docker compose logs -f worker | grep scheduler`. There should be a
  `scheduler.start` log line and one `scheduler.tick` (or
  `scheduler.fired`) log line per minute.
- **Check the `jobs` table** — `botctl jobs --since 5m` (run from the
  droplet via `docker compose exec bot botctl jobs --since 5m`).
  If a job exists with status `done` but you didn't see the message,
  the scheduler fired but delivery is broken. Check the
  `outbox_updates` table.

### Step 4 — clean up the every-minute schedule

If you leave the `* * * * *` schedule active you'll keep getting hourly
SCHED_OK pings forever. Disable it:

```text
/schedules           # find the schedule id
```

Then on the laptop or droplet:

```bash
botctl schedule disable sched_<id>
```

(There's no Discord slash command to disable schedules yet — that's a
follow-up if it becomes annoying. For now CLI-only.)

## Suggested second smoke test — daily morning brief

Once the every-minute test passes, schedule something useful:

```text
/schedule cron_expr:"0 13 * * *" task:"What's new in AI today? Search the web for the most important development in the last 24 hours and summarize it in 4 bullet points."
```

13:00 UTC = ~9am EDT, which is reasonable. Walk away, check Discord at
9am tomorrow.

## What to flip in the docs after success

- `docs/SESSION_RESUME.md` — under "Still open", remove the line about the
  scheduler never being smoke-tested.
- `docs/KNOWN_ISSUES.md` — same.
- `CHANGELOG.md` — add a "Validated live" line under v0.4.1 noting the
  scheduler smoke test passed end-to-end.

## Why this runbook exists

Recurring pattern: a feature ships in code with tests, but never gets
exercised against real Discord/real timing. The user then forgets it
exists and treats it as missing — at which point the right fix isn't
"ship more code", it's "exercise the feature once and tell the user it
exists." This runbook is the exercise step.
