from __future__ import annotations

from ._base import BaseBMS


class Cmd(BaseBMS):
    async def loc_state(self):
        return {"Foo": 123}

    pass
