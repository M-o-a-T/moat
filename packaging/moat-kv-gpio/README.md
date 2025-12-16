# MoaT-kv-gpio

.. start synopsis

MoaT-kv-gpio is a link between GPIO pins and MoaT-kv.

.. end synopsis

It will

- monitor inputs as specified
- write values that it reads from them to some KV entry
- monitor a KV entry and write any updates to GPIO
- work with MoaT-KV's runner system, either centrally or distributed
