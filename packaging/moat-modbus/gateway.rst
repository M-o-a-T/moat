=======
Gateway
=======

++++++++
Synopsis
++++++++

``moat modbus dev poll ‹config›.yaml`` starts a multi-port Modbus client or server
which gateways bidirectionally to MQTT or MoaT-KV storage.

The configuration file supports a structured register definition file with limited
support for macro expansion.

+++++++++++++++++++++
Config File structure
+++++++++++++++++++++

Servers
+++++++

The ``server`` tag contains a list of server entries.

TCP servers
-----------

Use "host" and "port" tags to specify which port to listen to. The port, if given,
must be an integer.

RTU servers
-----------

Use the "port" tag to specify the serial port, and the "serial" tag to specify
the baud rate etc. See the Python module `serial` for details.

Units Served
------------

Add a "units" tag.

Example::

    server:


Clients
+++++++

Metacommands
++++++++++++

include
-------

Includes another YAML file. The file is decoded and its data structure is added
in place of the ``include`` statement. You should not add other data::

    foo:
      include: some/file.yaml
      bar: baz

      is undefined.

Content: a file name.

ref
---

Replicates the referenced structure. Colliding items are merged recursively.

Example::

    foo:
      one:
        two: three
        four: five
    bar:
      ref: foo.one
      two: six
      five: ten

results in this data structure::

    foo: …
    bar:
      ref: foo.one
      two: six
      four: five
      five: ten

Content: a MoaT path (though the !P prefix is not used here) to the part you
want to reference, starting at the file's top level.

default
-------

The data structure below this tag is used for all the other tags at the same level,
recursively.

Example::

    foo:
      default:
        for:
          one: 42
      bar:
        baz: 99
      some:
        more:
          for:
            one: 41

results in::

    foo:
      default: …
      bar:
        baz: 99
        for:
          one: 42
      some:
        for:
          one: 42
        more:
          for:
            one: 41
            for:
              one: 42

This does result in far too many sub-items, but anything not used is ignored so that
does not matter.

repeat:
-------

The data strucure below this tag's ``data`` tag is replicated to several numeric tags,
applying an offset to any ``register`` tags found.

Example:

    foo:
      repeat: 3
      start: 4
      offset: 5
      data:
        bar:
          register: 100

results in ::

    foo:
      4:
        bar:
          register: 100
      5:
        bar:
          register: 105
      6:
        bar:
          register: 110

Any other data is preserved; you can override individual entries.
``repeat`` entries may be nested.

results in ::
