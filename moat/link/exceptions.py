"""
This module contains all MoaT-Link exceptions.

Currently this is (mostly) a re-import of moat.kv.exceptions.
"""

from __future__ import annotations

from moat.kv.exceptions import ClientCancelledError as ClientCancelledError
from moat.kv.exceptions import ClientError as ClientError
from moat.kv.exceptions import MoaTKVError

MoaTLinkError = MoaTKVError


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
