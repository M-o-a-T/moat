========
DistOWFS
========

DistOWFS is a link between 1wire and DistKV.

It will

* add all discovered 1wire devices

* poll these devices as specified

* write values that it reads from 1wire to some DistKV entry

* monitor a DistKV entry and write any updates to 1wire

* work with DistKV's runner system, either centrally or distributed
