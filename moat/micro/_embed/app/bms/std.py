from ._base import BaseBMSCmd

class Cmd(BaseBMSCmd):
    async def loc_state(self):
        return {"Foo":123}
    pass
