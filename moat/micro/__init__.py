# noqa:D104 pylint:disable=missing-module-docstring
from __future__ import annotations

__path__ = __import__("pkgutil").extend_path(__path__, __name__)
from moat.lib.config import CfgStore as _CfgStore

_CfgStore.with_(__name__)
