--------------
Moat-Link Data
--------------

MoaT-Link stores its data in a hierarchical tree. The MQTT top level
for structured MoaT-Link data is configured as ``link.root``. It **must
not** be empty.

Messages **must not** be sent with the Retain bit set unless specifically
mentioned here.

Data
++++

MoaT-Link entries are tuples with the following members:

* the actual data
* timestamp
* source
* …

The timestamp is seconds-in-UTC and may be a float or int.

The source is an identified for the (sub)system that originated the
message.

Layout
++++++

The MoaT-Link data store is organized into several functional top-level
hierarchies. They are described in the `doc/schema.yml` file (machine
readable), and in `doc/doc.yml` (for humans).

Both documents are loaded into MoaT-Link itself and also describe each
other.

doc
---

Documentation. Markdown text.

Any message in ``moat/#`` should have a corresponding entry in
``moat/doc/#``. Entries may be maps tagged by language code. Text is
interpreted as Markdown.

Documentation about MoaT command line usage is stored in ``moat.doc.shell``.


schema
------

JSON-Schema data.

Any message in ``moat/#`` should have a corresponding entry in
``moat/schema/#`` that describes its data structure.

The ``schema/_`` sub-hierarchy contains MoaT objects like `moat.util.Path`.


Message Metadata
++++++++++++++++

MoaT-Link messages should be accompanied with metadata as specified
in `schema/_/frame`. In MQTT the metadata is transmitted as an optional
user property named 'MoaT'.

Metadata are an array of strings separated by either periods or colons.
Dots mark a following string while colons signal that the next part is
encoded in CBOR and Base85/btoa. The last entry *may* be a map of free-form
extension data not covered by this specification.

Base85/btoa uses the alphabet ``0123456789`` ``ABCDEFGHIJKLMNOPQRSTUVWXYZ``
``abcdefghijklmnopqrstuvwxyz`` ``!#$%&()*+-;<=>?@^_`{|}~``.

The first member of this array always is a string, possibly empty. It
describes the origin of the message.

The second member is a float or integer, serving as a timestamp (standard
Unix time) and possibly tagged with CBOR Tag 1. A string *may* be used
instead; it *may* contain a time zone. If not, UTC is implied.

rcmd
----

Commands, except not packaged in a MoaT-Link array.

Used for Node-RED scripts.


rstate
------

State, except not packaged in a MoaT-Link array.

Used for Node-RED scripts.

The retention bit should be set.


Commands
++++++++

moat link doc
-------------

Print the documentation. Without arguments, prints this document. Otherwise
emits the text at the given path.

The ``--edit`` flag can be used to open a text editor, for updating.

The ``--list`` flag enumerates known subdocuments.

The ``--raw`` flag emits the current text without metadata. Combinded with
``--edit`` it also reads the new text from standard input.

