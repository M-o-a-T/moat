====================
Utilities for Python
====================

This is a Python "util" submodule with code that I habitually use in so
many projects that I decided to split it off into its own git archive.

This code is not a Python module. The idea is to add it as a submodule to
your own Python code::

   git submodule add git@github.com:smurfix/util-py.git src/your_module/util 

and then relative-import::

   from .util import attrdict

Feel free to extend and embrace. Patches welcome.


Features
========

A few. Read the code, I didn't get around to documenting all of that yet.

times
+++++

This code implements calculating an offset to an under-specified future
time. Like "how long until next Wednesday 8 am"?

The code also supports the inverse question, as in "how long until it's no
longer Wednesday 8 am".


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

