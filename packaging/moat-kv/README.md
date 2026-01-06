# MoaT-KV

Welcome to [MoaT-KV](https://github.com/MoaT/moat-kv)!

% start synopsis
% start main

MoaT-KV is a master-less distributed key-value storage system. It
circumvents the CAP theorem (you can't have all of consistency, availablilty,
and fault tolerance) using the assumption that a key is typically changed
by one node only. It is thus resistant to partitioning and intended to be
always-on; it will not block or lose updates, even in a partitioned
network.

% end synopsis

MoaT-KV comes with several batteries included:

- Basic user management, pattern-based ACLs
- Strong typing, code- and/or `JSON Schema`-based
- Data mangling
- Background code execution
- Seamless recovery even if only one master is running

The underlying communication is based on MQTT. A Serf back-end is also
available. Others are easy to implement.

MoaT-KV was originally called "distkv".

## API

MoaT-KV offers an efficient msgpack-based interface to access data and to
change internal settings. Most configuration is stored inside MoaT-KV
itself.

Stored data are **not** forced to be strings or binary sequences, but can
be anything that `MsgPack` supports. Keys to storage are multi-level and
support string, integer/float, and tuple keys.

## Status

MoaT-KV is in end-of-life. There are a lot of corner cases that don't
have tests. Critical bugs may be fixed, but "real" development continues
in `MoaT-Link`.

% end main

## Non-Features

MoaT-KV does not support data partitioning. Every node stores the whole
data set and can instantly deliver mostly-uptodate data.

MoaT-KV does not have a disk-based storage backend. Periodic snapshots and
event logs can be used to quickly restore a system, if necessary.

## TODO

- clean up some of the more egregious command line mistakes
- create a page for showcase-ing subprojects (knx owfs akumuli …)
- improve Home Assistant integration
