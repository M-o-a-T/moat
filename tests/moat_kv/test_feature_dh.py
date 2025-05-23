from __future__ import annotations
import logging

import pytest

from moat.kv.mock.mqtt import stdtest

logger = logging.getLogger(__name__)


@pytest.mark.trio()
async def test_51_dh(autojump_clock):  # pylint: disable=unused-argument
    async with stdtest(args={"init": 123}) as st:
        assert st is not None
        (s,) = st.s
        async with st.client() as c:
            assert len(s._clients) == 1
            sc = next(iter(s._clients))
            assert c._dh_key is None
            assert sc._dh_key is None
            dh = await c.dh_secret(length=10)
            assert dh == c._dh_key
            assert dh == sc._dh_key
