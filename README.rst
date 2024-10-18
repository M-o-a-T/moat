====================
Utilities for Python
====================

This is a Python "util" submodule with code that I habitually use in so
many projects that I decided to split it off into its own git archive.

Feel free to extend and embrace. Patches welcome.


Features
========

A few. Read the code and the subpackages' documentation; I didn't get
around to documenting all of that yet.


License
=======

No restrictions. CC0 / public domain / MIT / GPLv3 / whatever, as long as
you don't want anybody (i.e. the author(s)) to pay for the effects of any
bugs, features or "features" which this code might or might not have.

Please contribute any enhancements.


Dependencies
============

A few. Notable:

* anyio, version 3. Required for `ValueEvent`, `spawn` (obviously) and
  `as_service`.

* ruyaml. This is a fork of ruamel.yaml which is a fork of pyyaml.
  Fixes some bugs and has a more reasonable API. Required for
  `yload`/`yprint`/`yformat`.

* msgpack, obviously required for `pack`/`unpack` and `MsgReader`/`MsgWriter`.

* asyncclick, required for `main_`/`wrap_main`.

MoaT does not depend on:

* cbor2. Our implementation is shared with a version running on
  MicroPython and thus needs to be minimal. Also we want to support
  efficient async streaming.


CBOR Tags
=========

This package uses the following CBOR tags. The author assumes that they're
generally useful beyond the confines of this specification.

Path
----

    =============== =============================
    Tag             202
    Data Item       array
    Semantics       mark array as object path
    Reference       https://github.com/M-o-a-T/moat-util/
    Contact         Matthias Urlichs <matthias@urlichs.de>
    =============== =============================

A Path is a list of object accessors, i.e. a way to reference a
possibly-deeply nested object. These typically include strings
(object members) and numbers (array indices).

The array SHOULD include only strings and non-negative numbers.
The list of allowed characters in the string is application dependent.

Object Proxy
------------

    =============== =============================
    Tag             203
    Data Item       string, integer, array
    Semantics       reference a well-known or unencodable object
    Reference       https://github.com/M-o-a-T/moat-util/
    Contact         Matthias Urlichs <matthias@urlichs.de>
    =============== =============================

A Proxy refers to an object that cannot be encoded. Rather than throw an
encoding error, the sender may cache the object and replace it with a proxy
which the recipient can subsequently use to refer to it.

When the proxy's content is an array, it SHOULD consist of two elements:
a string that uniquely identifies the origin of the proxy object, and a
string or integer which said originator can use to recover the original.

An API to release auto-generated proxies is recommended but out of scope of
this specification.

An implementation MAY use well-known names to refer e.g. to types that can
be used to construct objects.

Object Constructor
------------------

    =============== =============================
    Tag             27
    Data Item       array
    Semantics       build an object from a class
    Reference       http://cbor.schmorp.de/generic-object
    Contact         Marc A. Lehmann
    =============== =============================

This tag is already specified and included here for MoaT-specific usage
details.

MoaT assumes a Proxy reference as the contained array's first member.
The decoder treats it as if tagged with 203.

MoaT uses three-element arrays: the class name or proxy, an array of
positional arguments, and a map of key/value arguments. Trailing members
may be omitted if empty.
