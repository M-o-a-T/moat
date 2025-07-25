"""
This module contains functions dealing with MoaT's Path objects.

MoaT Paths are represented as dot-separated strings. The colon is special.
See "moat util path" / moat.util.Path.__doc__ for details.

Behind the scenes, a Path is an immutable lists with special representation.
This is particularly useful in YAML (MoaT uses a ``!P`` prefix).

They are also marked in msgpack and CBOR.

Joining the string representation of two non-empty paths requires a dot iff
the second part doesn't start with a separator-colon, but you shouldn't
ever want to do that: paths are best processed as Path objects, not
strings.


This module also exports the magic paths "Root", "S_Root", "P_Root" and
"Q_Root". These are contextvars and can be set externally. They are
interpolated into slashed Path representations.

"""

from __future__ import annotations

import ast
import collections.abc
import logging
import re
import warnings
from base64 import b64decode, b64encode
from contextvars import ContextVar
from functools import total_ordering

import simpleeval

from moat.lib.codec.proxy import as_proxy
from . import NotGiven

__all__ = [
    "Path",
    "P",
    "PS",
    "logger_for",
    "PathShortener",
    "PathLongener",
    "path_eval",
    "Root",
    "RootPath",
    "set_root",
]

_PartRE = re.compile("[^:._]+|_|:|\\.")
_RTagRE = re.compile("^:m[^:._]+:$")


def set_root(cfg):
    """
    Utility to force-set the root global.

    Used for testing without a "proper" context.
    """
    from moat.util.path import Root, S_Root,P_Root,Q_Root
    Root.set(cfg.root)


@total_ordering
class Path(collections.abc.Sequence):
    """
    Paths are represented as dot-separated strings. The colon is special.
    Inline (within an element):

    \b
        ::  escapes : colon
        :.  escapes . dot   (dot-path repr only)
        :_  escapes   space (dot-path repr only)
        :|  escapes / slash (slash-path repr only)
        :h  escapes # hash  (slash-path repr only, optional)
        :p  escapes + plus  (slash-path repr only, optional)

    As separator (starts a new element):

    \b
        :t   True
        :f   False
        :e   empty string
        :n   None
        :z   Ellipsis / NotGiven
        :?   Error, reference to a variable that's not set
             (will parse as NotGiven, for round-trip type safety)

        :xAB Hex integer
        :b01 Binary integer
        :vXY Bytestring, inline
        :yAB Bytestring, hex encoding
        :sAB Bytestring, base64 encoding
        :iXY evaluate XY as a Python expression.
             The 'i' may be missing if XY does not start with a letter.

    Meta elements (delimits elements, SHOULD be in front):

    \b
        :mXX This path is marked with XX (deprecated)
        :R   An alias for the current root
        :Q   An alias for an alternate root
        :P   An alias for another alternate root
        :S   An alias for yet another alternate root

    The empty path is denoted by a single colon. A dotted path that starts
    or ends with a dot, or that contains empty elements (two non-escaped dots,
    one dot followed by a separator) is illegal.

    The alternate slash-path representation uses slashes as separators.
    **Path marks are ignored** when generating the slashed representation.

    Paths can be concatenated with "+", "/" or "|".
    "% n" removes n items from the end.

    All Path objects are read-only.

    The Root paths are context variables. If they are set and an "incoming"
    path has one of them as prefix, said prefix is replaced with a placeholder
    for this root. It is expanded in "slashed" form but not as native
    representation. That way, specific paths can be encoded in a root-free
    form, thus if you ever rename the root, or move entries from one
    MoaT-Link setup to another, everything still works.
    """

    def __init__(self, *a, mark="", scan=False):
        if mark:
            warnings.warn("Marking a path is deprecated")
        if any(isinstance(x,list) for x in a):
            a=tuple(tuple(x) if isinstance(x,list) else x for x in a)
        if a and scan:
            i = 0
            while i < len(a):
                for proxy in _Roots.values():
                    if not proxy:
                        continue

                    if len(a) >= i + len(proxy) and a[i : i + len(proxy)] == proxy:
                        a = a[:i] + (proxy,) + a[i + len(proxy) :]
                        break
                i += 1

        self._data: tuple = a
        if mark is None:
            raise ValueError("Use an empty mark, not 'None'")
        self._mark = mark

    @classmethod
    def build(cls, data, *, mark=""):
        """Optimized shortcut to generate a path from an existing tuple"""
        if mark:
            warnings.warn("Marking a path is deprecated")
        if isinstance(data, Path):
            return data
        if not isinstance(data, tuple) or any(isinstance(x,list) for x in data):
            return cls(*data)
        p = object.__new__(cls)
        p._data = tuple(data)  # noqa:SLF001
        if mark is None:
            raise ValueError("Use an empty mark, not 'None'")
        p._mark = mark  # noqa:SLF001
        return p

    def as_tuple(self):
        """deprecated"""
        return self._data

    @property
    def raw(self):
        """as tuple"""
        return self._data

    @property
    def mark(self):
        "accessor for the path's mark"
        return self._mark

    def startswith(self,path:Path|tuple|list):
        """
        Prefix test
        """
        if isinstance(path,Path):
            path=path._data
        if not isinstance(path,tuple):
            path=tuple(path)

        return self._data[:len(path)] == path

    def with_mark(self, mark=""):
        """Returns the same path with a different mark"""
        if mark:
            warnings.warn("Marking a path is deprecated")
        if mark is None:
            raise ValueError("Use an empty mark, not 'None'")
        return type(self).build(self._data, mark=mark)

    def __str__(self, slash:bool|Literal[2]=False):
        """
        Stringify the path to a dotstring.

        If not slashed: Spaces are escaped somewhat aggressively, for
        better doubleclickability. Do not depend on this.

        If slashed, space escaping is restricted to bytestrings.
        If slash==2, also escape # and +.

        Slash encoding does not work with empty paths; marks are ignored.
        """

        def _escol(x, spaces=True):
            x = x.replace(":", "::")  # must be first
            if slash:
                x = x.replace("/", ":|")
            else:
                x = x.replace(".", ":.")
            if slash == 2:
                x = x.replace("#", ":h")
                x = x.replace("+", ":p")
            if spaces:
                x = x.replace(" ", ":_")
            return x

        res = []
        if self.mark and not slash:
            res.append(":m" + self.mark)
        if self._data is None:
            return ":?"
        if not self._data:
            if slash:
                raise ValueError("Empty paths cannot be slash-coded")
            res.append(":")
        for x in self._data:
            if slash and res:
                res.append("/")

            if isinstance(x, str):
                if slash:
                    res.append(_escol(x, False))
                elif x == "":
                    res.append(":e")
                else:
                    if res:
                        res.append(".")
                    res.append(_escol(x))
            elif x is NotGiven:
                res.append(":z")
            elif x is True:
                res.append(":t")
            elif x is False:
                res.append(":f")
            elif x is None:
                res.append(":n")
            elif isinstance(x, RootPath):
                if not slash:
                    res.append(f":{x.key}")
                else:
                    if not x or len(x) == 0:
                        raise RuntimeError(f"You need to set {x.name}")
                    res.append(x.slashed)

            elif isinstance(x, (bytes, bytearray, memoryview)):
                if all(32 <= b < 127 for b in x):
                    res.append(":v" + _escol(x.decode("ascii"), True))
                else:
                    res.append(":s" + b64encode(x).decode("ascii"))
                    # no hex
            elif isinstance(x, (Path, tuple)):
                if len(x):
                    x = ",".join(repr(y) for y in x)  # noqa: PLW2901
                    res.append(":" + _escol(x) + ("," if len(x)==1 else ""))
                else:
                    x = "()"  # noqa: PLW2901
            else:
                x = repr(x)  # noqa: PLW2901
                if x[0].isalpha():
                    x = "i" + x  # noqa: PLW2901
                res.append(":" + _escol(x))
        return "".join(res)

    @property
    def slashed(self):
        """
        Stringify the path to a slashed string.

        Spaces are not escaped, except in bytestrings.
        """

        return self.__str__(slash=True)

    @property
    def slashed2(self):
        """
        Stringify the path to a slashed string.

        Spaces are not escaped, except in bytestrings.

        This also escapes + and # characters, for use in MQTT publish
        (but possibly-maybe NOT subscribe) paths.
        """

        return self.__str__(slash=2)

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
        if other is None:
            return False
        if isinstance(other, Path):
            if self.mark != other.mark:
                return False
            other = other._data
        else:
            try:
                other = tuple(other)
            except TypeError:
                return NotImplemented

        return self._data == other

    def __lt__(self, other):
        other = other._data if isinstance(other, Path) else tuple(other)
        return self._data < other

    def __hash__(self):
        return hash(self._data)

    def __iter__(self):
        return self._data.__iter__()

    def __contains__(self, x):
        return x in self._data

    def __mod__(self, other):
        if len(self._data) < other:
            raise ValueError("Path too short")
        return Path(*self._data[:-other], mark=self.mark)

    def _tag_add(self, other):
        if not isinstance(other, Path):
            return self.mark
        if not other.mark:
            return self.mark
        if not self.mark:
            return other.mark
        if self.mark != other.mark:
            raise RuntimeError(
                f"Can't concat paths with different tags: {self.mark} and {other.mark}",
            )
        return self.mark

    def __add__(self, other):
        mark = self._tag_add(other)
        if isinstance(other, Path):
            other = other._data
        elif not isinstance(other, (list, tuple)):
            other = (other,)
        if len(other) == 0:
            if self.mark != mark:
                return self.build(self._data, mark=mark)
            return self
        if isinstance(other[0],Path):
            return type(self)(*self._data, *other[0], *other[1:], mark=mark)
        return type(self)(*self._data, *other, mark=mark)

    def __or__(self, other):
        return self + other

    def __div__(self, other):
        return self + other

    #   def __iadd__(self, other):
    #       mark = self._tag_add(other)
    #       if isinstance(other, Path):
    #           other = other._data
    #       if len(other) > 0:
    #           self._mark = mark
    #           self._data.extend(other)
    #       return self

    def __truediv__(self, other):
        if isinstance(other, Path):
            raise TypeError("You want + not /")
        return Path(*self._data, other, mark=self.mark)

    #   def __itruediv__(self, other):
    #       if isinstance(other, Path):
    #           raise TypeError("You want + not /")
    #       self._data.append(other)

    # TODO add alternate output with hex integers

    def __repr__(self):
        return f"P({str(self)!r})"

    @classmethod
    def from_str(cls, path, *, mark="", scan=False):
        """
        Constructor to build a Path from its string representation.
        """
        res = []
        part: None | bool | str = False
        # non-empty string: accept colon-eval or dot (inline)
        # True: require dot or colon-eval (after :t)
        # False: accept only colon-eval (start)
        # None: accept neither (after dot)

        esc: bool = False
        # marks that an escape char has been seen

        eval_: bool | int = False
        # marks whether the current input shall be evaluated;
        # 2=it's a hex number

        pos = 0
        if isinstance(path, (tuple, list)):
            return cls.build(path, mark=mark)
        if path == ":":
            return cls(mark=mark)

        mp = _RTagRE.match(path)
        if mp:
            if not mark:
                mark = mp[0][2:-1]
            elif mark != mp[0][2:-1]:
                raise SyntaxError(f"Conflicting tags: {mark} vs. {mp[0][2:-1]}")
            return cls(mark=mark)

        def add(x):
            nonlocal part
            if not isinstance(part, str):
                part = ""
            try:
                part += x
            except TypeError:
                raise SyntaxError(f"Cannot add {x!r} at {pos}") from None

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
                        elif eval_ == -3:
                            part = b64decode(part.encode("ascii"))
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
                elif e in "z?":
                    new(NotGiven, True)
                elif e == "e":
                    new("", True)
                elif e == "t":
                    new(True, True)
                elif e == "f":
                    new(False, True)
                elif e[0] == "m" and len(e) > 1:
                    done(None)
                    if not mark:
                        mark = e[1:]
                    elif mark != e[1:]:
                        raise SyntaxError(f"Conflicting tags: {mark} vs. {e[1:]} at {pos}")
                    part = True
                elif e == "n":
                    new(None, True)
                elif e in _Roots:
                    new(_Roots[e], True)
                elif e == "_":
                    add(" ")
                elif e[0] == "i":
                    done(None)
                    part = e[1:]
                    eval_ = 1
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
                elif e[0] == "s":
                    done(None)
                    part = e[1:]
                    eval_ = -3
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
        return cls(*res, mark=mark, scan=scan)

    @classmethod
    def from_slashed(cls, path, *, mark=None, scan=True):
        """
        Constructor to build a Path from its slashed string representation.
        """

        res = []

        if isinstance(path, (tuple, list)):
            return cls.build(path, mark=mark)

        def _decol(s):
            s = s.replace(":|", "/").replace(":_", " ")
            s = s.replace(":h", "#").replace(":p", "+")
            return s.replace("::", ":")  # must be last

        marks = 0

        try:
            for pos, p in enumerate(path.split("/")):
                if p == "":
                    res.append("")
                elif p[0] != ":":
                    res.append(_decol(p))
                elif p == ":":
                    pass

                elif p[1] in (":","h","p"):
                    res.append(_decol(p))
                elif p[1] == "b":
                    res.append(int(p[2:], 2))
                elif p[1] == "e":
                    pass
                elif p[1] == "f":
                    if len(p) == 2:
                        res.append(False)
                elif p[1] == "i":
                    res.append(int(p[2:]))
                elif p[1] == "m":
                    if mark is None or mark == p[2:]:
                        mark = p[2:]
                        marks += 1
                elif p[1] == "n":
                    if len(p) == 2:
                        res.append(None)
                elif p[1] == "s":
                    res.append(b64decode(_decol(p[2:]).encode("ascii")))
                elif p[1] == "t":
                    if len(p) == 2:
                        res.append(True)
                elif p[1] == "v":
                    res.append(_decol(p[2:]).encode("ascii"))
                elif p[1] == "x":
                    res.append(int(p[2:], 16))
                elif p[1] == "y":
                    res.append(bytes.fromhex(p[2:]))

                else:
                    res.append(path_eval(p[1:]))

                if len(res) != pos + 1 - marks:
                    raise RuntimeError("Slashed-Path syntax")

        except Exception as exc:
            raise SyntaxError(f"Cannot eval {path!r}, part {pos + 1}") from exc

        if mark is None:
            mark = ""
        r = cls(*res, mark=mark, scan=scan)
        return r

    @classmethod
    def _make(cls, loader, node):
        value = loader.construct_scalar(node)
        return cls.from_str(value)


    def apply(self, path:Path) -> Path:
        """
        Construct a new path that replaces pattern tuples in @path with
        the referred-to entries in @self.

        @path is returned unchanged if @self doesn't contain any patterns.

        Thus:

        >>> p = Path("w.x.y.z")
        >>> P("a:2,.b").apply(p)
        P("a.x.b")
        >>> P("a:3,4.b").apply(p)
        P("a.y.z.b")

        Elements are numbered starting from 1 (left) or -1 (right).
        """
        if not any(isinstance(x,tuple) for x in self._data):
            return self

        # We might want to cache this …
        res = []
        for p in self._data:
            if not isinstance(p,tuple) or len(p) not in (1,2,3):
                res.append(p)
                continue

            p = list(p)
            if p[0] > 0:
                p[0] -= 1
            if len(p) == 1:
                res.append(path[p[0]])
            else:
                if p[1] < 0:
                    p[1] += 1
                    if p[1] == 0:  # was: -1
                        p[1] = None
                res.extend(path[slice(*p)])
        return Path.build(res)


class P(Path):
    """
    A Path subclass that delegates to `Path.from_str`.

    For idempotency (required by ``click``) it transparently accepts `Path`
    objects.

    Scanning for prefixes is disabled. Use this class for paths embedded in
    MoaT code.
    """

    def __new__(cls, path, *, mark="", scan=False):  # noqa:D102
        if isinstance(path, Path):
            if path.mark != mark:
                path = Path(*path, mark=mark, scan=scan)
            return path
        return Path.from_str(path, mark=mark, scan=scan)


class PP(Path):
    """
    A Path subclass that delegates to `Path.from_str`.

    This is identical to `P` except that scanning for prefixes is enabled.
    Use this class for command-line processing.
    """

    def __new__(cls, path, *, mark="", scan=True):
        if isinstance(path, Path):
            if path.mark != mark:
                path = Path(*path, mark=mark, scan=scan)
            return path
        return Path.from_str(path, mark=mark, scan=scan)


class PS(Path):
    """
    A Path subclass that delegates to `Path.from_path`.

    For idempotency (required by ``click``) it transparently accepts `Path`
    objects.
    """

    def __new__(cls, path, *, mark=""):  # noqa:D102
        if isinstance(path, Path):
            if path.mark != mark:
                path = Path(*path, mark=mark)
            return path
        return Path.from_slashed(path, mark=mark, scan=True)


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
        foo.:.a.b foo.a.b
        bar       foo.at.bar
        bar.c.d   foo.at.bar.c.d

    All elements in the path should be strings with no leading or trailing
    dot, though the first element may start with a dot or be None.

    """
    this = __name__.split(".", 1)[0]
    if len(path) == 0:
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
        p += "." + ".".join(str(x) or "-" for x in path[1:])
    p = p.replace("..", ".")
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
        a j k

    is shortened to

        0 a b
        2 c d
        3 e f
        4 g h
        3 i
        1 j k

    Usage::

        >>> d = PathShortener()
        >>> d.short(P('a.b.c.d'))
        (4, ('a','b',c','d'))
        >>> d.short(P('a.b.c.e.f'))
        (3, ('e','f'))
        {'depth':1, 'path':['e','f']}

    Alternate, somewhat-deprecated usage::
        >>> d = PathShortener(['a','b'])
        >>> d({'path': 'a b c d'.split})
        {'depth':0, 'path':['c','d']}
        >>> d({'path': 'a b c e f'.split})
        {'depth':1, 'path':['e','f']}

    Note that the input dict in the second example is modified in-place.

    Using a prefix is deprecated.

    Caution: this shortener ignores path marks.
    """

    def __init__(self, prefix:Path|list|tuple=Path()):  # noqa:B008
        self.prefix = prefix if isinstance(prefix,Path) else Path.build(prefix)
        self.depth = len(prefix)
        self.path = []

    def short(self, p: Path) -> tuple[int, Path]:
        """shortens the given path"""
        if self.depth and list(p[: self.depth]) != list(self.prefix):
            raise RuntimeError(f"Wrong prefix: has {p!r}, want {self.prefix!r}")

        p = p[self.depth :]
        cdepth = min(len(p), len(self.path))
        for i in range(cdepth):
            if p[i] != self.path[i]:
                cdepth = i
                break
        self.path = p
        return cdepth, p[cdepth:]

    def __call__(self, res: dict):
        "shortens the 'path' element in @res"
        try:
            p = res["path"]
        except KeyError:
            return
        cdepth, p = self.short(p)
        res["path"] = p
        res["depth"] = cdepth
        return res


class PathLongener:
    """
    This reverts the operation of a PathShortener. You need to pass the
    same prefix in.

    Calling a PathLongener with a dict without ``depth`` or ``path``
    attributes is a no-op.

    Using a prefix is deprecated.

    Caution: this longener ignores path marks.
    """

    cls = Path

    def __init__(self, prefix: Path | tuple | list = ()):
        if isinstance(prefix, Path):
            self.cls = type(prefix)
            prefix = prefix.raw
        elif isinstance(prefix,list):
            prefix=tuple(prefix)
        self.depth = len(prefix)
        self.path = prefix

    def long(self, d: int | None, p: Path):
        """Expand a given path suffix"""
        p = tuple(p)
        if d is None:
            return p
        p = self.cls.build(self.path[: self.depth + d] + p)
        self.path = p
        return p

    def __call__(self, res):
        "expands the 'path' element in @res"
        p = res.get("path", None)
        if p is None:
            return
        d = res.pop("depth", None)
        if d is None:
            return
        res["path"] = self.long(d, p)
        return res


# path_eval is a simple "eval" replacement to implement resolving
# expressions in paths. While it can be used for math, its primary function
# is to process tuples.
_eval = simpleeval.SimpleEval(functions={})
_eval.nodes[ast.Tuple] = lambda node: tuple(
    _eval._eval(x)  # noqa:SLF001
    for x in node.elts
)
path_eval = _eval.eval


# Here we declare our bunch of "root" variables.

Root = ContextVar[Path|None]("Root", default=None)


class RootPath(Path):
    """
    Wraps access to a contextvar that points to a Path.

    The problem is that the contextvar's ID is not stable. However proxying
    it must be consistent regardless of its content.
    """

    _mark = ""

    def __init__(self, key, var, name):
        self._key = key
        self._var = var
        self._name = name

    @property
    def name(self):
        "name"
        return self._name

    @property
    def key(self):
        "name of the contextvar"
        return self._key

    def __bool__(self):
        "check if the contextvar is set"
        p = self._var.get()
        return p is not None

    @property
    def _data(self):
        p = self._var.get()
        if p is None:
            return None
        return self._var.get()._data  # noqa:SLF001


_root = RootPath("R", Root, "Root")
as_proxy("R", _root)
_Roots = {"R": _root}

for _idx in "SPQ":  # and R. Yes I know.
    _name = f"{_idx}_Root"
    _ctx = ContextVar(_name, default=None)
    _path = RootPath(_idx, _ctx, _name)
    _ctx.set(Path("XXX",_idx,"XXX"))

    globals()[_name] = _ctx
    __all__ += [_name]  # noqa:PLE0604

    _Roots[_idx] = _path
    as_proxy(f"_P{_idx}", _path)

del _idx, _name, _ctx, _path
