=======
DistKNX
=======

DistKNX is a link between KNX buses and DistKV.

It will

* query and monitor inputs as specified

* write values that it reads from them to some DistKV entry

* monitor a DistKV entry and write any updates to KNX

* work with DistKV's runner system, either centrally or distributed


Warning
=======

Currently this will only work with MoaT's fork of XKNX because we're using
AnyIO and some other improvements.
