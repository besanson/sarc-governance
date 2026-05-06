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
from sarc_governance.constraints import ConstraintSpec
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
