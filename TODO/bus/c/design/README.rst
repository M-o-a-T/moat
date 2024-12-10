Design tools
============

This directory contains two C programs which I used to test CRC algorithms.

In particular, these programs proved that running a CRC algorithm on the
decoded bus messages does not work: it cannot recognize all two-bit errors
and might even get fooled by a single one-bit error. Owch.

