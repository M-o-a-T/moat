"""
Server side of BaseCmd
"""

from ._tree import Dispatch as _Dispatch

class Dispatch(_Dispatch):
    APP = "moat.micro.app"

class SubDispatch:
    """
    A Dispatch forwarder that prefixes a path
    """
    def __init__(self, dispatch, path):
        self.disp = dispatch
        self.path = path

    async def send(self, *a, **k):
        return await self.disp.dispatch(self.path+a, k)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *tb):
        pass
