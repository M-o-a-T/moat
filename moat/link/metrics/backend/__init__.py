"""
Common code for metrics backends.

Currently the only backend supported is Akumuli, but who knows.
"""

from __future__ import annotations

from ._base import Backend as Backend
from ._base import get_backend as get_backend

__all__ = ["Backend", "get_backend"]
