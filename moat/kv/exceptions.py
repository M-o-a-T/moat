"""
This module affords all MoaT-KV exceptions.
"""

# pylint: disable=unnecessary-pass
from __future__ import annotations

error_types = {}


def _typed(cls):
    error_types[cls.etype] = cls
    return cls


class MoaTKVError(RuntimeError):
    """Superclass of all MoaT-KV errors.

    Abstract class.
    """

    pass


class ServerError(MoaTKVError):
    """Generic server error.

    This class includes errors forwarded to the client.
    """

    pass


class ClientError(MoaTKVError):
    """Generic client error.

    Abstract class.
    """

    etype: str = None


@_typed
class ClientChainError(ClientError):
    """The chain you passed in didn't match the entry"""

    etype = "chain"


@_typed
class ClientConnectionError(ClientError):
    """Some connection error"""

    etype = "conn"


class ServerClosedError(ServerError):
    """The server closed our connection."""

    pass


class ServerConnectionError(ServerError):
    """Some connection error"""

    pass


class ACLError(ServerError):
    """An ACL did not match"""

    pass


class ClientCancelledError(ClientError):
    """A client call was cancelled."""

    pass


class ClientAuthError(ClientError):
    """Authorization failed.

    Abstract class.
    """

    pass


class ClientAuthRequiredError(ClientAuthError):
    """Authorization required but missing."""

    pass


class ClientAuthMethodError(ClientAuthError):
    """Wrong authorization method provided."""

    pass


class MoaTKVauthError(ClientError):
    """Auth error.

    Abstract class.
    """

    pass


class NoAuthError(MoaTKVauthError):
    """Server-side error: auth required"""

    pass


class NoAuthModuleError(MoaTKVauthError):
    """Server-side error: auth module doesn't exist"""

    pass


class AuthFailedError(MoaTKVauthError):
    """Server-side error: auth failed"""

    pass
