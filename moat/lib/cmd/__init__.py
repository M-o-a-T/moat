"""
Basic MoaT command multiplexer, sans-IO implementation
"""

from __future__ import annotations

from ._cmd import *  # noqa: F403

try:
    from concurrent.futures import CancelledError
except ImportError:  # nocover

    class CancelledError(Exception):
        "Basic remote cancellation"

        pass
