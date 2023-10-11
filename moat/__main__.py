"""
Code for "python3 -mmoat" when running in the MoaT source tree.
"""
from moat.main import cmd
from moat.util import exc_iter
import sys
import trio

ec = 0

try:
    cmd()
except* SystemExit as ex:
    for e in exc_iter(ex):
        ec |= e.code

sys.exit(ec)
