import sys
sys.path.insert(0,"lib/serialpacker")

import pytest
import anyio
import moat.compat

#@pytest.fixture
#async def main_tg():
#    async with anyio.create_task_group() as tg:
#        moat.compat._tg = tg
#        yield tg
