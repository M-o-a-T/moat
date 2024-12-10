=======================
MoaT data serialization
=======================

MoaT messages are serialized via MsgPack or CBOR.

MsgPack is the original method; its main advantage is that all ASCII data
self-encode to small integers, and thus interleaving messages with normal
console output "just works".

CBOR is newer and not universally supported yet.

The advantage of CBOR is that it has a rich and streamable tagging
mechanism, while MsgPack's extensions are limited and the data in them
cannot be streamed.

MsgPack extensions
==================

Bignums
-------

Extension 2, encoded as a big-endian bytestream.

Paths
-----

Extension 3. The data consists of the encoded path elemnts, concatenated.

Types
-----

A type is encoded as extension 4; the name is UTF-8 encoded and stored in
the extension data.


Objects
-------

Objects are encoded as extension 5. The data is a concatenation of the
(string) encoding of the type's name and the items resulting from calling
``__getstate__`` on it.


CBOR tags
=========

CBOR already has tags for bignums.

The rest is TBD.


Type and object names
=====================

Type and object names are not transmitted directly.

When sending, either the object itself or its type must be an existing
proxy. If no proxy exists, one is created on the fly. The receiver is
responsible for its eventual de-allocation.

Commands that return proxies must be documented.

Well-known proxies
------------------

All well-known proxy names start with an underscore, as a mark that they
cannot be unproxy-ed.

_
..
The NotGiven singleton.

This object is used in some places to signal that there is (or should be)
no value, as opposed to a value that happens to be `None`.

It is never returned as a stand-in for `AttributeError` or `KeyError`.

_FnErr
......

FileNotFoundError.

Exists only if the "fs" app is used.

_FxErr
......

FileExistsError.

Exists only if the "fs" app is used.

_KyErr
......

KeyError.

_AtErr
......

AttributeError.

_NiErr
......

NotImplementedError.


