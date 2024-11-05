======================
The MoaT-Codec library
======================

This library packages various codecs used for MoaT protocols
in a way that's reason- and stream-able.

Interface
+++++++++

Codec
-----

* encode(obj)

  Encode the object to a bytestream.

* decode(bytes)

  Decode the given bytes to a single object.

* feed(bytes, final=False)

  Data stream. Returns an array of objects.

  This method only exists when a sequence of encoded objects can be streamed,
  i.e. contains built-in message boundaries.

  if @final is ``True``, raise an exception if there is an incomplete
  object in the buffer after this call.

* getstate(), setstate(\*args)

  A streaming decoder may store partially-decoded state (unprocessed
  buffer) here.

The list of accepted objects is implementation dependent.

Extension
---------

Extension types vary by whether they carry binary data as in (msgpack), or
objects (as in cbor).

* binary (classvar): True if msgpack-style, False if cbor-style

* encode(type, key, encoder)

  Encode an object ``obj`` of type ``type``. ``encoder(codec, obj)`` must return
  a bytestring / an encodeable object.

* decode(key, decoder)

  Decode (key, data) to an object. ``decoder(codec, data)`` is called with a
  bytestring / a decoded object, and returns the resulting object.

Extensions get the codec as their first argument. They can use it to store
data, e.g. references.

