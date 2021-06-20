"""
This module contains various helper functions and classes.
"""
import ast
import collections.abc
import logging
import re
from functools import total_ordering
from typing import Union

import simpleeval

__all__ = ["Path", "P", "logger_for", "PathShortener", "PathLongener", "path_eval"]

_PartRE = re.compile("[^:._]+|_|:|\\.")


@total_ordering
class Path(collections.abc.Sequence):
    """
    This object represents the path to some node or other.

    It is an immutable list with special representation, esp. in YAML,
    and distinctive encoding in msgpack.

    Paths are represented as dot-separated strings. The colon is special.
    Inline (within an element):

        :.  escapes a dot
        ::  escapes a colon
        :_  escapes a space

    As separator (starts a new element):

        :t   True
        :f   False
        :e   empty string
        :n   None
        :xAB Hex integer
        :b01 Binary integer
        :vXY Bytestring, inline
        :yAB Bytestring, hex encoding

        :XYZ otherwise: evaluate XYZ (may not start with a letter)

    The empty path is denoted by a single colon. A path starting with a dot
    is illegal.

    Joining two paths requires a dot iff the second part doesn't start with
    a separator-colon, but you shouldn't ever want to do that: paths are
    best stored in Path objects, not strings.

    Paths are immutable and behave like lists with a human-readable string
    representation (if they consist of simple elements).
    """

    def __init__(self, *a):
        self._data: list = a

    @classmethod
    def build(cls, data):
        """Optimized shortcut to generate a path from an existing tuple"""
        if isinstance(data, Path):
            return data
        if not isinstance(data, tuple):
            return cls(*data)
        p = object.__new__(cls)
        p._data = data
        return p

    def __str__(self):
        def _escol(x, spaces=True):  # XXX make the default adjustable?
            x = x.replace(":", "::").replace(".", ":.")
            if spaces:
                x = x.replace(" ", ":_")
            return x

        res = []
        if not self._data:
            return ":"
        for x in self._data:
            if isinstance(x, str) and len(x):
                if res:
                    res.append(".")
                res.append(_escol(x))
            elif isinstance(x, (bytes, bytearray)):
                if all(32 <= b < 127 for b in x):
                    res.append(":v" + _escol(x.decode("ascii"), True))
                else:
                    res.append(":y" + x.hex())
            elif isinstance(x, (Path, tuple)) and len(x):
                x = ",".join(repr(y) for y in x)
                res.append(":" + _escol(x))
            elif x is True:
                res.append(":t")
            elif x is False:
                res.append(":f")
            elif x is None:
                res.append(":n")
            elif x == "":
                res.append(":e")
            else:
                if isinstance(x, (Path, tuple)):  # no spaces
                    assert not len(x)
                    x = "()"
                else:
                    x = repr(x)
                res.append(":" + _escol(x))
        return "".join(res)

    def __getitem__(self, x):
        if isinstance(x, slice) and x.start in (0, None) and x.step in (1, None):
            return type(self)(*self._data[x])
        else:
            return self._data[x]

    def __len__(self):
        return len(self._data)

    def __bool__(self):
        return True

    def __eq__(self, other):
        if isinstance(other, Path):
            other = other._data
        return self._data == other

    def __lt__(self, other):
        if isinstance(other, Path):
            other = other._data
        return self._data < other

    def __hash__(self):
        return hash(self._data)

    def __iter__(self):
        return self._data.__iter__()

    def __contains__(self, x):
        return x in self._data

    def __or__(self, other):
        return Path(*self._data, other)

    def __add__(self, other):
        if isinstance(other, Path):
            other = other._data
        if not len(other):
            return self
        return Path(*self._data, *other)

    # TODO add alternate output with hex integers

    def __repr__(self):
        return "P(%r)" % (str(self),)

    @classmethod
    def from_str(cls, path):
        """
        Constructor to build a Path from its string representation.
        """
        res = []
        part: Union[type(None), bool, str] = False
        # non-empty string: accept colon-eval or dot (inline)
        # True: require dot or colon-eval (after :t)
        # False: accept only colon-eval (start)
        # None: accept neither (after dot)

        esc: bool = False
        # marks that an escape char has been seen

        eval_: Union[bool, int] = False
        # marks whether the current input shall be evaluated;
        # 2=it's a hex number

        pos = 0
        if isinstance(path, (tuple, list)):
            return cls.build(path)
        if path == ":":
            return cls()

        def add(x):
            nonlocal part
            if not isinstance(part, str):
                part = ""
            try:
                part += x
            except TypeError:
                raise SyntaxError(f"Cannot add {x!r} at {pos}")

        def done(new_part):
            nonlocal part
            nonlocal eval_
            if isinstance(part, str):
                if eval_:
                    try:
                        if eval_ == -1:
                            part = bytes.fromhex(part)
                        elif eval_ == -2:
                            part = part.encode("ascii")
                        elif eval_ > 1:
                            part = int(part, eval_)
                        else:
                            part = path_eval(part)
                    except Exception as exc:
                        raise SyntaxError(f"Cannot eval {part!r} at {pos}") from exc
                    eval_ = False
                res.append(part)
            part = new_part

        def new(x, new_part):
            nonlocal part
            if part is None:
                raise SyntaxError(f"Cannot use {part!r} at {pos}")
            done(new_part)
            res.append(x)

        if path == "":
            raise SyntaxError("The empty string is not a path")
        for e in _PartRE.findall(path):
            if esc:
                esc = False
                if e in ":.":
                    add(e)
                elif e == "e":
                    new("", True)
                elif e == "t":
                    new(True, True)
                elif e == "f":
                    new(False, True)
                elif e == "n":
                    new(None, True)
                elif e == "_":
                    add(" ")
                elif e[0] == "b":
                    done(None)
                    part = e[1:]
                    eval_ = 2
                elif e[0] == "x":
                    done(None)
                    part = e[1:]
                    eval_ = 16
                elif e[0] == "y":
                    done(None)
                    part = e[1:]
                    eval_ = -1
                elif e[0] == "v":
                    done(None)
                    part = e[1:]
                    eval_ = -2
                else:
                    if part is None:
                        raise SyntaxError(f"Cannot parse {path!r} at {pos}")
                    done("")
                    add(e)
                    eval_ = True
            else:
                if e == ".":
                    if part is None or part is False:
                        raise SyntaxError(f"Cannot parse {path!r} at {pos}")
                    done(None)
                    pos += 1
                    continue
                elif e == ":":
                    esc = True
                    pos += 1
                    continue
                elif part is True:
                    raise SyntaxError(f"Cannot parse {path!r} at {pos}")
                else:
                    add(e)
            pos += len(e)
        if esc or part is None:
            raise SyntaxError(f"Cannot parse {path!r} at {pos}")
        done(None)
        return cls(*res)

    @classmethod
    def _make(cls, loader, node):
        value = loader.construct_scalar(node)
        return cls.from_str(value)


class P(Path):
    """
    A Path subclass that delegates to `Path.from_str`.

    For idempotency (required by ``click``) it transparently accepts `Path`
    objects.
    """

    def __new__(cls, path):
        if isinstance(path, Path):
            return path
        return Path.from_str(path)


def logger_for(path: Path):
    """
    Create a logger for this ``path``.

    The logger always starts with your main module name, with special
    treatment for paths starting with null or your-module-with-leading-dot.
    Thus if you import this code as "foo.util"::

        this path returns a logger for
        ========= ====================
        :         foo.root
        :n        foo.meta
        :n.x.y    foo.meta.x.y
        :.foo     foo.sub
        :.foo.z   foo.sub.z
        foo       foo
        foo.a.b   foo.a.b
        bar       foo.at.bar
        bar.c.d   foo.at.bar.c.d

    All elements in the path should be strings with no leading or trailing
    dot, though the first element may start with a dot or be None.

    """
    this = __name__.split(".", 1)[0]
    if not len(path):
        p = f"{this}.root"
    elif path[0] is None:
        p = f"{this}.meta"
    elif path[0] == f".{this}":
        p = f"{this}.sub"
    elif path[0] == this:
        p = this
    else:
        p = f"{this}.at.{path[0]}"
    if len(path) > 1:
        p += "." + ".".join(str(x) for x in path[1:])
    return logging.getLogger(p)


class PathShortener:
    """This class shortens path entries so that the initial components that
    are equal to the last-used path (or the original base) are skipped.

    It is illegal to path-shorten messages whose path does not start with
    the initial prefix.

    Example: The sequence

        a b
        a b c d
        a b c e f
        a b c e g h
        a b c i
        a b j

    is shortened to

        0
        0 c d
        1 e f
        2 g h
        1 i
        0 j

    where the initial number is the passed-in ``depth``, assuming the
    PathShortener is initialized with ``('a','b')``.

    Usage::

        >>> d = _PathShortener(['a','b'])
        >>> d({'path': 'a b c d'.split})
        {'depth':0, 'path':['c','d']}
        >>> d({'path': 'a b c e f'.split})
        {'depth':1, 'path':['e','f']}

    etc.

    Note that the input dict is modified in-place.

    """

    def __init__(self, prefix):
        self.prefix = prefix
        self.depth = len(prefix)
        self.path = []

    def __call__(self, res):
        try:
            p = res["path"]
        except KeyError:
            return
        if list(p[: self.depth]) != list(self.prefix):
            raise RuntimeError(f"Wrong prefix: has {p!r}, want {self.prefix!r}")

        p = p[self.depth :]  # noqa: E203
        cdepth = min(len(p), len(self.path))
        for i in range(cdepth):
            if p[i] != self.path[i]:
                cdepth = i
                break
        self.path = p
        p = p[cdepth:]
        res["path"] = p
        res["depth"] = cdepth


class PathLongener:
    """
    This reverts the operation of a PathShortener. You need to pass the
    same prefix in.

    Calling a PathLongener with a dict without ``depth`` or ``path``
    attributes is a no-op.
    """

    def __init__(self, prefix: Union[Path, tuple] = ()):
        self.depth = len(prefix)
        self.path = Path.build(prefix)

    def __call__(self, res):
        p = res.get("path", None)
        if p is None:
            return
        d = res.pop("depth", None)
        if d is None:
            return
        if not isinstance(p, tuple):
            # may be a list, dammit
            p = tuple(p)
        p = self.path[: self.depth + d] + p
        self.path = p
        res["path"] = p


# path_eval is a simple "eval" replacement to implement resolving
# expressions in paths. While it can be used for math, its primary function
# is to process tuples.
_eval = simpleeval.SimpleEval(functions={})
_eval.nodes[ast.Tuple] = lambda node: tuple(_eval._eval(x) for x in node.elts)
path_eval = _eval.eval
