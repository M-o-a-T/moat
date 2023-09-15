==========================================
CBOR tags for mutable/immutable data items
==========================================

This document registers tags to declare a data item as immutable
(read-only) or mutable (read-write), respectively::

    Tag: 55 (immutable)
    Data Item: multiple
    Semantics: Immutable data item
    Point of contact: Matthias Urlichs <matthias@urlichs.de>
    Description of semantics: https://github.com/M-o-a-T/moat-micro/doc/cbor-readonly.rst

    Tag: 56 (mutable)
    Data Item: multiple
    Semantics: Mutable data item
    Point of contact: Matthias Urlichs <matthias@urlichs.de>
    Description of semantics: https://github.com/M-o-a-T/moat-micro/doc/cbor-readonly.rst

Abstract
========

Some CBOR data elements map to elements which are ambiguous in some
programming languages. Specifically, often one variant is immutable while
the other can be modified.

The tags documented here mark the tagged data item as immutable, resp. mutable.

Introduction
============

In some cases, the result of decoding the data item must be read-write or
read-only when by default it is not.

As an example, Python has two types for bytestrings – one is readonly
(``bytes``), the other is not (``bytearray``); the former is the "normal"
result of decoding a Type 2 object. The same problem occurs with
lists (``tuple`` / ``list``), only in reverse, as decoders typically
emits a list for Type 4 data items.

Object serialization in particular requires a way to distinguish between
these variants, preferably without forcing the user to implement
language-specific constructors for otherwise-universally-understood data
types.


Interaction with other tags
---------------------------

When data items are tagged with a mutable/immutable tag and some other tag,
the other tag SHOULD be covered by the mutable/immutable tag.

The rationale for this order is that the mutable/immutable tags also affect
data items that are not described by additional tags. An efficient decoder
thus needs to pass a "make this item mutable/immutable" argument to the
procedure that unwraps the corresponding data item.

Also, the specification for most tags explicitly states that the tag in
question applies to e.g. arrays. Interoperability might be impaired if
a decoder encounters an array wrapped in an 'immutable' tag, or an
immutable array, instead of the "plain" array it expects.


Detailed Semantics
==================

The 'mutable' and 'immutable' tags MAY precede any data item, though the
semantics of tagging numbers are undefined.

Indefinite lengths SHOULD NOT be used for data items that are tagged as
immutable.

The tags described in this document do not affect items nested within the
wrapped data item.

A map's keys are assumed to be immutable: maps are usually implemented
as hashed data, and the value of the hash cannot change. Thus they MUST
NOT be tagged as being mutable and SHOULD NOT be tagged as immutable.

The data types chosen by decoders when neither tag is present are, and
remain, implementation specific.


Examples
========

::
    D8 37     # tag (55, immutable)
     82       # array (2)
      D8 38   # tag (56, read-write)
       81     # array [1]
        01    # 1
      D8 38   # tag (56, read-write)
        81    # array [1]
         02   # 2

This sequence decodes to the Python data structure ``([1],[2])``, i.e. an
(immutable) tuple of two (mutable) one-element arrays.

::
    D8 38     # tag (56, mutable)
     04       # rational number
      82      # array (2)
       01     # 1
       03     # 3

This sequence marks a rational number as being modifyable in-place.

Security Considerations
=======================

The tags described in this document are designed to be used in object
serialization protocols and related applications. Non-vetted inputs
already can cause crashes or worse.

That being said, an object that's the mutable cousin of the immutable type
usually produced by a CBOR decoder, or vice versa, might be able to trigger
crashes when not vetted properly.

For example, in Python an immutable bytestring can be used as the key
to a map, while a mutable string causes an exception. Likewise, some tests
accept tuples as well as arrays, which could subsequently cause an
unexpected error if the decoding program tries to modify it during
further processing.

Thus, an implementation MAY choose to ignore these tags and process the
underlying data items as if the tags described in this document didn't
exist.

Author
======

Matthias Urlichs <matthias@urlichs.de>
