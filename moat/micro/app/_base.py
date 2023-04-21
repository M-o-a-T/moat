"""
App and command base classes
"""
from moat.micro.cmd import BaseCmd


class ConfigError(RuntimeError):
    "generic config error exception"
    pass  # pylint:disable=unnecessary-pass


class BaseApp:
    "App"

    def __init__(self, name, cfg, gcfg):
        self.cfg = cfg
        self.gcfg = gcfg
        self.name = name

    async def config_updated(self, cfg):
        "called when the config gets updated"
        pass  # pylint:disable=unnecessary-pass


class BaseAppCmd(BaseCmd):
    "App-specific command"

    def __init__(self, parent, name, cfg, gcfg):
        super().__init__(parent)
        self.name = name
        self.cfg = cfg
        self.gcfg = gcfg
