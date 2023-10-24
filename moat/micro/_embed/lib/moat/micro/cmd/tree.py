"""
Satellite side of cmd.tree
"""


from ._tree import Dispatch as _Dispatch
from ._tree import *


class Dispatch(_Dispatch):
    APP = "app"
