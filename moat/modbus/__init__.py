"""
This module implements opinionated async Modbus client and servers.

Both work by registering Value objects which can be iterated, yielding
value changes.

Clients values are (optionally) split into multiple blocks, in order to
implement variable-times periodic requests with aggregate requests that
don't fetch unnecessary data. Client requests are executed in parallel
(configurable, some broken Modbus servers don't like that).

Also included is a configurable Modbus forwarder.

Modbus-TCP and Modbus-RTU (serial) are supported.
"""

from __future__ import annotations

from .client import *  # noqa: 403
from .server import *  # noqa: 403

__path__ = __import__("pkgutil").extend_path(__path__, __name__)  # noqa:F405
