"""
This module contains a heap of somewhat-random helper functions
and classes which are used throughout MoaT (and beyond)
but don't get their own package because they're too small,
or too interrelated … or the author was too lazy.
"""
# TODO split this up

# pylint: disable=cyclic-import,wrong-import-position
from __future__ import annotations

import logging as _logging

_log = _logging.getLogger(__name__)

from .dict import attrdict  # noqa: E402, F401

from .alert import *  # noqa: F403, E402  # isort:skip
from .impl import *  # noqa: F403, E402  # isort:skip
from .dict import *  # noqa: F403, E402  # isort:skip
from .merge import *  # noqa: F403, E402  # isort:skip
from .misc import *  # noqa: F403, E402  # isort:skip

from moat.lib.codec.proxy import *  # noqa: F403, E402  # isort:skip

try:
    from .event import *  # noqa: F403
except ImportError as exc:
    _log.warning("Missing: %s (importing .event)", exc)

try:
    from .ctx import *  # noqa: F403
except ImportError as exc:
    _log.warning("Missing: %s (importing .ctx)", exc)

try:
    from .queue import *  # noqa: F403
except ImportError as exc:
    _log.warning("Missing: %s (importing .queue)", exc)

try:
    from .module import *  # noqa: F403
except ImportError as exc:
    _log.warning("Missing: %s (importing .module)", exc)

try:
    from .msg import *  # noqa: F403
except ImportError as exc:
    _log.warning("Missing: %s (importing .msg)", exc)

try:
    from .msgpack import *  # noqa: F403
except ImportError as exc:
    _log.warning("Missing: %s (importing .msgpack)", exc)

try:
    from .path import *  # noqa: F403
except ImportError as exc:
    _log.warning("Missing: %s (importing .path)", exc)

try:
    from .server import *  # noqa: F403
except ImportError as exc:
    _log.warning("Missing: %s (importing .server)", exc)

try:
    from .spawn import *  # noqa: F403
except ImportError as exc:
    _log.warning("Missing: %s (importing .spawn)", exc)

try:
    from .systemd import *  # noqa: F403
except ImportError as exc:
    _log.warning("Missing: %s (importing .systemd)", exc)

try:
    from .yaml import *  # noqa: F403
except ImportError as exc:
    _log.warning("Missing: %s (importing .yaml)", exc)

try:
    from .exc import *  # noqa: F403
except ImportError as exc:
    _log.warning("Missing: %s (importing .exc)", exc)

from .main import *  # noqa: F403, E402
