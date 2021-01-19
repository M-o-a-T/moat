================
Firmware updates
================

Devices on the MoaTbus are typically built into things, or even walls or
ceilings; removing them for the purpose of fixing a bug is an exercise we'd
all like to avoid.

Thus, the bus is able to update firmware.

Small controllers might not have enough space for two firmware copies. We
therefore add the ability to split the firmware into two parts: one is the
main system initialization, the bus handler, and the firmware updater
itself; this part is expected not to be updated frequently.
The other part is the device-specific code.

Firmware updates are split into 64-byte chunks (due to limited client RAM
and bus usage). They are transmitted consecutively and they are secured by
an overall 32-bit CRC. Also, individual chunks are secured by a 16-bit
checksum.

Messages contain a 4-bit type in the flag part of the control message (bit
4 is reserved) plus whatever content is required.

A checksum of zero indicates that the client is unable to read its own ROM
and thus can't sum up its firmware. A checksum of all-one states that there
is no (such) firmware. If legitimate checksumming results in either of
these values, the lowest bit shall be inverted.

If a client is not in boot mode, message 0 must be answered. All others
may be rejected.

Reply messages are addressed to the server that sent the request. Bit 4 of
the first byte is reserved (server>client) or an error (client>server).

Error messages echo the server's first byte except that bit 4 is set.
The second byte contains a max-64-byte length-1.
Its bit 7 is set if the error is fatal and the device is potentially no
longer useable. Bit 6 is set if the error cannot be recovered by simply
retrying, i.e. need to power cycle and/or connect to a hardware programmer.
The data after this are `length` bytes of error data, human readable.

All numbers are big-endian.

* 0
  Firmware checksum + version

  The server sends an otherwise-empty message.

  The client shall respond with the 32-bit checksum plus a firmware-defined
  version number or string (bytes, length variable but nonzero).
  If there is no current firmware or it could not be verified the CRC must
  be all-1.
  
* 1
  Bootloader version
  Return the boot loader magic and CRC (two 32-bit integers).

* 2, 3
  reserved

* 4
  Clear
  Sent by the server, requests the client to clear its firmware, preparing
  for uploading a new image. The message contains the boot loader CRC,
  application start address (in 64-byte blocks relative to the start of
  Flash memory) and the number of 64-byte blocks to be written.

  The client will check that there's room and that the start address is
  correct, erase the ROM which the firmware shall be written to, then reply
  with an otherwise-empty OK message.

* 5
  Clear Boot
  Clear space for a new bootloader upload. This typically destroys the
  existing non-boot firmware. Same parameters as in 4 except that the boot
  loaded CRC is missing.

* 6
  Send Block
  The server sends the 16-bit block number, a 16-bit checksum of
  ``src,dst,block#,data`` and the 64-byte block of data.

  The client writes the block to firmware and replies with an empty OK
  message.

  Blocks should be transmitted consecutively. They must be repeated if the ack
  is lost. There is no attempt at a windowed protocol because a CPU that's
  in the process of self-flashing is typically unresponsive.

  Block numbers start with zero, corresponding to the Flash header.

* 7
  Finish
  The server sends a 32-bit CRC of the firmware image. The client
  shall verify that this CRC corresponds to the one in the Flash header and
  that the application's CRC matches.

  The byte after the CRC contains a minifloat (reboot timer).

* 8-11
  Read
  The server sends a block# and 1-byte length-1 (i.e. 0…63, corresponding
  to 1…64 bytes). The client replies with the contents, plus 16-bit checksum.

  8: standard flask
  9: boot flash
  10: RAM
  11: EEPROM
  
* 12-15
  Checksum Range
  As 'Read' but the reply contains just the checksum. TODO.

Updating the boot loader
========================

Boot loader updating is performed by a special application that, when
jumped to as part of finalization, copies itself to the beginning of
Flash memory and then reboots.

The new boot loader is stored directly behind the Flash header, followed by
the copy-to-start code.

Commands 4 and 5 are currently identical.
