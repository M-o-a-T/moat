"""
This module contains various helper functions and classes.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Mapping, Sequence

import ruyaml as yaml

from .dict import attrdict

try:
    from .msgpack import Proxy
except ImportError:
    Proxy = None
from moat.lib.codec.proxy import name2obj

from .path import Path

__all__ = ["yload", "yprint", "yformat", "yaml_repr", "yaml_parse", "add_repr"]

SafeRepresenter = yaml.representer.SafeRepresenter
SafeConstructor = yaml.constructor.SafeConstructor
Emitter = yaml.emitter.Emitter


SafeRepresenter.add_representer(attrdict, SafeRepresenter.represent_dict)
SafeConstructor.yaml_base_dict_type = attrdict


def str_presenter(dumper, data):
    """
    Always show multi-line strings with |-style quoting
    """
    if "\n" in data:  # multiline string?
        return dumper.represent_scalar("tag:yaml.org,2002:str", data, style="|")
    else:
        return dumper.represent_scalar("tag:yaml.org,2002:str", data)


def yaml_repr(name: str, use_repr: bool = False):
    """
    A class decorator that allows representing an object in YAML
    """

    def register(cls):
        def str_me(dumper, data):
            return dumper.represent_scalar("!" + name, repr(data) if use_repr else str(data))

        SafeRepresenter.add_representer(cls, str_me)
        return cls

    return register


def yaml_parse(name: str, use_repr: bool = False):
    """
    A decorator that allows parsing a YAML representation,
    i.e. the opposite of `yaml_repr`.
    """

    def register(cls):
        SafeConstructor.add_constructor(f"!{name}", cls)
        return cls

    use_repr  # noqa: B018
    return register


SafeRepresenter.add_representer(str, str_presenter)


def _path_repr(dumper, data):
    return dumper.represent_scalar("!P", str(data))
    # return ScalarNode(tag, value, style=style)
    # return yaml.events.ScalarEvent(anchor=None, tag='!P', implicit=(True, True), value=str(data))


def _proxy_repr(dumper, data):
    return dumper.represent_scalar("!R", data.name)
    # return ScalarNode(tag, value, style=style)
    # return yaml.events.ScalarEvent(anchor=None, tag='!P', implicit=(True, True), value=str(data))


def read_env(loader, node):
    value = loader.construct_scalar(node)
    return os.environ[value]


SafeRepresenter.add_representer(Path, _path_repr)
SafeConstructor.add_constructor("!P", Path._make)

SafeConstructor.add_constructor("!env", read_env)

if Proxy is not None:
    SafeRepresenter.add_representer(Proxy, _proxy_repr)
SafeConstructor.add_constructor("!R", name2obj)


def _bin_from_ascii(loader, node):
    value = loader.construct_scalar(node)
    return value.encode("ascii")


def _bin_from_hex(loader, node):
    value = loader.construct_scalar(node)
    return bytearray.fromhex(value.replace(":", ""))


def _bin_to_ascii(dumper, data):
    try:
        data = data.decode("ascii")
    except UnicodeError:
        if len(data) < 33:
            return dumper.represent_scalar("!hex", data.hex(":"))
        else:
            return dumper.represent_binary(data)
    else:
        return dumper.represent_scalar("!bin", data)


SafeRepresenter.add_representer(bytes, _bin_to_ascii)

SafeConstructor.add_constructor("!bin", _bin_from_ascii)
SafeConstructor.add_constructor("!hex", _bin_from_hex)


_expect_node = Emitter.expect_node


def expect_node(self, *a, **kw):
    """
    YAML stream mangler.

    TODO rationale?
    """
    _expect_node(self, *a, **kw)
    self.root_context = False


Emitter.expect_node = expect_node


def yload(stream, multi=False, attr=False):
    """
    Load one or more YAML objects from a file.
    """
    y = yaml.YAML(typ="safe")
    if attr:

        class AttrConstructor(SafeConstructor):  # pylint: disable=missing-class-docstring
            def __init__(self, *a, **k):
                super().__init__(*a, **k)
                self.yaml_base_dict_type = attrdict if attr is True else attr

        y.Constructor = AttrConstructor
    if multi:
        return y.load_all(stream)
    else:
        return y.load(stream)


def yprint(data, stream=sys.stdout, compact=False):
    """
    Write a YAML record.

    :param data: The data to write.
    :param stream: the file to write to, defaults to stdout.
    :param compact: Write single lines if possible, default False.
    """
    if isinstance(data, (int, float)):
        print(data, file=stream)
    elif isinstance(data, (str, bytes)):
        print(repr(data), file=stream)
    #   elif isinstance(data, bytes):
    #       os.write(sys.stdout.fileno(), data)
    else:
        y = yaml.YAML(typ="safe")
        y.default_flow_style = compact
        y.dump(data, stream=stream)


def yformat(data, compact=None):
    """
    Return ``data`` as a multi-line YAML string.

    :param data: The data to write.
    :param stream: the file to write to, defaults to stdout.
    :param compact: Write single lines if possible, default False.
    """
    from io import StringIO  # pylint: disable=import-outside-toplevel

    s = StringIO()
    yprint(data, compact=compact, stream=s)
    return s.getvalue()


def add_repr(typ, r=None):
    """
    Add a way to add representations for subtypes.

    This is useful for subclassed dict/int/str/… objects.
    """
    # pylint: disable=redefined-builtin
    if r is None:
        r = typ
    if issubclass(r, str):
        SafeRepresenter.add_representer(typ, SafeRepresenter.represent_str)
    elif issubclass(r, float):
        SafeRepresenter.add_representer(typ, SafeRepresenter.represent_float)
    elif issubclass(r, bool):
        SafeRepresenter.add_representer(typ, SafeRepresenter.represent_bool)
    elif issubclass(r, int):
        SafeRepresenter.add_representer(typ, SafeRepresenter.represent_int)
    elif issubclass(r, Mapping):
        SafeRepresenter.add_representer(typ, SafeRepresenter.represent_dict)
    elif issubclass(r, Sequence):
        SafeRepresenter.add_representer(typ, SafeRepresenter.represent_list)
    else:
        raise TypeError(f"Don't know what to do with {typ}")
