"""
Basic MoaT command multiplexer, sans-IO implementation
"""
from __future__ import annotations

from ._cmd import *

try:
	from concurrent.futures import CancelledError
except ImportError:
	class CancelledError(Exception):
		"Basic remote cancellation"
		pass

