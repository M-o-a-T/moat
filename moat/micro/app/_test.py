from moat.micro.cmd.base import BaseCmd

class Cmd(BaseCmd):
    async def cmd_echo(self, m):
        return {'r':m}
