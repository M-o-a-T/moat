"""
The base of MoaT-Link's server part.
"""

from __future__ import annotations

__path__ = __import__("pkgutil").extend_path(__path__, __name__)

try:
    from importlib.metadata import version

    _version = version("moat.link.server")
    _version_tuple = tuple(int(x) for x in _version.split("."))

except Exception:  # pragma: no cover
    _version = "0.0.1"
    _version_tuple = (0, 0, 1)

from ._server import Server as Server
