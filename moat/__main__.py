"""
Code for "python3 -mmoat" when running in the MoaT source tree.
"""

from moat.main import cmd
import sys

ec = cmd()
sys.exit(ec)
