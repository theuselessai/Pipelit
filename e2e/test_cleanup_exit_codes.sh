#!/usr/bin/env bash
# Regression guard for run_smoke.sh's exit status.
#
# run_smoke.sh reports its result from an EXIT trap. A trap that ends in a bare
# `exit 0` overrides the status that fired it, so an abort under `set -e` — a
# container that never boots, a missing docker, a failed migration — was
# reported to CI as success with "0 passed, 0 failed". e2e-smoke was green for
# months while asserting nothing.
#
# This drives the real cleanup(), extracted from run_smoke.sh, through every
# path, invoked the way the script invokes it: as an EXIT trap fired by `set -e`.
#
# Usage: ./e2e/test_cleanup_exit_codes.sh

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SMOKE="$SCRIPT_DIR/run_smoke.sh"
FN="$(mktemp)"
trap 'rm -f "$FN"' EXIT

awk '/^cleanup\(\) \{/,/^\}/' "$SMOKE" > "$FN"
if ! grep -q "^cleanup() {" "$FN" || [ "$(wc -l < "$FN")" -lt 5 ]; then
    echo "FATAL: could not extract cleanup() from $SMOKE"
    exit 1
fi

FAILED=0

run_case() {
    local desc="$1" abort_rc="$2" pass="$3" fail="$4" expected="$5"
    local actual
    actual=$(bash -c "
        set -euo pipefail
        MOCK_PID=''; CONTAINER_NAME='no-such-container-$$'
        PASS=$pass; FAIL=$fail
        source '$FN'
        trap cleanup EXIT
        (exit $abort_rc)   # non-zero aborts under set -e, firing the trap
    " > /dev/null 2>&1; echo $?)

    if [ "$actual" = "$expected" ]; then
        printf '  PASS  %-50s exit=%s\n' "$desc" "$actual"
    else
        printf '  FAIL  %-50s exit=%s (expected %s)\n' "$desc" "$actual" "$expected"
        FAILED=1
    fi
}

echo "═══ run_smoke.sh cleanup() exit-status matrix ═══"
#         description                                  abort  pass fail  expected
run_case "all assertions passed"                           0     7    0    0
run_case "some assertions failed"                          0     5    2    1
run_case "no assertions ran"                               0     0    0    1
run_case "aborted: container never booted"                 1     0    0    1
run_case "aborted: docker missing"                       127     0    0  127
run_case "aborted mid-run, some passes recorded"           2     4    0    2
echo ""

if [ "$FAILED" -ne 0 ]; then
    echo "FAIL: cleanup() can report a failed run as success"
    exit 1
fi
echo "OK: every failure mode surfaces a non-zero exit status"
