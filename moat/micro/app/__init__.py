from moat.micro.cmd import BaseCmd

class ConfigError(RuntimeError):
    pass

class BaseApp:
    def __init__(self, name, cfg, gcfg):
        self.cfg = cfg
        self.gcfg = gcfg
        self.name = name

    async def config_updated(self, cfg):
        pass

class BaseAppCmd(BaseCmd):
    def __init__(self, parent, name, cfg, gcfg):
        super().__init__(parent)
        self.name = name
        self.cfg = cfg
        self.gcfg = gcfg

