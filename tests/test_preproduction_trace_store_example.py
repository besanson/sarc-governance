"""Smoke test for examples/preproduction_trace_store/run_demo.py."""

from __future__ import annotations

import asyncio
import importlib.util
import io
import pathlib
import sys
from contextlib import redirect_stdout


REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
DEMO_PATH = REPO_ROOT / "examples" / "preproduction_trace_store" / "run_demo.py"


def test_preproduction_demo_runs_cleanly():
    spec = importlib.util.spec_from_file_location("_preproduction_demo", DEMO_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)  # type: ignore[union-attr]

    out = io.StringIO()
    with redirect_stdout(out):
        asyncio.run(module.main())
    text = out.getvalue()

    assert "hash chain: OK" in text
    assert "exported hash chain: OK" in text
    assert "blocked: ConstraintViolation" in text
    assert "diff: +0  -0  ~1" in text
