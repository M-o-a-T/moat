"""
This module contains a mapping that's heap-sorted by value.
"""

from __future__ import annotations

from ._impl import PrioMap as PrioMap
from ._impl import TimerMap as TimerMap

__all__ = ["PrioMap", "TimerMap"]
