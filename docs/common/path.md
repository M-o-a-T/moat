# MoaT Paths

## Overview

Loosely speaking, a path is a way to go from object A to object B
by way of a series of attribute or index lookups.

In MoaT, a path may contain strings, integers, floats, bytestrings,
constants (`True`, `False`, `None`), or tuples of any of the above,
recursively.

Important: a MoaT path is not a series of strings (`123` is not `"123"`,
just as in Python), an empty element is distinct from no element (unlike a
file system path where `a//b` is the same thing as `a/b`), and there are no
disallowed characters — unlike file paths (`/` cannot be part of a file name)
or MQTT topics (no `+` allowed).

MoaT uses Paths as accessors for data, MoaT-Link remote commands, MQTT data,
and probably some others.

## Examples

- `foo.42.bar`
  A path consisting of three strings.

- `foo:42.bar`
  A path consisting of a string, an integer, and another string.

- `foo:.42.bar`
  A path consisting of the strings `foo.42` and `bar`.

- `foo:42:.5.bar`
  A path consisting of a string, the floating-point number `42.5`, and
  another string.

- `:`
  The empty path.

## Syntax

### Separator: Dot

The canonical separator for MoaT path elements is a dot.

* It's easier to type than a slash on many non-QWERTY keyboard layouts

* It's used in domain names, members of Python objects, importing modules,
  et al..

* Particularly when using fixed-width fonts, it affords the most visual
  separation between path elements (except for a space, which we can't use
  because you'd need a ton of shell quoting whenever a path is used in a
  command line argument).


### Escape: Colon

The MoaT Path's escape character, as in "the following is somehow special",
is a colon.

We choose not to use the traditional backslash for two reasons.

* Typing a backslash is somewhat annoying on many non-US-QWERTY keyboard layouts.

* It tends to proliferate. A backslash in strings or shell command lines requires
  another backslash to escape it. This quickly becomes unwieldy.

Also, a backslash traditionally escapes the next character. The problem is
that our paths do not consist solely of characters. Since semantically a
string consisting of two letters and a `None` does not make sense, MoaT
re-purposes the colon as a path separator if the element escaped by it is
not a string, thus removing some visual clutter. Backslashes, as used
traditionally, are a bad fit for this.

### Some Examples

* a.b
  A path element 'a' followed by a path element 'b'.

* a.b.c
  'a' and 'b' and 'c'.

* a:.b.c
  'a.b' and 'c'.

* a.b::c
  'a' and 'b:c'.

* a
  A single-element path.

* a/b
  Another single-element path.

* :
  An empty path.

* :e
  A single-element path consisting of an empty string.

* a.123.b
  'a' plus '123' (a 3-character string) plus 'b'.

* a:123.b
  'a' plus 123 (an integer number) plus 'b'.

* a:123:.5.b
  'a' plus 123.5 (a floating-point number) plus 'b'.

  Floats are not typically used in paths, so escaping the dot with a colon
  seems like an acceptable compromise.

* a."123".b
  'a' plus '"123"' (a 5-character string, i.e. including the quotes) plus 'b'.

* :t
  A one-element path whose only element is the bool constant `True`.

* :t:f:n
  A path consisting of `True`, `False`, and `None`.


### Slashes

The file system and MQTT want slashes as separators. MoaT supports these
use cases with an alternate syntax that uses slashes instead of dots.
The colon is still interpreted as before.

MoaT optionally escapes `+` and `#`, as these cannot appear as elements
of MQTT topics.

Thus the above paths are, in slash notation,

* a/b
* a/b/c
* a.b/c
* a/b::c
* a
* a:|b
* /
* :e
* a/123/b
* a/:123/b
* a/:123.5/b
* a/"123"/b
* :t
* :t/:f/:n

## Roots

A file system path or a MQTT topic has a single root. However, MoaT is
designed to be a multi-homed system.

Thus, the configuration contains a "link.root" element that is used as the
standard prefix. MoaT reserves `:S`, `:P`, `:Q` and `:R` as "rooted-path"
markers (dot notation). These marks may only appear at the beginning of a path.

Ths slash notation does not have root placeholders, as the file system or
MQTT don't know about them. Instead, they are expanded when generating the
path's slashed representation. When the slashed path is parsed, root
prefixes are recognized and re-applied.


## Encoding details

### Inline escapes

These encode single characters and do not start a new path element.

    ::  escapes : colon

    :.  escapes . dot   (dot-path only)

    :|  escapes / slash (slash-path only)
    :h  escapes # hash  (slash-path only, MQTT)
    :p  escapes + plus  (slash-path only, MQTT)

    :=  escapes + plus  (dot-path parsing only)
    :_  escapes   space (dot-path only)
    :%  escapes \ backslash (parsing only)
    :!  escapes | pipe/bar (parsing only)

.. note::
    You might wonder why there is a distinct escape for a "plus" in dot
    paths. The reason is that the MoaT argument parser uses a single plus
    as a convenient shortcut for "append the following to the argument list
    of this command". The `:=` escape is thus required for the
    much-less-common case of a path that consists of a single element `"+"`.

    The other parsing-only escapes are useful for input to shell prompts
    et al., when you don't want to deal with (possibly multi-layered) quoting.
    They are (currently) not generated when printing a path.

### Separator escapes

In dot notation the following escapes start a new element.
In slash notation they must be delimited by slashes.

    :t   True
    :f   False
    :e   empty string
    :n   None
    :z   Ellipsis / NotGiven
    :?   Error, reference to a variable that's not set
            (will parse as NotGiven, for round-trip type safety)

    :S   Some application-specific root path
    :P   Another application-specific root path
    :Q   Yet another application-specific root path
    :R   The global MoaT root path
    :xAB Hex integer
    :b01 Binary integer
    :vXY Bytestring, inline
    :yAB Bytestring, hex encoding
    :sAB Bytestring, base64 encoding
    :iXY evaluate XY as a Python expression.
            The 'i' ("interpret") may be omitted if XY starts with a digit,
            minus, or open parenthesis (for tuples).

## Errors

### Dot notation

* A leading or trailing dot

* A trailing colon, except `:` which denotes an empty path

* A sequence of two dots, or a dot and a separator escape

* A separator escape that's not followed by a dot, another separator escape,
  or the end of the path

### Slash notation

* Any separator-escaped sequence that is not delimited by slashes
  (or the start / end of the path)

* A leading or trailing slash, except `/` which denotes an empty path
