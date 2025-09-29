"""
exec
"""

from __future__ import annotations

import pytest
import subprocess

from moat.util.exec import run


@pytest.mark.anyio
async def test_basic():
    """
    Duh
    """
    assert await run("echo", "Foo", capture=True) == "Foo\n"
    with pytest.raises(subprocess.CalledProcessError) as err:
        await run("/bin/sh", "-c", "exit 1")
    assert err.value.returncode == 1
    await run(
        "/bin/sh", "-c", "echo foo; sleep 1; echo bar >/dev/stderr; sleep 1; echo baz", echo=True
    )
    fb = await run(
        "/bin/sh",
        "-c",
        "echo -n foo; sleep 1; echo bar >/dev/stderr; sleep 1; echo -n baz",
        echo=True,
        capture=True,
    )
    assert fb == "foobaz"
    ct = await run("/bin/cat", capture=True, input="whatever")
    assert ct == "whatever"
