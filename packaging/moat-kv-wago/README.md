# Moat-KV-Wago

.. start synopsis

MoaT-KV-Wago is a link between old Linux-based WAGO controllers and MoaT-KV.

.. end synopsis

It will

- add all discovered wago ports
- monitor inputs as specified
- write values that it reads from them to some MoaT-KV entry
- monitor a MoaT-KV entry and write any updates to wago
- work with MoaT-KV's runner system, either centrally or distributed
