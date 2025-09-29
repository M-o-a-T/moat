from __future__ import annotations  # noqa: D100

import logging
import pytest

from moat.kv.mock.mqtt import stdtest

logger = logging.getLogger(__name__)


@pytest.mark.trio
async def test_51_dh(autojump_clock):  # pylint: disable=unused-argument  # noqa: ARG001, D103
    async with stdtest(args={"init": 123}) as st:
        assert st is not None
        (s,) = st.s
        async with st.client() as c:
            assert len(s._clients) == 1  # noqa: SLF001
            sc = next(iter(s._clients))  # noqa: SLF001
            assert c._dh_key is None  # noqa: SLF001
            assert sc._dh_key is None  # noqa: SLF001
            dh = await c.dh_secret(length=10)
            assert dh == c._dh_key  # noqa: SLF001
            assert dh == sc._dh_key  # noqa: SLF001
