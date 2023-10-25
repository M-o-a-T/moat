"""
Satellite side of cmd.tree
"""
from __future__ import annotations

from ._tree import (  # noqa:F401 pylint:disable=unused-import
    BaseFwdCmd,
    BaseLayerCmd,
    BaseListenCmd,
    BaseListenOneCmd,
    BaseSubCmd,
    BaseSuperCmd,
    DirCmd,
    SubDispatch,
)
from ._tree import Dispatch as _Dispatch


class Dispatch(_Dispatch):  # noqa:D101
    APP = "app"
