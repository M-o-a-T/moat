"""
Legacy controller vs. simulator: reference traces (see data/legacy/README.md).

Run with ``--heat-refresh`` to rewrite the stored traces.
"""

from __future__ import annotations

import pytest

from .legacy import SCENARIOS, load_solvis, run_scenario, trace_file


def test_no_kv_client():
    "The legacy module cannot open a real MoaT-KV connection."
    solvis = load_solvis()
    with pytest.raises(RuntimeError):
        solvis.open_client()


@pytest.mark.parametrize("name", list(SCENARIOS))
def test_trace(name: str, trace_check) -> None:
    "The legacy controller still behaves as recorded."
    trace_check(run_scenario(SCENARIOS[name]), trace_file(name))
