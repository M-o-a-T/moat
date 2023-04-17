"""
This module contains a heap of somewhat-random helper functions
and classes which are used throughout MoaT (and beyond)
but don't get their own package because they're too small,
or too interrelated … or the author was too lazy.
"""
# TODO split this up

# pylint: disable=cyclic-import,wrong-import-position

import logging as _logging

_log = _logging.getLogger(__name__)

from .alert import *  # noqa: F401,F403,E402  # isort:skip
from .impl import *  # noqa: F401,F403,E402  # isort:skip
from .dict import *  # noqa: F401,F403,E402  # isort:skip
from .merge import *  # noqa: F401,F403,E402  # isort:skip
from .proxy import *  # noqa: F401,F403,E402  # isort:skip

try:
    from .event import *  # noqa: F401,F403
except ImportError as exc:
    _log.warning("Missing: %s", exc)

try:
    from .ctx import *  # noqa: F401,F403
except ImportError as exc:
    _log.warning("Missing: %s", exc)

try:
    from .queue import *  # noqa: F401,F403
except ImportError as exc:
    _log.warning("Missing: %s", exc)

try:
    from .msgpack import *  # noqa: F401,F403
except ImportError as exc:
    _log.warning("Missing: %s", exc)

try:
    from .module import *  # noqa: F401,F403
except ImportError as exc:
    _log.warning("Missing: %s", exc)

try:
    from .msg import *  # noqa: F401,F403
except ImportError as exc:
    _log.warning("Missing: %s", exc)

try:
    from .path import *  # noqa: F401,F403
except ImportError as exc:
    _log.warning("Missing: %s", exc)

try:
    from .server import *  # noqa: F401,F403
except ImportError as exc:
    _log.warning("Missing: %s", exc)

try:
    from .spawn import *  # noqa: F401,F403
except ImportError as exc:
    _log.warning("Missing: %s", exc)

try:
    from .systemd import *  # noqa: F401,F403
except ImportError as exc:
    _log.warning("Missing: %s", exc)

try:
    from .yaml import *  # noqa: F401,F403
except ImportError as exc:
    _log.warning("Missing: %s", exc)

try:
    from .main import *  # noqa: F401,F403
except ImportError as exc:
    _log.warning("Missing: %s", exc)
