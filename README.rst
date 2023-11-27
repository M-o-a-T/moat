===========
MoaT-KV-KNX
===========

MoaT-KV-KNX is a link between KNX buses and MoaT-KV.

It will

* query and monitor inputs as specified

* write values that it reads from them to some entry in MoaT-KV

* monitor a MoaT-KV entry and write any updates to KNX

* work with MoaT-KV's runner system, either centrally or distributed


Warning
=======

Currently this will only work with MoaT's fork of XKNX because we're using
AnyIO and some other improvements.
