"""
Empty test file
"""

from __future__ import annotations

from moat.lib.gpio import open_chip, Direction
from moat.lib.gpio.test import GpioWatcher
import anyio
import pytest
from moat.util.exec import run as run_

async def preload():
    await run_("tests/moat_lib_gpio/test.sh")

anyio.run(preload)


@pytest.mark.anyio
async def test_mockup():
    """
    Empty test
    """
    async with (
        anyio.create_task_group() as tg,
        GpioWatcher(interval=.05).run() as w,
    ):
        try:
            with open_chip(label="gpio-mockup-A") as c:
                assert c.num_lines == 8, f"Should have eight lines, not {c.num_lines}"
                pass
        except RuntimeError:
            pytest.skip("GPIO Mockup module not loaded!")

        with open_chip(label="gpio-mockup-A") as c:
            assert c.label == "gpio-mockup-A"

            with c.line(1).open() as li:
                assert li.offset==1
                assert not li.direction

                p = w.pin(c.name,1)

                p.set(False)
                assert not li.value

                p.set(True)
                assert li.value
                
                p.set(False)
                assert not li.value

            with c.line(2).open(direction=True) as li:
                assert li.direction
                p = w.pin(c.name,2)

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
        GpioWatcher(interval=.05).run() as w,
        open_chip(label="gpio-mockup-A") as c,
        ):
        assert c.label == "gpio-mockup-A"

        with c.line(3).monitor() as li:
            p = w.pin(c.name,3)

            ali=aiter(li)
            p.set(False)
            with anyio.move_on_after(.1):
                s=await anext(ali)
                assert not s.value
            p.set(True)
            with anyio.fail_after(.1):
                s=await anext(ali)
                assert s.value
            with anyio.move_on_after(.1):
                s=await anext(ali)
                raise RuntimeError("two events", s)
            await anyio.sleep(0.1)
            p.set(False)
            with anyio.fail_after(.1):
                s=await anext(ali)
                assert not s.value
            with anyio.move_on_after(.1):
                s=await anext(ali)
                raise RuntimeError("two events", s)


pass  # pylint: disable=unnecessary-pass
