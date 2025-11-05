"""
This module contains all MoaT-Link exceptions.

Currently this is (mostly) a re-import of moat.kv.exceptions.
"""

from __future__ import annotations


class MoaTLinkError(RuntimeError):
    """Superclass of all MoaT-KV errors.

    Abstract class.
    """

    pass


class ClientError(MoaTLinkError):  # noqa: D101
    pass


class ClientCancelledError(ClientError):  # noqa: D101
    pass


class AuthError(MoaTLinkError):  # noqa: D101
    pass


class OutOfDateError(MoaTLinkError):  # noqa: D101
    pass


class ServiceSupplanted(MoaTLinkError):  # noqa: D101
    pass


class ServiceNotFound(MoaTLinkError):  # noqa: D101
    pass


class ServiceNotStarted(UserWarning):  # noqa: D101
    pass
