CBOR Tags
=========

The MoaT software uses the following CBOR tags.

The author presumes that the proposed tag 203 is generally useful
beyond the confines of this specification and has submitted them to IANA.


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

MoaT assumes a Proxy (referencing the class of the object in question) as
the array's first entry; tag 203 MAY be omitted.

The remaining array elements mirror Python's object serialization scheme:
an array of positional arguments, a map of key/value arguments, an array of
items to add/append to the object, and a map of attributes to set. Trailing
elements may be omitted if empty.


Path
----

    =============== =============================
    Tag             39
    Data Item       array
    Semantics       Identifier (object access)
    Reference       https://github.com/lucas-clemente/cbor-specs/blob/master/id.md
    Contact         Lucas_Clemente
    =============== =============================

In the context of MoaT, this tag is used with arrays to tag a path to an
object. See :ref:`common/path` for details.

In the context of CBOR, a Path is a sequence of object accessors, i.e. a
way to reference a possibly-deeply nested object. Path elements typically
include text strings (object members, map keys) and non-negative integers
(array indices).

A recipient can use this tag to distinguish a sequence of lookups from
a tuple that's directly used as a map key. (Languages like Python allow this.)

While the array SHOULD consist of ASCII text strings and non-negative
integers, Applications MAY use additional data types or values.

Applications that generate paths to an object MUST do so in a consistent
manner. Paths that refer to an object without conforming to the chosen
scheme (e.g. negative array indices that count from the array's end) MAY be
rejected.



Object Proxy
------------

    =============== =============================
    Tag             32769
    Data Item       text string, integer, array
    Semantics       reference a well-known or unencodable object
    Reference       https://gitlab.com/Hawk777/cbor-specs/-/blob/main/external-reference.md
    Contact         Christopher_Head
    =============== =============================

This tag is specified as "external object reference". In MoaT it is used
as an object proxy, in two different but related ways.

MoaT pre-defines some proxy objects, mainly for classes whose instances can
be serialized safely. This includes some Python exceptions. These consist
of a simple string.

Other proxies may refer to an object that cannot (or, perhaps due to its
size, should not) be encoded in CBOR. A sender caches such an object and
send a proxy instead of throwing an error. The recipient can subsequently
refer to this object using the Proxy tag when it sends another message
back.

Auto-generated proxies consist of two elements. The first identifies
the system that created the proxy; the second is a unique integer.

Details, and an API to release auto-generated proxies, are on the TODO list.



CBOR Sequence
-------------

    =============== =============================
    Tag             55800
    Data Item       array
    Semantics       Labeled CBOR Sequence
    Reference       https://www.rfc-editor.org/rfc/rfc9277.html
    Contact
    =============== =============================


This tag marks files that contain CBOR data items. In the context of this
specification, its contents are always tagged with 1299145044, described
below.


File Identifier
---------------

    =============== =============================
    Tag             1299145044
    Data Item       array
    Semantics       MoaT file identifier / details
    Reference       https://github.com/M-o-a-T/moat/blob/main/doc/common/cbor.rst
    Contact         Matthias Urlichs <matthias@urlichs.de>
    =============== =============================

Files with MoaT-compatible messages start with an array that is wrapped with
tag 1299145044 (0x4d6f6154, "MoaT"), inside tag 55800 (CBOR).

The array has two elements. The first contains a text string that describes the
file's contents. This string MUST be at least 24 bytes long (pad with spaces
if necessary), for the benefit of the "file" utility. It is free-format,
meant to be shown to humans, and MUST be ignored by programs that read the
file.

The second array member is a map that describes the file. Programs that read
it should use the map's contents to determine how to interpret it, or
to extract metadata (e.g. range of record, file creation date, etc.).

This way, ``file`` can show basic data about the file, using these magic entries:

.. code-block::

    0        string/3b  \xd9\xd9\xf7     CBOR
    >3       string/5b  \xdaMoaT         MoaT file
    >>8      string/2b  \x82\x78
    >>>10    pstring    >\0              %s
    >>8      string/2b  \x82\x79
    >>>10    pstring/H  >\0              %s

Shorter descriptive strings would require 24 additional entries in ``file``'s
magic pattern file (as it cannot mask the high bits of a string's length
field), which seems excessive.

Change of status marker
-----------------------

    =============== =============================
    Tag             1298360423
    Data Item       map
    Semantics       MoaT change-of-status marker
    Reference       https://github.com/M-o-a-T/moat/blob/main/doc/common/cbor.rst
    Contact         Matthias Urlichs <matthias@urlichs.de>
    =============== =============================

This tag ("Mchg") marks a status change in a MoaT message stream.

It is used to note that e.g. an initial state dump is complete, or that the
switch-over to a new file stream has started.


End of file marker
------------------

    =============== =============================
    Tag             1298493254
    Data Item       map
    Semantics       MoaT end-of-file marker
    Reference       https://github.com/M-o-a-T/moat/blob/main/doc/common/cbor.rst
    Contact         Matthias Urlichs <matthias@urlichs.de>
    =============== =============================

This tag ("MeoF") is the last tag written to a file before it's closed. Its
content describes e.g. why the file has ended (timeout, interrupt, restart …)
and which file will continue the content (if applicable).

When this tag is not the last CBOR data item in a file, it MUST be followed
with a tag 55799+1299145044 with matching continuation IDs ("cont") in its
map part. MoaT uses this element to verify that multiple files have been
concatenated correctly.
