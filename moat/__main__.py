"""
Code for "python3 -mmoat" when running in the MoaT source tree.
"""

from __future__ import annotations

import sys

from moat.main import cmd

ec = cmd()
sys.exit(ec)
