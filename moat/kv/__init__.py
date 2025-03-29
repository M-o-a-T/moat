# pylint: disable=W0703,C0103
from __future__ import annotations
import contextlib

__path__ = __import__("pkgutil").extend_path(__path__, __name__)

try:
    from importlib.metadata import version

    _version = version("moat.kv")
    _version_tuple = tuple(int(x) for x in _version.split("."))

except Exception:  # pragma: no cover
    _version = "0.0.1"
    _version_tuple = (0, 0, 1)

with contextlib.suppress(NameError):
    del version
