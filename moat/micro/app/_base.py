"""
App and command base classes
"""

from __future__ import annotations


class ConfigError(RuntimeError):
    "generic config error exception"

    # pylint:disable=unnecessary-pass
