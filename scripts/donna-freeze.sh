#!/usr/bin/env bash
# scripts/donna-freeze.sh
#
# Donna v0.7.3 freeze rule (DZ-1, DZ-2 from docs/PATH_3_INVARIANTS.md §20).
#
# This script is invoked as a git commit-msg hook. Wire it into
# .git/hooks/commit-msg via scripts/install-freeze-hook.sh.
#
# Behavior:
#   - Reads the commit message file (passed as $1 by git).
#   - Allows the commit if its first non-empty, non-comment line begins
#     with one of:  fix:  chore:  docs:  security:
#   - Allows automatic Merge / Revert commits (created by git itself).
#   - Rejects everything else with a message explaining the freeze.
#
# Bypass:  git commit --no-verify
#   This is intentional. The freeze rule exists to make new strategic
#   capabilities a CONSCIOUS choice for an operator who has agreed in
#   PATH_3_INVARIANTS.md that Donna v0.7.3 is feature-frozen. Bypassing
#   should be rare. If you find yourself bypassing more than once per
#   quarter, the freeze policy needs revisiting in PATH_3_INVARIANTS.md
#   §20 — not in the hook.
#
# Why commit-msg, not pre-commit:
#   commit-msg runs AFTER the message is composed. It can inspect the
#   actual message content. pre-commit runs before, when the message
#   doesn't exist yet.
#
# Why client-side only:
#   Server-side enforcement (PR-title validation) is a separate concern
#   that belongs in a GitHub Action. This hook catches the more common
#   case: client-side commits made by the operator on a feature branch.

set -euo pipefail

COMMIT_MSG_FILE="${1:-}"
if [[ -z "$COMMIT_MSG_FILE" || ! -f "$COMMIT_MSG_FILE" ]]; then
    echo "donna-freeze: no commit message file passed (got '$COMMIT_MSG_FILE')" >&2
    exit 1
fi

# Read the first non-empty, non-comment line from the commit message.
# Git's default commit message includes leading blank lines and
# instructional comments (lines starting with '#'). We want the
# operator's actual subject line.
FIRST_LINE=""
while IFS= read -r line || [[ -n "$line" ]]; do
    # Strip leading whitespace.
    stripped="${line#"${line%%[![:space:]]*}"}"
    [[ -z "$stripped" ]] && continue
    [[ "$stripped" == \#* ]] && continue
    FIRST_LINE="$stripped"
    break
done < "$COMMIT_MSG_FILE"

if [[ -z "$FIRST_LINE" ]]; then
    echo "donna-freeze: empty commit message" >&2
    exit 1
fi

# Exempt: automatic merge / revert commits from git itself.
# Operator can't easily change the prefix git generates; rejecting
# these would just be friction for legitimate merges.
if [[ "$FIRST_LINE" =~ ^Merge[[:space:]] ]]; then
    exit 0
fi
if [[ "$FIRST_LINE" =~ ^Revert[[:space:]] ]]; then
    exit 0
fi

# Allowed prefixes per DZ-1.
if [[ "$FIRST_LINE" =~ ^(fix|chore|docs|security): ]]; then
    exit 0
fi

# Reject. Print a long-form message so the operator understands why
# and how to bypass intentionally.
cat >&2 <<EOF
donna-freeze: commit rejected.

  Donna v0.7.3 freeze rule (DZ-1, PATH_3_INVARIANTS §20).

  This repo is feature-frozen pending capability migration to the
  new system. Commit messages must begin with one of:

    fix:        - bug fix in existing behavior
    chore:      - maintenance, dependency bumps, refactors that don't
                  change behavior
    docs:       - documentation only
    security:   - security patch

  Your message starts with:
    ${FIRST_LINE}

  If this is a Merge or Revert commit, git should have prefixed it
  automatically; check 'git log --oneline -1 HEAD' to see what got
  composed.

  If this commit is intentionally outside the freeze scope (a one-off
  ops change you've agreed to in a planning session, a reverted feature,
  etc.), bypass with:

    git commit --no-verify

  Bypassing is a conscious choice. The freeze is a discipline, not a
  technical lock. If you find yourself bypassing more than once per
  quarter, that's a signal to revisit the freeze policy in
  docs/PATH_3_INVARIANTS.md §20.

EOF

exit 1
