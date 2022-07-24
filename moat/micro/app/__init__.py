class BaseApp:
    def __init__(self, name, cfg, gcfg):
        self.cfg = cfg
        self.gcfg = gcfg
        self.name = name

    async def config_updated(self):
        pass
