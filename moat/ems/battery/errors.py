from __future__ import annotations
from moat.util import as_proxy


@as_proxy("err_eb_NSC")
class NoSuchCell(RuntimeError):
    pass


@as_proxy("err_eb_ME")
class MessageError(RuntimeError):
    pass


@as_proxy("err_eb_ML")
class MessageLost(RuntimeError):
    pass
