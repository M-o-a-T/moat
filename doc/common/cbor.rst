CBOR Tags
=========

The MoaT software uses the following CBOR tags.

The author presumes that the proposed tags 202 and 203 are generally useful
beyond the confines of this specification and has submitted them to IANA.


Path
----

    =============== =============================
    Tag             202
    Data Item       array
    Semantics       mark array as object path
    Reference       https://github.com/M-o-a-T/moat/blob/main/doc/common/cbor.rst
    Contact         Matthias Urlichs <matthias@urlichs.de>
    =============== =============================

A Path is a sequence of object accessors, i.e. a way to reference a
possibly-deeply nested object. Path elements typically include text strings
(object members, map keys) and non-negative integers (array indices).

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
    Tag             203
    Data Item       text string, integer, array
    Semantics       reference a well-known or unencodable object
    Reference       https://github.com/M-o-a-T/moat/blob/main/doc/common/cbor.rst
    Contact         Matthias Urlichs <matthias@urlichs.de>
    =============== =============================

A Proxy refers to an object that cannot be encoded in CBOR. In a messaging
system, a sender may cache the object and replace it with a proxy instead
of throwing an error. The recipient can subsequently refer to the object
using the same Proxy tag when it sends a message back.

When the proxy's content is an array, it MUST consist of at least two
elements. The first is a text string, integer, or (if global uniqueness is
required) a UUID that uniquely identifies the origin of the proxy object.
The remainder of the array holds the data which the originator requires
in order to access or recover the original.

An API to release auto-generated proxies is recommended but out of scope of
this specification.

An implementation may pre-define some proxy objects, e.g. for classes whose
objects can be serialized safely. Attempts to release these predefined
references SHOULD be ignored.


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
tag 1299145044 (0x4d6f6154, "MoaT"), inside tag 55799 (CBOR).

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

