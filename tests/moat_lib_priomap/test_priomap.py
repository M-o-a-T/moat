from __future__ import annotations  # noqa: D100

import anyio
import pytest

from moat.lib.priomap import PrioMap


def test_initialization_min_heap():  # noqa: D103
    h = PrioMap({"a": 5, "b": 2, "c": 8})
    assert len(h) == 3
    # peek should return smallest key 'b'
    key, prio = h.peek()
    assert key == "b"
    assert prio == 2


def test_setitem_and_getitem():  # noqa: D103
    h = PrioMap()
    h["x"] = 10
    assert h["x"] == 10
    # # update via __setitem__ should update and reorder
    # h['x'] = 1
    # assert h['x'] == 1
    # assert h.peek() == ('x', 1)


def test_pop_and_ordering():  # noqa: D103
    h = PrioMap({"a": 3, "b": 1, "c": 2})
    popped = []
    while not h.is_empty():
        popped.append(h.pop())
    assert popped == [("b", 1), ("c", 2), ("a", 3)]


def test_peek_empty():  # noqa: D103
    h = PrioMap()
    with pytest.raises(IndexError):
        h.peek()


def test_pop_empty():  # noqa: D103
    h = PrioMap()
    with pytest.raises(IndexError):
        h.pop()


def test_delete_item():  # noqa: D103
    h = PrioMap({"a": 1, "b": 2})
    del h["a"]
    assert "a" not in h
    # remaining is b
    assert len(h) == 1
    assert h.peek() == ("b", 2)


def test_pop_item():  # noqa: D103
    h = PrioMap({"a": 1, "b": 2})
    assert h.pop("b") == 2
    assert "b" not in h
    # remaining is b
    assert len(h) == 1
    assert h.peek() == ("a", 1)


def test_update():  # noqa: D103
    h = PrioMap({"a": 5, "b": 2})
    h.update("a", 1)
    assert h["a"] == 1
    # now a is smallest
    assert h.peek() == ("a", 1)
    with pytest.raises(KeyError):
        h.update("c", 10)
    with pytest.raises(TypeError):
        h.update("a", "bad")


def test_clear_and_is_empty():  # noqa: D103
    h = PrioMap({"x": 1, "y": 2})
    h.clear()
    assert h.is_empty()


def test_contains_and_len():  # noqa: D103
    h = PrioMap()
    h["foo"] = 42
    assert "foo" in h
    assert len(h) == 1
    assert "bar" not in h


def test_keys_items_values_iteration_and_modification_error():  # noqa: D103
    h = PrioMap({"a": 1, "b": 2, "c": 3})
    keys = list(h.keys())
    assert set(keys) == {"a", "b", "c"}
    items = list(h.items())
    assert set(items) == {("a", 1), ("b", 2), ("c", 3)}
    values = list(h.values())
    assert set(values) == {1, 2, 3}

    # test iteration returning both key and priority
    it = iter(h)
    first = next(it)
    assert isinstance(first, tuple)
    assert len(first) == 2

    # test modification during iteration raises
    it2 = iter(h)
    next(it2)
    h["d"] = 4
    with pytest.raises(RuntimeError):
        next(it2)


@pytest.mark.anyio
async def test_aiter():  # noqa: D103
    res = []
    h = PrioMap({"a": 1, "b": 2, "c": 3})

    async def reader():
        async for k, _ in h:
            res.append(k)
            await anyio.sleep(0.05)

    async with anyio.create_task_group() as tg:
        tg.start_soon(reader)
        await anyio.sleep(0.025)
        assert h.peek() == ("b", 2)
        h["y"] = 2.5
        h["x"] = 1
        while h:  # noqa:ASYNC110
            await anyio.sleep(0.025)
        assert not h
        h["z"] = 0
        await anyio.sleep(0.11)
        tg.cancel_scope.cancel()

    assert "".join(res) == "axbycz"
