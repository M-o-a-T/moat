# noqa:D104 pylint:disable=missing-module-docstring
from __future__ import annotations

__path__ = __import__("pkgutil").extend_path(__path__, __name__)
from moat.lib.config import register as _register
from moat.lib.rpc import add_app_prefix

_register(__name__)
add_app_prefix("moat.micro.app")
