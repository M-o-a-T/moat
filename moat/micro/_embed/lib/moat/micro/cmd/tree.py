"""
Satellite side of cmd.tree
"""

from moat.util import attrdict, NotGiven

from ._tree import *
from ._tree import Dispatch as _Dispatch

class Dispatch(_Dispatch):
    APP = "app"

