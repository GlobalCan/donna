#!/usr/bin/env bash
# scripts/test-freeze-hook.sh
#
# Smoke-test scripts/donna-freeze.sh against allowed and disallowed
# commit-message subjects. Doesn't make actual commits — runs the hook
# script directly against tempfiles.
#
# Usage:
#   bash scripts/test-freeze-hook.sh

set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
HOOK="$REPO_ROOT/scripts/donna-freeze.sh"

if [[ ! -f "$HOOK" ]]; then
    echo "Error: cannot find $HOOK" >&2
    exit 1
fi

PASS=0
FAIL=0

run_test() {
    local label="$1"
    local message="$2"
    local expected="$3"  # 0 = should allow, 1 = should reject
    local tmpfile actual
    tmpfile="$(mktemp)"
    printf "%s\n" "$message" > "$tmpfile"
    if bash "$HOOK" "$tmpfile" >/dev/null 2>&1; then
        actual=0
    else
        actual=1
    fi
    rm -f "$tmpfile"
    if [[ "$actual" == "$expected" ]]; then
        echo "  PASS: $label"
        PASS=$((PASS + 1))
    else
        echo "  FAIL: $label (expected $expected, got $actual)"
        FAIL=$((FAIL + 1))
    fi
}

echo "Allowed messages (expect ALLOW = exit 0)"
run_test "fix:"       "fix: stale URL in README"               0
run_test "chore:"     "chore: bump httpx 0.27 -> 0.28"          0
run_test "docs:"      "docs: clarify backup runbook"            0
run_test "security:"  "security: rotate Slack token"            0
run_test "Merge"      "Merge branch 'main' into feature/x"      0
run_test "Revert"     "Revert \"feat: add bad thing\""          0
run_test "leading blank line + fix" $'\nfix: late-line subject' 0
run_test "comment line then fix" $'# please commit\nfix: ok'    0

echo
echo "Disallowed messages (expect REJECT = exit 1)"
run_test "feat:"      "feat: add new tool"                      1
run_test "refactor:"  "refactor: rename module"                  1
run_test "test:"      "test: more coverage"                      1
run_test "perf:"      "perf: speed up retrieval"                 1
run_test "style:"     "style: format with black"                 1
run_test "no prefix"  "Just doing some work"                     1
run_test "wip"        "wip: experiments"                         1
run_test "uppercase"  "FIX: stale URL"                           1
run_test "all-caps"   "DOCS: SOMETHING"                          1
run_test "empty"      ""                                          1
run_test "comments only" $'# only comments\n#nothing real'       1

echo
echo "Summary: $PASS passed, $FAIL failed."
if [[ "$FAIL" -gt 0 ]]; then
    exit 1
fi
