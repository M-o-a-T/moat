"""
App and command base classes
"""

from __future__ import annotations

from moat.micro.cmd.base import BaseCmd


class ConfigError(RuntimeError):
    "generic config error exception"

    # pylint:disable=unnecessary-pass


class BaseAppCmd(BaseCmd):
    "App-specific command"


#   def __init__(self, name, cfg, gcfg):
#       super().__init__(cfg)
#       self.name = name
#       self.gcfg = gcfg
