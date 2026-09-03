"""
Tests for moat.lib.proxy — proxy name/object mapping and serialization.
"""

from __future__ import annotations

import pytest

from moat.lib.proxy import (
    DProxy,
    Proxy,
    as_proxy,
    drop_proxy,
    get_proxy,
    name2obj,
    obj2name,
)
from moat.lib.proxy._proxy import _CProxy


class TestName2Obj:
    """Test name2obj registration and lookup."""

    def test_register_and_lookup(self):
        """register and lookup."""
        obj = object()
        name2obj("_test_foo", obj)
        assert name2obj("_test_foo") is obj

    def test_lookup_missing_raises(self):
        """lookup missing raises."""
        with pytest.raises(KeyError):
            name2obj("_nonexistent_proxy_xyz")

    def test_overwrite_existing(self):
        """overwrite existing."""
        obj1 = object()
        obj2 = object()
        name2obj("_test_overwrite", obj1)
        name2obj("_test_overwrite", obj2)
        assert name2obj("_test_overwrite") is obj2


class TestObj2Name:
    """Test obj2name reverse lookup."""

    def test_registered_object_returns_name(self):
        """registered object returns name."""
        obj = object()
        name2obj("_test_o2n", obj)
        assert obj2name(obj) == "_test_o2n"

    def test_unregistered_object_raises(self):
        """unregistered object raises."""

        # Use a class instance to get a unique id that won't collide
        # with objects from other tests (Python may reuse memory addresses)
        class _Unique:
            pass

        obj = _Unique()
        with pytest.raises(KeyError):
            obj2name(obj)


class TestGetProxy:
    """Test get_proxy — like obj2name but creates a temporary name if unknown."""

    def test_known_object(self):
        """known object."""
        obj = object()
        name2obj("_test_gp", obj)
        assert get_proxy(obj) == "_test_gp"

    def test_unknown_object_creates_name(self):
        """unknown object creates name."""
        obj = object()
        name = get_proxy(obj)
        assert name.startswith("p_")
        # Should now be registered
        assert name2obj(name) is obj

    def test_repeated_call_returns_same_name(self):
        """repeated call returns same name."""
        obj = object()
        name1 = get_proxy(obj)
        name2 = get_proxy(obj)
        assert name1 == name2


class TestAsProxy:
    """Test as_proxy decorator and function."""

    def test_decorator_form(self):
        """decorator form."""

        @as_proxy("_test_decorated")
        class MyClass:
            pass

        assert name2obj("_test_decorated") is MyClass
        assert obj2name(MyClass) == "_test_decorated"

    def test_function_form(self):
        """function form."""
        obj = object()
        result = as_proxy("_test_func", obj)
        assert result is obj
        assert name2obj("_test_func") is obj

    def test_duplicate_raises(self):
        """duplicate raises."""
        obj1 = object()
        as_proxy("_test_dup", obj1)

        obj2 = object()
        with pytest.raises(ValueError, match="already exists"):
            as_proxy("_test_dup", obj2)

    def test_replace_allows_overwrite(self):
        """replace allows overwrite."""
        obj1 = object()
        as_proxy("_test_replace", obj1)

        obj2 = object()
        as_proxy("_test_replace", obj2, replace=True)
        assert name2obj("_test_replace") is obj2


class TestDropProxy:
    """Test drop_proxy cleanup."""

    def test_drop_by_name(self):
        """drop by name."""
        obj = object()
        as_proxy("test_drop", obj)
        drop_proxy("test_drop")
        assert "test_drop" not in _CProxy

    def test_drop_by_object(self):
        """drop by object."""
        obj = object()
        as_proxy("test_drop_obj", obj)
        drop_proxy(obj)
        assert "test_drop_obj" not in _CProxy

    def test_drop_system_proxy_raises(self):
        """System proxies (starting with _) cannot be dropped."""
        with pytest.raises(ValueError, match="system proxy"):
            drop_proxy("_")

    def test_drop_empty_raises(self):
        """drop empty raises."""
        with pytest.raises(ValueError, match="system proxy"):
            drop_proxy("")


class TestProxyClass:
    """Test the Proxy class."""

    def test_repr(self):
        """repr."""
        p = Proxy("my_proxy")
        assert "my_proxy" in repr(p)
        assert "Proxy" in repr(p)

    def test_ref(self):
        """ref."""
        obj = object()
        name2obj("_test_ref", obj)
        p = Proxy("_test_ref")
        assert p.ref() is obj

    def test_name_attribute(self):
        """name attribute."""
        p = Proxy("foo")
        assert p.name == "foo"


class TestDProxyClass:
    """Test the DProxy class."""

    def test_init_with_args_and_kwargs(self):
        """init with args and kwargs."""
        dp = DProxy("_test_dp", [1, 2, 3], {"key": "val"})
        assert dp.name == "_test_dp"
        assert dp.a == [1, 2, 3]
        assert dp.k == {"key": "val"}

    def test_init_empty(self):
        """init empty."""
        dp = DProxy("_test_dp_empty", None, {})
        assert dp.a == []
        assert dp.k == {}

    def test_getitem_by_index(self):
        """getitem by index."""
        dp = DProxy("_test_dp_gi", [10, 20, 30], {})
        assert dp[0] == 10
        assert dp[1] == 20
        assert dp[2] == 30

    def test_getitem_by_key(self):
        """getitem by key."""
        dp = DProxy("_test_dp_gik", [], {"foo": "bar"})
        assert dp["foo"] == "bar"

    def test_eq_same(self):
        """eq same."""
        dp1 = DProxy("_test_eq", [1, 2], {"a": "b"})
        dp2 = DProxy("_test_eq", [1, 2], {"a": "b"})
        assert dp1 == dp2

    def test_eq_different_name(self):
        """eq different name."""
        dp1 = DProxy("_test_eq1", [1], {})
        dp2 = DProxy("_test_eq2", [1], {})
        assert dp1 != dp2

    def test_eq_different_args(self):
        """eq different args."""
        dp1 = DProxy("_test_eq3", [1, 2], {})
        dp2 = DProxy("_test_eq3", [1, 3], {})
        assert dp1 != dp2

    def test_eq_different_kwargs(self):
        """eq different kwargs."""
        dp1 = DProxy("_test_eq4", [1], {"a": "b"})
        dp2 = DProxy("_test_eq4", [1], {"a": "c"})
        assert dp1 != dp2

    def test_eq_not_dproxy(self):
        """eq not dproxy."""
        dp = DProxy("_test_eq5", [1], {})
        assert dp != 42
        assert dp != "string"

    def test_repr(self):
        """repr."""
        dp = DProxy("_test_repr", [1, 2], {"k": "v"})
        r = repr(dp)
        assert "_test_repr" in r
        assert "DProxy" in r

    def test_append(self):
        """append."""
        dp = DProxy("_test_app", [], {})
        dp.append(42)
        assert dp.a == [42]

    def test_setitem(self):
        """setitem."""
        dp = DProxy("_test_si", [], {})
        dp["key"] = "value"
        assert dp.k == {"key": "value"}
