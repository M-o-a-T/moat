class _Remote:
    """
    Delegates requests to the other side
    """

    def __init__(self, cmd, cfg, **kw):
        self.req = cmd.request
       
        self.cmd = cfg.cmd
        if isinstance(self.cmd,str):
            self.cmd = self.cmd.split(".")
        self.args = cfg.args if "args" in cfg else {}
        self.attr = cfg.attr if "attr" in cfg else []
    
    async def read(self):
        res = await self.req.send(self.cmd, **self.args)
        for a in self.attr:
            try:
                res = getattr(res,a)
            except AttributeError:
                res = res[a]
        return res
        

