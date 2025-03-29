"""
A hacked-up copy of some parts of `moat.util`.
"""

from __future__ import annotations

import re

_PartRE = re.compile("[^:._]+|_|:|\\.")


def P(s):
    return Path.from_str(s)


class Path(tuple):  # noqa:SLOT001
    """
    somewhat-dummy Path

    half-assed string analysis, somewhat-broken output for non-basics
    """

    def __str__(self):
        def _escol(x):
            x = x.replace(":", "::").replace(".", ":.").replace(" ", ":_")
            return x

        res = []
        if not len(self):
            res.append(":")
        for x in self:
            if isinstance(x, str):
                if x == "":
                    res.append(":e")
                else:
                    if res:
                        res.append(".")
                    res.append(_escol(x))
            elif x is True:
                res.append(":t")
            elif x is False:
                res.append(":f")
            elif x is None:
                res.append(":n")
            elif isinstance(x, (bytes, bytearray, memoryview)):
                if all(32 <= b < 127 for b in x):
                    res.append(":v" + _escol(x.decode("ascii")))
                else:
                    from base64 import b64encode

                    res.append(":s" + b64encode(x).decode("ascii"))
                    # no hex
            else:
                res.append(":" + _escol(repr(x)))
        return "".join(res)

    @classmethod
    def from_str(cls, path):
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
            return cls(path)
        if path == ":":
            return cls()

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
                            raise SyntaxError("Generic eval is not supported: {part !r}")
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

        def err():
            nonlocal path, pos
            raise SyntaxError(f"Cannot parse {path!r} at {pos}")

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
                elif e[0] == "s":
                    done(None)
                    part = e[1:]
                    eval_ = -3
                else:
                    if part is None:
                        err()
                    done("")
                    add(e)
                    eval_ = True
            else:
                if e == ".":
                    if part is None or part is False:
                        err()
                    done(None)
                    pos += 1
                    continue
                elif e == ":":
                    esc = True
                    pos += 1
                    continue
                elif part is True:
                    raise Err(path, pos)
                else:
                    add(e)
            pos += len(e)
        if esc or part is None:
            err()
        done(None)
        return cls(res)

    def __repr__(self):
        return f"P({str(self)!r})"

    def __truediv__(self, x):
        return Path(self + (x,))

    def __add__(self, x):
        return Path(tuple(self) + x)
