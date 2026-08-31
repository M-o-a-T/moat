"""
This module contains various helper functions and classes.
"""

from __future__ import annotations

import math
import os
import re
import sys
from pathlib import PosixPath

try:
    import ruyaml as yaml
    from ruyaml import constructor, emitter, representer
except ImportError:
    import ruamel.yaml as yaml
    from ruamel.yaml import constructor, emitter, representer

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
        from ruamel.yaml.constructor import BaseConstructor
        from ruamel.yaml.constructor import (
            SafeConstructor as SafeConstructorType,
        )
        from ruamel.yaml.emitter import Emitter as EmitterType
        from ruamel.yaml.nodes import Node
        from ruamel.yaml.representer import BaseRepresenter
        from ruamel.yaml.representer import (
            SafeRepresenter as SafeRepresenterType,
        )

    from collections.abc import Callable
    from typing import IO

try:
    from moat.lib.proxy import DProxy, Proxy
except ImportError:
    Proxy = None  # ty:ignore[invalid-assignment, misc]  # optional import
    DProxy = None  # ty:ignore[invalid-assignment, misc]  # optional import

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

SafeRepresenter.add_representer(PosixPath, SafeRepresenter.represent_str)


def load_ansible_repr() -> None:
    "Call me if you're using `moat.util` in conjunction with Ansible."

    # optional dependencies, imported at runtime
    from ansible.parsing.yaml.objects import (  # noqa: PLC0415
        AnsibleUnicode,
    )
    from ansible.utils.unsafe_proxy import (  # noqa: PLC0415
        AnsibleUnsafeText,
    )
    from ansible.vars.hostvars import (  # noqa: PLC0415
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
        data = round(data, int(14 - math.log10(abs(data))))
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


# Characters that need escaping in a ``!bina`` scalar: any non-printable
# byte (i.e. outside 0x20–0x7E plus tab/newline/return) or a literal
# backslash. Operating on a latin-1 string makes each codepoint map 1:1
# to a byte value.
_BINA_ENCODE_RE = re.compile(r"[^ -~\t\n\r]|\\")

# The inverse: a doubled backslash (literal backslash) or a ``\xHH``
# escape. Matching left-to-right removes any ambiguity between the two.
_BINA_DECODE_RE = re.compile(r"\\\\|\\x([0-9a-fA-F]{2})")


def _bina_encode_match(match: re.Match[str]) -> str:
    """Escape a single backslash or non-printable character for ``!bina``."""
    char = match.group(0)
    if char == "\\":
        return "\\\\"
    return f"\\x{ord(char):02x}"


def _bina_decode_match(match: re.Match[str]) -> str:
    """Unescape a doubled backslash or ``\\xHH`` escape from ``!bina``."""
    hex_digits = match.group(1)
    if hex_digits is None:
        return "\\"
    return chr(int(hex_digits, 16))


def _bin_from_bina(loader: BaseConstructor, node: Node) -> bytes:
    """Decode a ``!bina`` tagged value back into bytes.

    The ``!bina`` tag encodes non-printable bytes as ``\\xHH`` escape
    sequences and literal backslashes as ``\\\\`` so that the resulting
    string is valid ASCII.
    """
    value = loader.construct_scalar(node)
    return _BINA_DECODE_RE.sub(_bina_decode_match, value).encode("latin-1")


def _is_printable(b: int) -> bool:
    """Return True if a byte value is considered printable.

    Printable ASCII is 0x20–0x7E, plus the common whitespace
    characters tab (0x09), newline (0x0A) and carriage return (0x0D).
    """
    return (0x20 <= b <= 0x7E) or b in (0x09, 0x0A, 0x0D)


def _data_bytes(data: bytes | bytearray | memoryview) -> bytes:
    """Normalise any bytestring source to a plain ``bytes`` object."""
    return data.tobytes() if isinstance(data, memoryview) else bytes(data)


def _bin_to_ascii(dumper: SafeRepresenterType, data: bytes | bytearray | memoryview) -> Node:
    """Represent a bytestring in YAML.

    1. If it decodes as valid UTF-8, tag it ``!bin``.
    2. Otherwise, if fewer than 10 % of bytes are non-printable, tag it
       ``!bina`` with ``\\xHH`` escapes for the non-printable bytes and
       ``\\\\`` for literal backslashes.
    3. If it is shorter than 33 bytes, use ``!hex`` with colon-separated
       hex pairs.
    4. Otherwise fall back to ``!binary``.
    """
    data_bytes = _data_bytes(data)
    try:
        data_str = data_bytes.decode("utf-8")
    except UnicodeError:
        pass
    else:
        return dumper.represent_scalar("!bin", data_str)

    nonprintable = sum(1 for b in data_bytes if not _is_printable(b))
    threshold = max(1, len(data_bytes) * 10 // 100)
    if nonprintable < threshold:
        encoded = _BINA_ENCODE_RE.sub(_bina_encode_match, data_bytes.decode("latin-1"))
        return dumper.represent_scalar("!bina", encoded)

    if len(data_bytes) < 33:
        return dumper.represent_scalar("!hex", data_bytes.hex(":"))
    return dumper.represent_binary(data_bytes)


SafeRepresenter.add_representer(bytes, _bin_to_ascii)
SafeRepresenter.add_representer(bytearray, _bin_to_ascii)
SafeRepresenter.add_representer(memoryview, _bin_to_ascii)

SafeConstructor.add_constructor("!bin", _bin_from_ascii)
SafeConstructor.add_constructor("!bina", _bin_from_bina)
SafeConstructor.add_constructor("!hex", _bin_from_hex)


_expect_node = Emitter.expect_node


def expect_node(self: Any, *a: Any, **kw: Any) -> None:
    """
    YAML stream mangler.

    TODO rationale?
    """
    _expect_node(self, *a, **kw)
    self.root_context = False


Emitter.expect_node = expect_node  # monkey-patch


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

        class AttrConstructor(SafeConstructor):  # ty:ignore[unsupported-base, valid-type]  # runtime class creation
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
        y.width = sys.maxsize
        y.dump(data, stream=stream)


def yformat(data: Any, compact: bool = False) -> str:
    """
    Return ``data`` as a multi-line YAML string.

    :param data: The data to write.
    :param stream: the file to write to, defaults to stdout.
    :param compact: Write single lines if possible, default False.
    """
    from io import StringIO  # noqa: PLC0415

    s = StringIO()
    yprint(data, compact=compact, stream=s)  # ty:ignore[arg-type]  # StringIO is compatible with TextIOWrapper
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
