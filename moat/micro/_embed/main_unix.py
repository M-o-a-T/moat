"""
This code is used by MicroPython to set up the test dispatcher.

TODO: replace this with the standard "main.py".
"""

from __future__ import annotations

import sys

mode = sys.argv[1] if len(sys.argv) > 1 else "once"


sys.path.insert(0, "./stdlib")
sys.path.insert(0, ".")

import moat  # noqa:E402

moat.go(mode, cmd=False)
