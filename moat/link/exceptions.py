"""
This module contains all MoaT-Link exceptions.

Currently this is (mostly) a re-import of moat.kv.exceptions.
"""

from __future__ import annotations

from moat.lib.codec.proxy import as_proxy


class MoaTLinkError(RuntimeError):
    """Superclass of all MoaT-KV errors.

    Abstract class.
    """

    pass


@as_proxy("_EMLCl")
class ClientError(MoaTLinkError):  # noqa: D101
    pass


@as_proxy("_EMLClC")
class ClientCancelledError(ClientError):  # noqa: D101
    pass


@as_proxy("_EMLClA")
class AuthError(MoaTLinkError):  # noqa: D101
    pass


@as_proxy("_EMLClDt")
class OutOfDateError(MoaTLinkError):  # noqa: D101
    pass


@as_proxy("_EMLClSup")
class ServiceSupplanted(MoaTLinkError):  # noqa: D101
    pass


@as_proxy("_EMLClClr")
class ServiceCleared(MoaTLinkError):  # noqa: D101
    pass


@as_proxy("_EMLClSnF")
class ServiceNotFound(MoaTLinkError):  # noqa: D101
    pass


@as_proxy("_EMLClSnS")
class ServiceNotStarted(UserWarning):  # noqa: D101
    pass
