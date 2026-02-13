"""
This module contains various helper functions and classes.
"""

from __future__ import annotations

import math
import os
import sys

try:
    import ruyaml as yaml
    from ruyaml import constructor, emitter, representer
except ImportError:
    import ruamel.yaml as yaml  # type: ignore[import-not-found]  # fallback import
    from ruamel.yaml import constructor, emitter, representer  # type: ignore[import-not-found]  # fallback import

from moat.lib.path import Path

from .dict import attrdict

from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    try:
        from ruyaml.constructor import BaseConstructor
        from ruyaml.constructor import SafeConstructor as SafeConstructorType
        from ruyaml.emitter import Emitter as EmitterType
        from ruyaml.nodes import Node
        from ruyaml.representer import BaseRepresenter
        from ruyaml.representer import SafeRepresenter as SafeRepresenterType
    except ImportError:
        from ruamel.yaml.constructor import BaseConstructor  # type: ignore[import-not-found]  # fallback import
        from ruamel.yaml.constructor import SafeConstructor as SafeConstructorType  # type: ignore[import-not-found]  # fallback import
        from ruamel.yaml.emitter import Emitter as EmitterType  # type: ignore[import-not-found]  # fallback import
        from ruamel.yaml.nodes import Node  # type: ignore[import-not-found]  # fallback import
        from ruamel.yaml.representer import BaseRepresenter  # type: ignore[import-not-found]  # fallback import
        from ruamel.yaml.representer import SafeRepresenter as SafeRepresenterType  # type: ignore[import-not-found]  # fallback import

    from collections.abc import Callable
    from typing import IO

try:
    from moat.lib.proxy import DProxy, Proxy
except ImportError:
    Proxy = None  # type: ignore[assignment, misc]  # optional import
    DProxy = None  # type: ignore[assignment, misc]  # optional import

__all__ = [
    "add_repr",
    "load_ansible_repr",
    "yaml_parse",
    "yaml_repr",
    "yformat",
    "yload",
    "yprint",
]

SafeRepresenter: type[SafeRepresenterType] = representer.SafeRepresenter
SafeConstructor: type[SafeConstructorType] = constructor.SafeConstructor
Emitter: type[EmitterType] = emitter.Emitter


SafeRepresenter.add_representer(attrdict, SafeRepresenter.represent_dict)


def load_ansible_repr() -> None:
    "Call me if you're using `moat.util` in conjunction with Ansible."
    from ansible.parsing.yaml.objects import (  # noqa: PLC0415  # optional dependency, imported at runtime
        AnsibleUnicode,  # type: ignore[import-not-found]  # optional dependency
    )
    from ansible.utils.unsafe_proxy import (  # noqa: PLC0415  # optional dependency, imported at runtime
        AnsibleUnsafeText,  # type: ignore[import-not-found]  # optional dependency
    )
    from ansible.vars.hostvars import (  # type: ignore[import-not-found]  # optional dependency  # noqa: PLC0415
        HostVars,
        HostVarsVars,
    )

    SafeRepresenter.add_representer(HostVars, SafeRepresenter.represent_dict)
    SafeRepresenter.add_representer(HostVarsVars, SafeRepresenter.represent_dict)
    SafeRepresenter.add_representer(AnsibleUnsafeText, SafeRepresenter.represent_str)
    SafeRepresenter.add_representer(AnsibleUnicode, SafeRepresenter.represent_str)


def str_presenter(dumper: BaseRepresenter, data: str) -> Node:
    """
    Always show multi-line strings with |-style quoting
    """
    if "\n" in data:  # multiline string?
        return dumper.represent_scalar("tag:yaml.org,2002:str", data, style="|")
    else:
        return dumper.represent_scalar("tag:yaml.org,2002:str", data)


def float_presenter(dumper: BaseRepresenter, data: float) -> Node:
    """
    Round appropriately
    """
    if data != 0:
        data = round(data, int(7 - math.log10(abs(data))))
    return dumper.represent_scalar("tag:yaml.org,2002:float", str(data))


def yaml_repr(name: str, use_repr: bool = False) -> Callable[[type], type]:
    """
    A class decorator that allows representing an object in YAML
    """

    def register(cls: type) -> type:
        def str_me(dumper: BaseRepresenter, data: Any) -> Node:
            return dumper.represent_scalar("!" + name, repr(data) if use_repr else str(data))

        SafeRepresenter.add_representer(cls, str_me)
        return cls

    return register


def yaml_parse(name: str, use_repr: bool = False) -> Callable[[type], type]:
    """
    A decorator that allows parsing a YAML representation,
    i.e. the opposite of `yaml_repr`.
    """

    def register(cls: type) -> type:
        SafeConstructor.add_constructor(f"!{name}", cls)
        return cls

    _ = use_repr  # unused
    return register


SafeRepresenter.add_representer(str, str_presenter)
SafeRepresenter.add_representer(float, float_presenter)


def _path_repr(dumper: BaseRepresenter, data: Path) -> Node:
    return dumper.represent_scalar("!P", str(data))


def _proxy_repr(dumper: BaseRepresenter, data: Any) -> Node:
    return dumper.represent_scalar("!R", data.name)


def _dproxy_repr(dumper: BaseRepresenter, data: Any) -> Node:
    return dumper.represent_scalar("!DP", repr([data.name, data.a, data.k]))


def read_env(loader: BaseConstructor, node: Node) -> str:
    value = loader.construct_scalar(node)
    return os.environ[value]


def _el_repr(dumper: BaseRepresenter, data: Any) -> Node:  # noqa: ARG001  # data unused but required by interface
    return dumper.represent_scalar("!R", "...")


SafeRepresenter.add_representer(type(Ellipsis), _el_repr)
SafeRepresenter.add_representer(Path, _path_repr)
SafeConstructor.add_constructor("!P", Path._make)

SafeConstructor.add_constructor("!env", read_env)

if Proxy is not None:
    SafeRepresenter.add_representer(Proxy, _proxy_repr)
if DProxy is not None:
    SafeRepresenter.add_representer(DProxy, _dproxy_repr)


def _name2obj(constructor: BaseConstructor, node: Node) -> Any:
    _ = constructor  # unused but required by interface

    from moat.lib.proxy import name2obj  # noqa: PLC0415

    return name2obj(node.value)


SafeConstructor.add_constructor("!R", _name2obj)


def _bin_from_ascii(loader: BaseConstructor, node: Node) -> bytes:
    value = loader.construct_scalar(node)
    return value.encode("ascii")


def _bin_from_hex(loader: BaseConstructor, node: Node) -> bytearray:
    value = loader.construct_scalar(node)
    return bytearray.fromhex(value.replace(":", ""))


def _bin_to_ascii(dumper: SafeRepresenterType, data: bytes | bytearray | memoryview) -> Node:
    try:
        if isinstance(data, memoryview):
            data_str = data.tobytes().decode("utf-8")
        else:
            data_str = data.decode("utf-8")
    except UnicodeError:
        data_bytes = data.tobytes() if isinstance(data, memoryview) else data
        if len(data_bytes) < 33:
            return dumper.represent_scalar("!hex", data_bytes.hex(":"))
        else:
            return dumper.represent_binary(data_bytes)
    else:
        return dumper.represent_scalar("!bin", data_str)


SafeRepresenter.add_representer(bytes, _bin_to_ascii)
SafeRepresenter.add_representer(bytearray, _bin_to_ascii)
SafeRepresenter.add_representer(memoryview, _bin_to_ascii)

SafeConstructor.add_constructor("!bin", _bin_from_ascii)
SafeConstructor.add_constructor("!hex", _bin_from_hex)


_expect_node = Emitter.expect_node


def expect_node(self: Any, *a: Any, **kw: Any) -> None:
    """
    YAML stream mangler.

    TODO rationale?
    """
    _expect_node(self, *a, **kw)
    self.root_context = False


Emitter.expect_node = expect_node  # type: ignore[method-assign]  # monkey-patch


def yload(
    stream: Any,
    multi: bool = False,
    attr: bool | type[attrdict] = False,
    typ: str = "safe",
) -> Any:
    """
    Load one or more YAML objects from a file.
    """
    y = yaml.YAML(typ=typ)
    if attr:

        class AttrConstructor(SafeConstructor):  # type: ignore[misc, valid-type]  # runtime class creation
            def __init__(self, *a: Any, **k: Any) -> None:
                super().__init__(*a, **k)
                self.yaml_base_dict_type = attrdict if attr is True else attr

        y.Constructor = AttrConstructor
    if multi:
        return y.load_all(stream)
    else:
        return y.load(stream)


def yprint(
    data: Any,
    stream: IO[str] = sys.stdout,
    compact: bool = False,
    typ: str = "safe",
) -> None:
    """
    Write a YAML record.

    :param data: The data to write.
    :param stream: the file to write to, defaults to stdout.
    :param compact: Write single lines if possible, default False.
    """
    if isinstance(data, int | float):
        print(data, file=stream)
    elif isinstance(data, str | bytes):
        print(repr(data), file=stream)
    #   elif isinstance(data, bytes):
    #       os.write(sys.stdout.fileno(), data)
    else:
        y = yaml.YAML(typ=typ)
        y.default_flow_style = compact
        y.dump(data, stream=stream)


def yformat(data: Any, compact: bool | None = None) -> str:
    """
    Return ``data`` as a multi-line YAML string.

    :param data: The data to write.
    :param stream: the file to write to, defaults to stdout.
    :param compact: Write single lines if possible, default False.
    """
    from io import StringIO  # noqa: PLC0415

    s = StringIO()
    yprint(data, compact=compact, stream=s)  # type: ignore[arg-type]  # StringIO is compatible with TextIOWrapper
    return s.getvalue()


def add_repr(typ: type, r: type | None = None) -> None:
    """
    Add a way to add representations for subtypes.

    This is useful for subclassed dict/int/str/… objects.
    """
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
