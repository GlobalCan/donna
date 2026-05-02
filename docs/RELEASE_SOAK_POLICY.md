# Release soak policy

**After platform-level changes, soak the deploy for 24h before adding features.**

Codex 2026-05-01 review: "Four releases in 72h is acceptable once. Do not normalize it." This document is the rule.

---

## What counts as a "platform-level change"

| Type | Soak required? |
|---|---|
| Schema migration | YES |
| Adapter retool (Discord -> Slack, etc.) | YES |
| Worker process model change (e.g. async runner addition) | YES |
| Entrypoint / Docker / compose change | YES |
| Secret rotation | YES |
| New external dependency in pyproject.toml | YES |
| Bug fix to an existing handler | NO |
| New botctl command (read-only) | NO |
| Doc update | NO |
| New eval golden | NO |
| New tool in registry | YES — first time only; subsequent additions NO |

When in doubt: assume YES. The cost of waiting 24h is one day; the cost of compounding two latent bugs across releases is worse.

---

## What "soaking" means

After the merge + tag + GitHub release + droplet deploy:

1. **Live smoke**: run `botctl slack-doctor`. Expect all green.
2. **Operator usage**: at least one real DM exchange + one slash command on the new build. Confirms basic happy path.
3. **24h quiet window**: no new merges to main during this window. Branches CAN be open in development; they just don't merge.
4. **Inspect at the end**: `botctl jobs --since=1d`, `botctl cost`, `botctl dead-letter list`, `botctl async-tasks list`. Look for:
   - Stuck jobs (status=running, lease_until expired)
   - Cost spike vs prior 24h
   - New error_codes in dead-letter
   - Failed async_tasks (status=failed)

If any of those surface a regression, fix forward (don't roll back) and reset the soak window.

---

## Hot-fix exception

A real production fire (V50-1-style infinite retry storm, security issue, secret leak) bypasses the soak. Fix forward immediately, then resume the soak from the new baseline.

The exception requires the **fix to be focused on the fire**. Don't bundle "while we're hotfixing, also let me ship feature X." Two reasons:

1. The cost of "incident landed clean" is one operator-day; the cost of "incident + half-baked feature both landed at 2am" is unbounded.
2. A focused hotfix gets reviewed differently — Codex / second-reviewer can pattern-match on "this is incident response" without spending budget on the bundled feature.

---

## Cadence target

- **0-2 platform changes per quarter** is healthy.
- **3-5 per quarter** is active foundation work.
- **6+ per quarter** is a code smell. Reconsider — the design is probably churning.

The 2026-04-23 → 2026-05-02 stretch shipped v0.3.0 → v0.6 (≈ 7 platform changes in 9 days). That was bootstrap mode. **Not the steady-state cadence.**

---

## Verification

The policy isn't lint-enforced (a 24h timer test would just delay CI). It's an operational discipline. The visible signal is that platform-change PRs include a `Soak window:` line in the PR description specifying:

- The soak start time
- The botctl commands run for verification
- Any anomalies caught + how addressed

If a PR is marked `Skip soak: hotfix for <fire>` it must reference the fire (incident report, log line, etc.).

---

## When this policy can change

Update this document, get a review, land it. The policy is meant to evolve as the project's risk profile changes — when Donna has a regression test suite that catches the kind of bugs the soak window catches now, the soak can shrink. Currently (v0.6) the regression spine is 4 tests; the soak is the second line of defense.
