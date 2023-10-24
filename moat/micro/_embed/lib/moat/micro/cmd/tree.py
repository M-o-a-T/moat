"""
Satellite side of cmd.tree
"""
from __future__ import annotations

from ._tree import *
from ._tree import Dispatch as _Dispatch


class Dispatch(_Dispatch):
    APP = "app"
