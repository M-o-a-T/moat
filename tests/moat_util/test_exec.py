"""
exec
"""

from __future__ import annotations

import pytest
import subprocess

from moat.util.exec import DetailedCalledProcessError, run


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


@pytest.mark.anyio
async def test_failure_str_handles_path_arg(tmp_path):
    """Rendering a failed command must not choke on non-string (``Path``) args.

    Regression: ``shlex.quote`` raised ``TypeError`` on ``Path`` elements of
    ``self.cmd``, so ``str(DetailedCalledProcessError)`` crashed instead of
    reporting the actual failure.
    """
    with pytest.raises(DetailedCalledProcessError) as err:
        await run("/bin/sh", "-c", "exit 1", tmp_path)
    msg = str(err.value)
    assert "exit status 1" in msg
    assert str(tmp_path) in msg
    # The Path must survive rendering as a quoted/plain token, not raise.
    assert "Path" not in msg
