"""
Empty test file
"""

from __future__ import annotations

import anyio
import os
import pytest

from moat.lib.gpio import open_chip
from moat.lib.gpio.test import GpioWatcher
from moat.util.exec import CalledProcessError
from moat.util.exec import run as run_


async def preload():
    "Try to load the mock gpio kernel module"
    await run_("tests/moat_lib_gpio/test.sh")


try:
    anyio.run(preload)
except CalledProcessError:
    pytest.skip("Could not set up mock GPIO module", allow_module_level=True)


@pytest.mark.anyio
@pytest.mark.skipif(os.geteuid() != 0, reason="needs root")
async def test_mockup():
    """
    Empty test
    """
    async with GpioWatcher(interval=0.05).run() as w:
        try:
            with open_chip(label="gpio-mockup-A") as c:
                assert c.num_lines == 8, f"Should have eight lines, not {c.num_lines}"
                pass
        except RuntimeError:
            pytest.skip("GPIO Mockup module not loaded!")

        with open_chip(label="gpio-mockup-A") as c:
            assert c.label == "gpio-mockup-A"

            with c.line(1).open() as li:
                assert li.offset == 1
                assert not li.direction

                p = w.pin(c.name, 1)

                p.set(False)
                assert not li.value

                p.set(True)
                assert li.value

                p.set(False)
                assert not li.value

            with c.line(2).open(direction=True) as li:
                assert li.direction
                p = w.pin(c.name, 2)

                li.value = False
                await anyio.sleep(0.1)
                assert p.value is False

                li.value = True
                await anyio.sleep(0.1)
                assert p.value is True

                li.value = False
                await anyio.sleep(0.1)
                assert p.value is False


@pytest.mark.anyio
@pytest.mark.skipif(os.geteuid() != 0, reason="needs root")
async def test_poll():
    """
    Empty test
    """
    try:
        with open_chip(label="gpio-mockup-A") as c:
            assert c.num_lines == 8, f"Should have eight lines, not {c.num_lines}"
            pass
    except RuntimeError:
        pytest.skip("GPIO Mockup module not loaded!")

    async with (
        GpioWatcher(interval=0.05).run() as w,
        open_chip(label="gpio-mockup-A") as c,
    ):
        assert c.label == "gpio-mockup-A"

        with c.line(3).monitor() as li:
            p = w.pin(c.name, 3)

            ali = aiter(li)
            p.set(False)
            with anyio.move_on_after(0.1):
                s = await anext(ali)
                assert not s.value
            p.set(True)
            with anyio.fail_after(0.1):
                s = await anext(ali)
                assert s.value
            with anyio.move_on_after(0.1):
                s = await anext(ali)
                raise RuntimeError("two events", s)
            await anyio.sleep(0.1)
            p.set(False)
            with anyio.fail_after(0.1):
                s = await anext(ali)
                assert not s.value
            with anyio.move_on_after(0.1):
                s = await anext(ali)
                raise RuntimeError("two events", s)


pass  # pylint: disable=unnecessary-pass
