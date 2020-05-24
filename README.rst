========
DistGPIO
========

DistGPIO is a link between GPIO pins and DistKV.

It will

* monitor inputs as specified

* write values that it reads from them to some DistKV entry

* monitor a DistKV entry and write any updates to GPIO

* work with DistKV's runner system, either centrally or distributed
