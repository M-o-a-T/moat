"""
This module contains various helper functions and classes.
"""
import sys

import ruyaml as yaml

from ._dict import attrdict
from ._path import Path

__all__ = ["yload", "yprint", "yformat", "yaml_named"]

SafeRepresenter = yaml.representer.SafeRepresenter
SafeConstructor = yaml.constructor.SafeConstructor
Emitter = yaml.emitter.Emitter


SafeRepresenter.add_representer(attrdict, SafeRepresenter.represent_dict)


def str_presenter(dumper, data):
    if "\n" in data:  # check for multiline string
        return dumper.represent_scalar("tag:yaml.org,2002:str", data, style="|")
    return dumper.represent_scalar("tag:yaml.org,2002:str", data)


def yaml_named(name: str, use_repr: bool = False):
    """
    A class decorator that allows representing an object in YAML
    """
    def register(cls):
        def str_me(dumper, data):
            return dumper.represent_scalar("!" + name, repr(data) if use_repr else str(data))

        SafeRepresenter.add_representer(cls, str_me)
        return cls

    return register


SafeRepresenter.add_representer(str, str_presenter)


def _path_repr(dumper, data):
    return dumper.represent_scalar("!P", str(data))
    # return ScalarNode(tag, value, style=style)
    # return yaml.events.ScalarEvent(anchor=None, tag='!P', implicit=(True, True), value=str(data))


SafeRepresenter.add_representer(Path, _path_repr)
SafeConstructor.add_constructor("!P", Path._make)


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
    _expect_node(self, *a, **kw)
    self.root_context = False


Emitter.expect_node = _expect_node


def yload(stream, multi=False):
    """
    Load one or more YAML objects from a file.
    """
    y = yaml.YAML(typ="safe")
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
    from io import StringIO

    s = StringIO()
    yprint(data, compact=compact, stream=s)
    return s.getvalue()
