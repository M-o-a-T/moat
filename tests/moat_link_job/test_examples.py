"""
Run the test cases of the example snippets in ``examples/moat-link-job/``.

Each file holds one snippet and its test cases, in the format of
``moat link code PATH get -r``; the file's name is the snippet's path.
Every test case is a separate pytest item.
"""

from __future__ import annotations

import pytest
from pathlib import Path as FSPath

import moat.link.job  # noqa:F401 - register cfg
from moat.util import yload, yprint
from moat.link._test import Scaffold
from moat.link.code.io import path_from_file, split_snippet, write_snippet
from moat.link.code.testrun import run_test

pytestmark = pytest.mark.anyio

EXAMPLES = FSPath(__file__).parents[2] / "examples" / "moat-link-job"

XFAIL = {
    "timer.auto_off:same": "moat-5m1s: the test's monitor and the snippet watch the same path",
}
"Test cases that are known to fail, with the reason."


def _cases():
    for fn in sorted(EXAMPLES.glob("*.yaml")):
        with fn.open() as f:
            data = yload(f)
        _rec, tests = split_snippet(data)
        for case in tests:
            name = f"{fn.stem}:{case}"
            marks = ()
            if name in XFAIL:
                marks = (pytest.mark.xfail(reason=XFAIL[name], strict=True),)
            yield pytest.param(fn, case, id=name, marks=marks)


@pytest.mark.parametrize(("fn", "case"), list(_cases()))
async def test_example(cfg, fn, case):
    "Load the snippet into a test server and run one of its test cases."
    with fn.open() as f:
        data = yload(f)
    path = path_from_file(fn.name)
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


async def test_import_get(cfg):
    "``moat link code : import FILE…`` stores the examples, ``get -r`` reads them back."
    files = sorted(EXAMPLES.glob("*.yaml"))
    async with (
        Scaffold(cfg, use_servers=True) as sf,
        sf.server_(init={"Hello": "there!"}),
        sf.client_() as c,
    ):
        await sf.run(["link", "code", ":", "import", *(str(fn) for fn in files)])
        await c.i_sync()
        for fn in files:
            with fn.open() as f:
                data = yload(f)
            path = path_from_file(fn.name)
            got = yload((await sf.run(f"link code {path} get -r")).stdout)
            rec, tests = split_snippet(data)
            grec, gtests = split_snippet(got)
            assert grec == rec
            assert {k: v.dump() for k, v in gtests.items()} == {
                k: v.dump() for k, v in tests.items()
            }

        # Importing again replaces the test cases.
        fn = files[0]
        with fn.open() as f:
            data = yload(f)
        path = path_from_file(fn.name)
        data["tests"] = dict(list(data["tests"].items())[:1])
        dst = FSPath(sf.tempdir) / fn.name
        with dst.open("w") as f:
            yprint(data, stream=f)
        await sf.run(["link", "code", str(path), "import", str(dst)])
        await c.i_sync()
        got = yload((await sf.run(f"link code {path} get -r")).stdout)
        assert list(got["tests"]) == list(data["tests"])
