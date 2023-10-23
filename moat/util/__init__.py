"""
This module contains a heap of somewhat-random helper functions
and classes which are used throughout MoaT (and beyond)
but don't get their own package because they're too small,
or too interrelated … or the author was too lazy.
"""
# TODO split this up

# pylint: disable=cyclic-import,wrong-import-position

import logging as _logging

import msgpack as _mp

_log = _logging.getLogger(__name__)


def packer(*a, cbor=False, **k):
    """single message packer"""
    if cbor:
        return _cbor.packb(*a, **k)
    # pylint:disable=protected-access
    return _mp.packb(*a, strict_types=False, use_bin_type=True, default=_msgpack._encode, **k)


def unpacker(*a, cbor=False, **k):
    """single message unpacker"""
    if cbor:
        return _cbor.unpackb(*a, **k)
    return _mp.unpackb(
        *a,
        object_pairs_hook=attrdict,
        strict_map_key=False,
        raw=False,
        use_list=False,
        ext_hook=_msgpack._decode,  # pylint:disable=protected-access
        **k,
    )


def stream_unpacker(*a, cbor=False, **k):
    """stream unpacker factory"""
    if cbor:
        return _cbor.Unpacker(*a, **k)
    return _mp.Unpacker(
        *a,
        object_pairs_hook=attrdict,
        strict_map_key=False,
        raw=False,
        use_list=False,
        ext_hook=_msgpack._decode,  # pylint:disable=protected-access
        **k,
    )


from .dict import attrdict

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
    from .exc import *  # noqa: F401,F403
except ImportError as exc:
    _log.warning("Missing: %s", exc)

try:
    from .main import *  # noqa: F401,F403
except ImportError as exc:
    _log.warning("Missing: %s", exc)

from . import cbor as _cbor
from . import msgpack as _msgpack  # pylint:disable=reimported  # nonsense
