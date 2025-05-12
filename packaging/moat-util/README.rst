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

* asyncclick, required for `main_`/`wrap_main`.

* Optionally: msgpack.

MoaT does not depend on:

* cbor2. Our implementation is shared with a version running on
  MicroPython and thus needs to be minimal. Also, we want to support
  efficient async streaming.


CBOR tags
=========

see `ref:../common/cbor.rst`.


Paths
=====

MoaT uses `Path` objects as hierarchical object accessors.

A Path is a list of text strings and/or integers that identify an object or
subroutine. For instance, `moat.micro` may connect to an external node
named "ext" with three binary outputs, so you'd call ``"ext" -> 1 -> "set"
(True)`` to turn the second port on.

Since that's somewhat awkward, MoaT paths are typically entered and
displayed as single strings with dots as separators, ``ext:1.set`` in this
case. There's also a secondary representation that uses slashes (``ext/:1/set``)
for interfacing with the file system or MQTT.

See ``pydoc moat.util.path.Path`` for details.
