#!/usr/bin/env bash
# Run sarc-governance audit against the bundled pass/fail traces and print exit codes.
#
# Usage (from repo root):
#   pip install -e .
#   bash examples/audit_trace_file/run_audit.sh
#
# Uses `python -m sarc_governance.cli` so the script works from a fresh clone
# after an editable install, without requiring sarc-governance on PATH.
set -u

HERE="$(cd "$(dirname "$0")" && pwd)"
SPEC="$HERE/spec.yaml"

# Prefer python -m form; fall back to the installed CLI entry point.
if python -m sarc_governance.cli --help > /dev/null 2>&1; then
    SARC="python -m sarc_governance.cli"
elif command -v sarc-governance > /dev/null 2>&1; then
    SARC="sarc-governance"
else
    echo "ERROR: sarc-governance not found. Run: pip install -e ." >&2
    exit 1
fi

run() {
    local label="$1" trace="$2"
    echo "=== $label ==="
    $SARC audit "$SPEC" "$trace"
    echo "exit=$?"
    echo
}

run "PASS trace" "$HERE/trace_pass.json"
run "FAIL trace" "$HERE/trace_fail.json"
