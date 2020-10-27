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

Messages consist of a 4-bit type and 4-bit flags in the first byte, plus
whatever content is required.

A checksum of zero indicates that the client is unable to read its own ROM
and thus can't sum up its firmware. A checksum of all-one states that there
is no (such) firmware. If legitimate checksumming results in either of
these values, the lowest bit shall be inverted.

If a client is not in boot mode, message 0 must be answered. All others
may be rejected.

* 0
  Firmware checksum + version

  The server sends an otherwise-empty message.

  The client shall respond with the 32-bit checksum plus a firmware-defined
  version number or string (bytes, length variable but nonzero).
  If there is no current firmware the CRC must be all-1; if the client
  knows its firmware is valid and can't be bothered to checksum it, it may
  reply with a version string and an all-zero CRC.
  
* 1
  Bootloader checksum + version
  As 0 but for the boot loader.

* 2
  reserved
  was serial# update, but that should be done via the dictionary

* 3
  Error
  Sent by the client. Followed by some diagnostic data, preferably
  human-readable.
  The first byte contains a max-64-byte length-1.
  Its bit 7 is set if the error is fatal and the device is potentially no
  longer useable. Bit 6 is set if the error cannot be recovered by simply
  retrying, i.e. need to power cycle and/or connect to a hardware programmer.

* 4
  Clear
  Sent by the server, requests the client to clear its firmware, preoaring
  for uploading a new image. The message contains the number of 64-byte
  blocks to be written (16bit, big-endian).

  The client will mirror this request after it has erased the ROM which the
  firmware shall be written to.

* 5
  Clear Boot
  Clear space for a new bootloader upload. This typically destroys the
  existing non-boot firmware. Same parameters as in 4.

* 6
  Send Block
  The server sends the 16-bit block number, a 64-byte block of data, and a
  16-bit checksum of the whole message.

  The client writes the block to firmware and replies with the same
  message, except for the actual data. A write error shall be indicated by
  a type-3 message.

  Blocks must be transmitted consecutively. They must be repeated if the ack
  got lost.

* 7
  Finish
  The server sends a 32-bit CRC of the firmware image. The client
  shall verify that CRC, then reply with the same message, then reboot into
  the new firmware. A CRC of all-zero is ignored.

  If the boot loader has been replaced, the reboot may involve copying it to
  its final destination before rebooting.

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

