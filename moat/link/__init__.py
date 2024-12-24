"""
Moat-Link is a moderately shallow library that distributes basic
topic-based messaging between several connections or encodings.

The point of this library is to support a minimal unified pub/sub messaging
service.

Configuration looks like this:

    link:
      dist:
        hass:
          prefix: !P hass
          backend: mqtt
          path: !P some.special.hass
          chop: 1
          codec: home_assistant

        root:
          prefix: !P dist.root
          backend: mqtt
          codec: cbor

        special:
          prefix: !P :
          backend: mqtt
          path: !P some.special.area
          chop: 0
          codec: cbor

        storage:
          prefix: !P :
          chop: 0
          backend: kv
          codec: null
          retained: true

      backend:
        mqtt:
          uri: mqtt://localhost:51883

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
