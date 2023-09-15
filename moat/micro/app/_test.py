from moat.micro.cmd import BaseCmd

class Cmd(BaseCmd):
    async def cmd_echo(self, m):
        return {'r':m}
