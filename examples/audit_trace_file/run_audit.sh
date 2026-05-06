#!/usr/bin/env bash
# Run sarc-governance audit against the bundled pass/fail traces and print exit codes.
set -u

HERE="$(cd "$(dirname "$0")" && pwd)"
SPEC="$HERE/spec.yaml"

run() {
    local label="$1" trace="$2"
    echo "=== $label ==="
    sarc-governance audit "$SPEC" "$trace"
    echo "exit=$?"
    echo
}

run "PASS trace" "$HERE/trace_pass.json"
run "FAIL trace" "$HERE/trace_fail.json"
