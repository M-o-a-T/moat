"""
Tests for the operator override items (HEAT.md §2.7).
"""

from __future__ import annotations

import anyio
import pytest

from jsonschema.exceptions import ValidationError

from moat.dev.heat.link import Override
from moat.dev.heat.override import OVERRIDES, _parse, path, publish_schemas, reader, set_override
from moat.lib.path import P
from moat.util.time import time

from typing import Any


@pytest.mark.parametrize(
    ("name", "value", "ok"),
    [
        ("wp", True, True),
        ("wp", False, True),
        ("wp", None, True),
        ("wp", {"value": False, "expires": 1e10, "reason": "service"}, True),
        ("wp", {"value": None}, True),
        ("wp", "yes", False),
        ("wp", 1, False),
        ("wp", {"value": True, "extra": 1}, False),
        ("wp", {"expires": 1e10}, False),
        ("pellet", True, True),
        ("flow_temp", 45, True),
        ("flow_temp", 45.5, True),
        ("flow_temp", "warm", False),
        ("pwm", 0.5, True),
        ("pwm", 1.5, False),
        ("errors", {"value": {":2": 123}}, True),
        ("errors", {":2": 123}, False),
        ("errors", {"value": {":2": "bad"}}, False),
    ],
)
@pytest.mark.anyio
async def test_schema(link, name: str, value: Any, ok: bool) -> None:
    "valid writes pass, invalid ones are rejected"
    await publish_schemas(link)
    await link.i_sync()
    if ok:
        await link.d_set(path(name), value, retain=True, verify=True)
    else:
        with pytest.raises(ValidationError):
            await link.d_set(path(name), value, retain=True, verify=True)


@pytest.mark.parametrize(
    ("kind", "raw", "want"),
    [
        (bool, True, True),
        (bool, False, False),
        (bool, None, None),
        (bool, 1, None),
        (bool, "on", None),
        (bool, {"value": False, "reason": "x"}, False),
        (float, 3, 3),
        (float, 3.5, 3.5),
        (float, True, None),
        (float, {"value": 40.0}, 40.0),
        (float, {"value": 40.0, "expires": 1.0}, None),  # long expired
    ],
)
def test_typed_reader(kind: type, raw: Any, want: Any) -> None:
    "a typed reader yields its type or None"
    r = Override[Any](None, P("test.ov"), kind=kind)  # ty:ignore[invalid-argument-type]
    r.feed(raw, time())
    assert r.value == want
    if isinstance(raw, dict):
        assert r.reason == raw.get("reason")


@pytest.mark.anyio
async def test_expiry_clears(link):
    "an override lapses on time: the reader reads None and the item is deleted"
    r = reader(link, "wp")
    async with anyio.create_task_group() as tg:
        await tg.start(r.run)
        await set_override(link, "wp", False, duration=0.5, reason="test")
        with anyio.fail_after(2):
            while r.value is not False:
                await r.wait_changed()
        assert r.reason == "test"
        with anyio.fail_after(2):
            while r.value is not None:
                await r.wait_changed()
        await anyio.sleep(0.2)
        await link.i_sync()
        with pytest.raises(KeyError):
            await link.d_get(path("wp"))
        tg.cancel_scope.cancel()


@pytest.mark.anyio
async def test_set_and_clear(link):
    "set_override writes plain or wrapped values; None clears"
    await publish_schemas(link)
    await link.i_sync()
    await set_override(link, "flow_temp", 42.0)
    await link.i_sync()
    assert await link.d_get(path("flow_temp")) == 42.0
    await set_override(link, "flow_temp", 42.0, reason="guests")
    await link.i_sync()
    assert await link.d_get(path("flow_temp")) == {"value": 42.0, "reason": "guests"}
    await set_override(link, "flow_temp", None)
    await link.i_sync()
    with pytest.raises(KeyError):
        await link.d_get(path("flow_temp"))
    with pytest.raises(ValidationError):
        await set_override(link, "pwm", 2.0)


def test_parse():
    "command-line values"
    assert _parse("wp", "on") is True
    assert _parse("wp", "OFF") is False
    assert _parse("wp", "auto") is None
    assert _parse("flow_temp", "41.5") == 41.5
    assert set(OVERRIDES) >= {"wp", "pellet", "flow_temp", "pwm", "errors"}
