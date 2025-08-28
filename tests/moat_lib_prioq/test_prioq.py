import pytest
from heapmap import HeapMap


def test_initialization_min_heap():
    h = HeapMap({'a': 5, 'b': 2, 'c': 8})
    assert len(h) == 3
    # peek should return smallest key 'b'
    key, prio = h.peekitem()
    assert key == 'b' and prio == 2


def test_initialization_max_heap():
    h = HeapMap({'a': 5, 'b': 2, 'c': 8}, is_max_heap=True)
    assert len(h) == 3
    key, prio = h.peekitem()
    assert key == 'c' and prio == 8


def test_setitem_and_getitem():
    h = HeapMap()
    h['x'] = 10
    assert h['x'] == 10
    # # update via __setitem__ should update and reorder
    # h['x'] = 1
    # assert h['x'] == 1
    # assert h.peekitem() == ('x', 1)


def test_invalid_priority():
    h = HeapMap()
    with pytest.raises(TypeError):
        h['k'] = 'not a number'  # invalid priority


def test_popitem_and_ordering():
    h = HeapMap({'a': 3, 'b': 1, 'c': 2})
    popped = []
    while not h.is_empty():
        popped.append(h.popitem())
    assert popped == [('b', 1), ('c', 2), ('a', 3)]


def test_peekitem_empty():
    h = HeapMap()
    with pytest.raises(IndexError):
        h.peekitem()


def test_popitem_empty():
    h = HeapMap()
    with pytest.raises(IndexError):
        h.popitem()


def test_delete_item():
    h = HeapMap({'a': 1, 'b': 2})
    del h['a']
    assert 'a' not in h
    # remaining is b
    assert len(h) == 1
    assert h.peekitem() == ('b', 2)


def test_update():
    h = HeapMap({'a': 5, 'b': 2})
    h.update('a', 1)
    assert h['a'] == 1
    # now a is smallest
    assert h.peekitem() == ('a', 1)
    with pytest.raises(KeyError):
        h.update('c', 10)
    with pytest.raises(TypeError):
        h.update('a', 'bad')


def test_clear_and_is_empty():
    h = HeapMap({'x': 1, 'y': 2})
    h.clear()
    assert h.is_empty()


def test_contains_and_len():
    h = HeapMap()
    h['foo'] = 42
    assert 'foo' in h
    assert len(h) == 1
    assert 'bar' not in h


def test_keys_items_values_iteration_and_modification_error():
    h = HeapMap({'a': 1, 'b': 2, 'c': 3})
    keys = list(h.keys())
    assert set(keys) == {'a', 'b', 'c'}
    items = list(h.items())
    assert set(items) == {('a', 1), ('b', 2), ('c', 3)}
    values = list(h.values())
    assert set(values) == {1, 2, 3}

    # test iteration returning both key and priority
    it = iter(h)
    first = next(it)
    assert isinstance(first, tuple) and len(first) == 2

    # test modification during iteration raises
    it2 = iter(h)
    next(it2)
    with pytest.raises(RuntimeError):
        h['d'] = 4
        next(it2)
