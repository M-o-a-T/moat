"""
This module calculates optimal battery charge/discharge based on usage and
pricing prediction.

"""

from __future__ import annotations

from moat.util.config import CfgStore

from .control import Model  # noqa:F401

CfgStore.with_(__name__)
