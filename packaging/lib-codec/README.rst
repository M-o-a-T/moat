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

* encoder(cls, key, fn)

  Encode an object ``obj`` of type ``type``. ``fn(codec, obj)`` must return
  a bytestring / an encodeable object. If the registration key is ``None``
  the function must return a tuple with the key as first element.

* decoder(key, fn)

  Add a decoder (key, data) to an object. ``fn(codec, data)`` is called with a
  bytestring / a decoded object, and returns whatever has been encoded.

Extensions get the codec as their first argument. They can use it to store
data, e.g. references. The extension object is available as ``codec.ext``.

