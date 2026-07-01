from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_wrf_doc_freshness_check_passes() -> None:
    script = ROOT / "scripts" / "check_wrf_doc_freshness.py"
    spec = importlib.util.spec_from_file_location("check_wrf_doc_freshness", script)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    assert module.main() == 0
