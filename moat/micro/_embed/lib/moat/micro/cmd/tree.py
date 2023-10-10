"""
Satellite side of cmd.tree
"""

from moat.util import attrdict, NotGiven

from ._tree import Dispatch as _Dispatch
from ._tree import SubDispatch

class Dispatch(_Dispatch):
    APP = "app"

