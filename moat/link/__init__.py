"""
Moat-Link is a library that enhances MQTT messaging (other backends are
possible) with structured data types, defined metadata (message source
and timestamp), and

The point of this library is to support a minimal unified pub/sub messaging
service.

Configuration looks like this:

    link:
      backend:
        driver: mqtt
        host: localhost
        port: 51883
        codec: std-cbor
      root: moat.org.example.test

"""

from __future__ import annotations

try:
    from importlib.metadata import version

    _version = version("moat.link")
    _version_tuple = tuple(int(x) for x in _version.split("."))

except Exception:  # pragma: no cover
    _version = "0.0.1"
    _version_tuple = (0, 0, 1)

protocol_version_min = 0
protocol_version = 0

__path__ = __import__("pkgutil").extend_path(__path__, __name__)
