"""
This module calculates optimal battery charge/discharge based on usage and
pricing prediction.

"""

from __future__ import annotations

from moat.lib.config import register as _register

from .control import Model  # noqa:F401

__all__ = []

_register(__name__)
