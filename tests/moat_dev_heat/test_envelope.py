"""
Tests for the pump-envelope job (examples/moat-dev-heat).
"""

from __future__ import annotations

import pytest
from pathlib import Path as FSPath

import moat.link.job  # noqa:F401 - register cfg
from moat.util import yload
from moat.link._test import Scaffold
from moat.link.code.io import path_from_file, split_snippet, write_snippet
from moat.link.code.testrun import run_test

pytestmark = pytest.mark.anyio

CODE = FSPath(__file__).parents[2] / "examples" / "moat-dev-heat" / "transform.envelope.yaml"


def _cases():
    with CODE.open() as f:
        _rec, tests = split_snippet(yload(f))
    for case in tests:
        yield pytest.param(case, id=f"envelope:{case}")


@pytest.mark.parametrize("case", list(_cases()))
async def test_envelope(cfg, case):
    "Load the snippet into a test server and run one of its test cases."
    with CODE.open() as f:
        data = yload(f)
    path = path_from_file(CODE.name)
    _rec, tests = split_snippet(data)

    async with (
        Scaffold(cfg, use_servers=True) as sf,
        sf.server_(init={"Hello": "there!"}),
        sf.client_() as c,
    ):
        await write_snippet(c, path, data)
        await c.i_sync()
        out = await run_test(c, path, tests[case])
        assert out.ok, "\n".join(out.log)
