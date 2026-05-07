"""sarc-governance command-line interface.

A small, dependency-free CLI for working with SARC constraint specs and
runtime traces. Useful for CI gating, local validation, and quick demos.

Subcommands
-----------
``validate SPEC_PATH``
    Load a YAML/JSON spec, validate constraint structure and class/point
    compatibility, and print a per-constraint summary.

``list-predicates``
    List the names of every predicate registered in
    :mod:`sarc_governance.predicates` (built-ins plus anything registered by
    importable plugins).

``audit SPEC_PATH TRACE_PATH``
    Load a spec and a JSON trace file (a list of ``TraceRecord`` dicts or
    the higher-level ``sarc_eval.py`` schema) and run :func:`audit_trace`.
    Exits non-zero if any discrepancies are found, unless
    ``--allow-discrepancies`` is passed.

``demo procurement``
    Run the bundled procurement demo end-to-end.

Output is plain text, line-oriented, and suitable for CI logs.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
from typing import Any, Dict, List, Optional, Sequence

from sarc_governance import audit_trace, predicates
from sarc_governance.hashchain import verify_chain
from sarc_governance.policy import diff_policies, inspect_policy
from sarc_governance.specs import load_spec


# ---------------------------------------------------------------------------
# Subcommand implementations
# ---------------------------------------------------------------------------


def cmd_validate(args: argparse.Namespace) -> int:
    spec_path = pathlib.Path(args.spec_path)
    try:
        spec = load_spec(spec_path)
    except FileNotFoundError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    except (ValueError, ImportError) as e:
        print(f"error: invalid spec: {e}", file=sys.stderr)
        return 1

    print(f"spec: {spec_path}")
    print(f"constraints: {len(spec)}")
    if not spec.constraints:
        print("(no constraints declared)")
        return 0

    width = max(len(c.id) for c in spec.constraints)
    print()
    print(f"  {'id'.ljust(width)}  class       point  response")
    print(f"  {'-' * width}  ----------  -----  --------")
    for c in spec.constraints:
        print(
            f"  {c.id.ljust(width)}  "
            f"{c.klass.value.ljust(10)}  "
            f"{c.verif.value.ljust(5)}  "
            f"{c.response.value}"
        )
    return 0


def cmd_list_predicates(args: argparse.Namespace) -> int:
    names = predicates.available()
    if not names:
        print("(no predicates registered)")
        return 0
    if args.quiet:
        for n in names:
            print(n)
        return 0
    print(f"registered predicates: {len(names)}")
    for n in names:
        fn = predicates.get(n)
        doc = (fn.__doc__ or "").strip().splitlines()[0] if fn.__doc__ else ""
        if doc:
            print(f"  {n}  -- {doc}")
        else:
            print(f"  {n}")
    return 0


def cmd_audit(args: argparse.Namespace) -> int:
    spec_path = pathlib.Path(args.spec_path)
    trace_path = pathlib.Path(args.trace_path)
    try:
        spec = load_spec(spec_path)
    except FileNotFoundError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    except (ValueError, ImportError) as e:
        print(f"error: invalid spec: {e}", file=sys.stderr)
        return 1

    if not trace_path.exists():
        print(f"error: trace file not found: {trace_path}", file=sys.stderr)
        return 2
    try:
        trace = json.loads(trace_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        print(f"error: trace is not valid JSON: {e}", file=sys.stderr)
        return 1
    if not isinstance(trace, list):
        print(
            f"error: trace must be a JSON list of records; got {type(trace).__name__}",
            file=sys.stderr,
        )
        return 1

    discrepancies = audit_trace(
        spec, trace, check_attribution=not args.no_attribution
    )

    print(f"spec: {spec_path}  ({len(spec)} constraints)")
    print(f"trace: {trace_path}  ({len(trace)} records)")
    if not discrepancies:
        print("audit: PASS  (no discrepancies)")
        return 0

    print(f"audit: FAIL  ({len(discrepancies)} discrepancies)")
    by_type: Dict[str, int] = {}
    for d in discrepancies:
        by_type[d["type"]] = by_type.get(d["type"], 0) + 1
    for t, n in sorted(by_type.items()):
        print(f"  {t}: {n}")
    print()
    for d in discrepancies:
        print(
            f"  [{d['type']}] action={d['action_id']} "
            f"constraint={d['constraint']}: {d['message']}"
        )

    if args.allow_discrepancies:
        return 0
    return 1


def cmd_policy_inspect(args: argparse.Namespace) -> int:
    spec_path = pathlib.Path(args.spec_path)
    try:
        spec = load_spec(spec_path)
    except FileNotFoundError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    except (ValueError, ImportError) as e:
        print(f"error: invalid spec: {e}", file=sys.stderr)
        return 1

    summary = inspect_policy(spec)
    if args.json:
        print(json.dumps(summary, indent=2, sort_keys=True))
        return 0

    print(f"spec: {spec_path}")
    print(f"checksum: {summary['checksum']}")
    print(f"constraints: {summary['constraint_count']}")
    if summary["by_class"]:
        parts = ", ".join(f"{k}={v}" for k, v in summary["by_class"].items())
        print(f"by class: {parts}")
    if summary["by_point"]:
        parts = ", ".join(f"{k}={v}" for k, v in summary["by_point"].items())
        print(f"by point: {parts}")
    if not summary["constraints"]:
        return 0
    print()
    width = max(len(c["id"]) for c in summary["constraints"])
    print(f"  {'id'.ljust(width)}  class       point  predicate")
    print(f"  {'-' * width}  ----------  -----  ---------")
    for c in summary["constraints"]:
        print(
            f"  {c['id'].ljust(width)}  "
            f"{c['class'].ljust(10)}  "
            f"{c['verif'].ljust(5)}  "
            f"{c['predicate']}"
        )
    return 0


def cmd_policy_diff(args: argparse.Namespace) -> int:
    old_path = pathlib.Path(args.old_spec)
    new_path = pathlib.Path(args.new_spec)
    try:
        old_spec = load_spec(old_path)
        new_spec = load_spec(new_path)
    except FileNotFoundError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    except (ValueError, ImportError) as e:
        print(f"error: invalid spec: {e}", file=sys.stderr)
        return 1

    diff = diff_policies(old_spec, new_spec)
    if args.json:
        print(json.dumps(diff, indent=2, sort_keys=True))
    else:
        cs = diff["checksum"]
        print(f"old: {old_path}  ({cs['old']})")
        print(f"new: {new_path}  ({cs['new']})")
        print(
            f"changes: +{len(diff['added'])}  -{len(diff['removed'])}  "
            f"~{len(diff['changed'])}  ={len(diff['unchanged'])}"
        )
        if diff["added"]:
            print()
            print("added:")
            for c in diff["added"]:
                print(f"  + {c['id']} ({c['class']}/{c['verif']} -> {c['response']})")
        if diff["removed"]:
            print()
            print("removed:")
            for c in diff["removed"]:
                print(f"  - {c['id']} ({c['class']}/{c['verif']} -> {c['response']})")
        if diff["changed"]:
            print()
            print("changed:")
            for c in diff["changed"]:
                print(f"  ~ {c['id']} ({', '.join(c['fields'])})")
                for f in c["fields"]:
                    print(f"      {f}: {c['before'][f]!r} -> {c['after'][f]!r}")

    if args.exit_code and (diff["added"] or diff["removed"] or diff["changed"]):
        return 1
    return 0


def cmd_trace_verify_chain(args: argparse.Namespace) -> int:
    trace_path = pathlib.Path(args.trace_path)
    if not trace_path.exists():
        print(f"error: trace file not found: {trace_path}", file=sys.stderr)
        return 2

    records: List[Dict[str, Any]] = []
    suffix = trace_path.suffix.lower()
    text = trace_path.read_text(encoding="utf-8")
    try:
        if suffix == ".jsonl":
            for line in text.splitlines():
                line = line.strip()
                if not line:
                    continue
                records.append(json.loads(line))
        else:
            data = json.loads(text)
            if isinstance(data, list):
                records = data
            else:
                print(
                    f"error: JSON trace must be a list of records; got {type(data).__name__}",
                    file=sys.stderr,
                )
                return 1
    except json.JSONDecodeError as e:
        print(f"error: trace is not valid JSON: {e}", file=sys.stderr)
        return 1

    breaks = verify_chain(records)
    if args.json:
        out = {
            "trace": str(trace_path),
            "record_count": len(records),
            "breaks": [b.to_dict() for b in breaks],
            "ok": not breaks,
        }
        print(json.dumps(out, indent=2, sort_keys=True))
    else:
        print(f"trace: {trace_path}  ({len(records)} records)")
        if not breaks:
            print("hash chain: OK")
        else:
            print(f"hash chain: BROKEN  ({len(breaks)} issue(s))")
            for b in breaks:
                msg = f"  index={b.index}  reason={b.reason}"
                if b.expected is not None:
                    msg += f"  expected={b.expected}"
                if b.actual is not None:
                    msg += f"  actual={b.actual}"
                print(msg)

    return 0 if not breaks else 1


def cmd_trace_export(args: argparse.Namespace) -> int:
    """Export a SQLite trace store to JSONL."""
    from sarc_governance.stores import SQLiteTraceStore

    store_path = pathlib.Path(args.store_path)
    if not store_path.exists():
        print(f"error: store file not found: {store_path}", file=sys.stderr)
        return 2
    out_path = pathlib.Path(args.out_path)
    store = SQLiteTraceStore(store_path)
    try:
        n = store.export_jsonl(out_path, session_id=args.session_id)
    finally:
        store.close()
    print(f"exported {n} record(s) from {store_path} -> {out_path}")
    return 0


def cmd_demo(args: argparse.Namespace) -> int:
    if args.demo_name == "procurement":
        return _run_procurement_demo()
    print(f"error: unknown demo {args.demo_name!r}", file=sys.stderr)
    return 2


def _run_procurement_demo() -> int:
    import asyncio
    import importlib.util

    demo_path = (
        pathlib.Path(__file__).resolve().parent.parent.parent
        / "examples"
        / "procurement_agent"
        / "run_demo.py"
    )
    if not demo_path.exists():
        print(
            "error: procurement demo script not found at "
            f"{demo_path}; run from a source checkout",
            file=sys.stderr,
        )
        return 2
    spec = importlib.util.spec_from_file_location("_sarc_governance_demo", demo_path)
    if spec is None or spec.loader is None:  # pragma: no cover
        print("error: failed to load demo module", file=sys.stderr)
        return 1
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    asyncio.run(module.main())
    return 0


# ---------------------------------------------------------------------------
# Argparse wiring
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sarc-governance",
        description="SARC runtime governance CLI: validate specs, list predicates, audit traces.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=_version_string(),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_validate = sub.add_parser(
        "validate",
        help="Load a YAML/JSON constraint spec and print a summary.",
    )
    p_validate.add_argument("spec_path", help="Path to a YAML or JSON spec file.")
    p_validate.set_defaults(func=cmd_validate)

    p_list = sub.add_parser(
        "list-predicates",
        help="List names of registered predicates.",
    )
    p_list.add_argument(
        "-q", "--quiet", action="store_true", help="Print names only, one per line."
    )
    p_list.set_defaults(func=cmd_list_predicates)

    p_audit = sub.add_parser(
        "audit",
        help="Audit a JSON trace file against a spec.",
    )
    p_audit.add_argument("spec_path", help="Path to a YAML or JSON spec file.")
    p_audit.add_argument(
        "trace_path", help="Path to a JSON trace file (list of TraceRecord dicts)."
    )
    p_audit.add_argument(
        "--allow-discrepancies",
        action="store_true",
        help="Exit 0 even if discrepancies are found (still printed).",
    )
    p_audit.add_argument(
        "--no-attribution",
        action="store_true",
        help="Skip attribution-completeness checks (action-level traces only).",
    )
    p_audit.set_defaults(func=cmd_audit)

    # ----- policy ------------------------------------------------------
    p_policy = sub.add_parser(
        "policy",
        help="Policy lifecycle: inspect a spec or diff two specs.",
    )
    policy_sub = p_policy.add_subparsers(dest="policy_command", required=True)

    p_policy_inspect = policy_sub.add_parser(
        "inspect",
        help="Print a structured summary of a spec (counts, checksum, predicates).",
    )
    p_policy_inspect.add_argument("spec_path", help="Path to a YAML or JSON spec file.")
    p_policy_inspect.add_argument(
        "--json", action="store_true", help="Emit JSON instead of plain text."
    )
    p_policy_inspect.set_defaults(func=cmd_policy_inspect)

    p_policy_diff = policy_sub.add_parser(
        "diff",
        help="Show added / removed / changed constraints between two specs.",
    )
    p_policy_diff.add_argument("old_spec", help="Path to the OLD spec.")
    p_policy_diff.add_argument("new_spec", help="Path to the NEW spec.")
    p_policy_diff.add_argument(
        "--json", action="store_true", help="Emit JSON instead of plain text."
    )
    p_policy_diff.add_argument(
        "--exit-code",
        action="store_true",
        help="Exit non-zero if any differences are found (CI gate).",
    )
    p_policy_diff.set_defaults(func=cmd_policy_diff)

    # ----- trace -------------------------------------------------------
    p_trace = sub.add_parser(
        "trace",
        help="Trace store utilities: verify hash chain, export from SQLite store.",
    )
    trace_sub = p_trace.add_subparsers(dest="trace_command", required=True)

    p_trace_verify = trace_sub.add_parser(
        "verify-chain",
        help="Verify the SHA-256 hash chain of a trace JSON or JSONL file.",
    )
    p_trace_verify.add_argument(
        "trace_path",
        help="Path to a trace file. .jsonl is line-delimited; .json is a JSON list.",
    )
    p_trace_verify.add_argument(
        "--json", action="store_true", help="Emit JSON instead of plain text."
    )
    p_trace_verify.set_defaults(func=cmd_trace_verify_chain)

    p_trace_export = trace_sub.add_parser(
        "export",
        help="Export a SQLite trace store to a JSONL file.",
    )
    p_trace_export.add_argument("store_path", help="Path to a SQLite trace store file.")
    p_trace_export.add_argument(
        "out_path", help="Path to the JSONL output file (will be overwritten)."
    )
    p_trace_export.add_argument(
        "--session-id",
        default=None,
        help="Optional session id filter. Default: export every record.",
    )
    p_trace_export.set_defaults(func=cmd_trace_export)

    # ----- demo --------------------------------------------------------
    p_demo = sub.add_parser("demo", help="Run a bundled demo.")
    p_demo.add_argument("demo_name", choices=["procurement"], help="Demo name.")
    p_demo.set_defaults(func=cmd_demo)

    return parser


def _version_string() -> str:
    try:
        from sarc_governance import __version__  # local import to avoid circulars
    except Exception:  # pragma: no cover
        __version__ = "unknown"
    return f"sarc-governance {__version__}"


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
