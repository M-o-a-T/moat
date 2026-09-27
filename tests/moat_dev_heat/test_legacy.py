"""
Legacy controller vs. simulator: reference traces (see data/legacy/README.md).

Set ``MOAT_HEAT_REFRESH=1`` to rewrite the stored traces instead of
comparing against them.
"""

from __future__ import annotations

import os
import pytest

from .legacy import SCENARIOS, dump, load, load_solvis, run_scenario, trace_file

REFRESH = bool(os.environ.get("MOAT_HEAT_REFRESH"))


def test_no_kv_client():
    "The legacy module cannot open a real MoaT-KV connection."
    solvis = load_solvis()
    with pytest.raises(RuntimeError):
        solvis.open_client()


def _same(a: object, b: object) -> bool:
    if isinstance(a, float) or isinstance(b, float):
        return isinstance(a, (int, float)) and isinstance(b, (int, float)) and abs(a - b) < 0.002
    return a == b


@pytest.mark.parametrize("name", list(SCENARIOS))
def test_trace(name: str) -> None:
    "The legacy controller still behaves as recorded."
    tr = run_scenario(SCENARIOS[name])
    f = trace_file(name)
    if REFRESH or not f.exists():
        f.write_text(dump(tr))
        pytest.skip("trace written")
    ref = load(f.read_text())
    tr = load(dump(tr))  # same rounding and types as the stored file

    assert tr["events"] == ref["events"]
    assert len(tr["samples"]) == len(ref["samples"])
    for s, r in zip(tr["samples"], ref["samples"], strict=True):
        bad = {
            k: (s.get(k), r.get(k)) for k in s.keys() | r.keys() if not _same(s.get(k), r.get(k))
        }
        assert not bad, f"t={s['t']}: {bad}"
