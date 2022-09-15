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

from ._impl import *  # noqa: F401,F403,E402  # isort:skip
from ._dict import *  # noqa: F401,F403,E402  # isort:skip
from ._merge import *  # noqa: F401,F403,E402  # isort:skip

try:
    from ._event import *  # noqa: F401,F403
except ImportError as exc:
    _log.warning("Missing: %s", exc)

try:
    from ._ctx import *  # noqa: F401,F403
except ImportError as exc:
    _log.warning("Missing: %s", exc)

try:
    from ._queue import *  # noqa: F401,F403
except ImportError as exc:
    _log.warning("Missing: %s", exc)

try:
    from ._msgpack import *  # noqa: F401,F403
except ImportError as exc:
    _log.warning("Missing: %s", exc)

try:
    from ._module import *  # noqa: F401,F403
except ImportError as exc:
    _log.warning("Missing: %s", exc)

try:
    from ._msg import *  # noqa: F401,F403
except ImportError as exc:
    _log.warning("Missing: %s", exc)

try:
    from ._path import *  # noqa: F401,F403
except ImportError as exc:
    _log.warning("Missing: %s", exc)

try:
    from ._server import *  # noqa: F401,F403
except ImportError as exc:
    _log.warning("Missing: %s", exc)

try:
    from ._spawn import *  # noqa: F401,F403
except ImportError as exc:
    _log.warning("Missing: %s", exc)

try:
    from ._systemd import *  # noqa: F401,F403
except ImportError as exc:
    _log.warning("Missing: %s", exc)

try:
    from ._yaml import *  # noqa: F401,F403
except ImportError as exc:
    _log.warning("Missing: %s", exc)

try:
    from ._main import *  # noqa: F401,F403
except ImportError as exc:
    _log.warning("Missing: %s", exc)
