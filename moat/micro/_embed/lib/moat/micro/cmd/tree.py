"""
Satellite side of cmd.tree
"""

from moat.util import NotGiven, attrdict

from ._tree import Dispatch as _Dispatch
from ._tree import *


class Dispatch(_Dispatch):
    APP = "app"
