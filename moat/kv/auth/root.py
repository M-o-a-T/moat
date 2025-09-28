#
"""
Null auth method.

Does not limit anything, allows everything.
"""

from __future__ import annotations

from . import (
    BaseClientAuth,
    BaseClientAuthMaker,
    BaseServerAuthMaker,
    RootServerUser,
    null_client_login,
    null_server_login,
)


def load(typ: str, *, make: bool = False, server: bool):  # noqa:D103
    if typ == "client":
        if server:
            return null_server_login
        else:
            return null_client_login
    if typ != "user":
        raise NotImplementedError("This module only handles users")
    if server:
        if make:
            return ServerUserMaker
        else:
            return ServerUser
    else:
        if make:
            return ClientUserMaker
        else:
            return ClientUser


class ServerUserMaker(BaseServerAuthMaker):  # noqa:D101
    schema = {"type": "object", "additionalProperties": False}


class ServerUser(RootServerUser):  # noqa:D101
    schema = {"type": "object", "additionalProperties": False}


class ClientUserMaker(BaseClientAuthMaker):  # noqa:D101
    gen_schema = {"type": "object", "additionalProperties": False}
    mod_schema = {"type": "object", "additionalProperties": False}

    @property
    def ident(self):  # noqa:D102
        return "*"


class ClientUser(BaseClientAuth):  # noqa:D101
    schema = {"type": "object", "additionalProperties": False}
