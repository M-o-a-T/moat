"""
Code for "python3 -mmoat" when running in the MoaT source tree.
"""
from moat.main import cmd
import sys
import trio

ec = 0

def _leaves(exc):
    if isinstance(exc, BaseExceptionGroup):
        for e in exc.exceptions:
            yield from _leaves(e)
    else:
        yield exc

try:
    cmd()
except* SystemExit as ex:
    for e in _leaves(ex):
        ec |= e.code

sys.exit(ec)
