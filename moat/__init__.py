# noqa: D104
from __future__ import annotations

__path__ = __import__("pkgutil").extend_path(__path__, __name__)

import sys

from moat.lib.config import register as _register

_register(__name__)

DOC = "sphinx" in sys.modules

__all__ = []
