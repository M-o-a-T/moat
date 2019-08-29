========
DistWAGO
========

DistWAGO is a link between WAGO controllers and DistKV.

It will

* add all discovered wago ports

* monitor inputs as specified

* write values that it reads from them to some DistKV entry

* monitor a DistKV entry and write any updates to wago

* work with DistKV's runner system, either centrally or distributed
