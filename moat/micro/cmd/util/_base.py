"""
Helpers for MoaT command interpreters et al.
"""

from __future__ import annotations

from moat.lib.micro import log


async def run_no_exc(p, msg, x_err=()):
    """Call p(msg) but log exceptions"""
    try:
        r = p(**msg)
        if hasattr(r, "throw"):  # coroutine
            r = await r
    except x_err as err:
        log("Error in %r %r: %r", p, msg, err)
    except Exception as err:  # pylint:disable=broad-exception-caught
        log("Error in %r %r", p, msg, err=err)
