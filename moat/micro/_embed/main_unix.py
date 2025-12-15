"""
This code is used by MicroPython to set up the test dispatcher.

TODO: replace this with the standard "main.py".
"""

from __future__ import annotations

import sys

sys.path.insert(0, "./stdlib")
sys.path.insert(0, ".")

import moat

moat.go(cmd=False)
