"""
This module contains all MoaT-Link exceptions.

Currently this is (mostly) a re-import of moat.kv.exceptions.
"""

from __future__ import annotations

from moat.kv.exceptions import *

MoaTLinkError = MoaTKVError

class AuthError(MoaTLinkError):  # noqa: D101, D102
    pass

