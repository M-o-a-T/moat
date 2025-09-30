Address assignment
==================

Address assignment messages are control messages with type zero.
They are special because clients must listen (and possibly react) to them
even if they're not addressed to them directly.

Every assignment message's first byte contains a the message type (bit 2…0,
zero), a flag bit (bit 3) and four bits for the length of the client's
serial number / MAC / EUID, minus one (bit 7…4). Serial numbers longer than
16 bytes are not allowed. Serial numbers shorter than four bytes are strongly
discouraged.

Bytes two to ``length+2`` contain the serial number.

If the flag bit is set, the serial number is followed by an additional flag
byte. Otherwise the flag byte is assumed to be zero and the message ends
after the serial.

A client process an AA message if

* the client knows its ID and the message is addressed to it directly,

*or*

* MAC length *and* MAC content matches theirs.

Message types
-------------

AA message types are encoded by the control message's mode, i.e. the
combination of source and destination address.

* Mode 1 (Broadcast → Broadcast)

  Request. Sent by a client that doesn't have an address yet.

* Mode 2 (Server → Client)

  ACK: Address assignment.

* Mode 3 (Server → Broadcast)

  NACK. The server rejects, or refuses to assign, this address.

* Mode 4 (Client → Broadcast)

  Collision. A client has observed its own address with a different MAC, or
  vice versa.

* Mode 5 (Client → Server)

  Poll reply. This is used when a server's Poll request indicates that the
  MAC shall be included.


Other message modes are reserved.


Flags
-----

Flag bits, if present, are located directly after the MAC/serial.
Bit 3 of the first byte states whether a flag byte exists.
A nonexisting flag byte is equivalent to zero.

If the message is a NACK with a "data problem" reason, bits 7…3 encode the
reason instead. See below.


* bit 0: wait. If set, the next byte contains a timer minifloat.
  Its meaning varies depending on the mode:

  * Request: The server shall delay for this time before sending a reply.
    Used e.g. when the client does some more initialisation before it restarts
    its bus listener.

  * ACK: The client shall wait this long before proceeding.

  * NACK: The client shall wait this long before trying again.


* bit 1+2: state

  * Request: 0 rebooted, 1 wakeup, 2 check, 3 reserved.

  * ACK: 0 new, 1 known, 2 reserved, 3 reassigned.

  * NACK: 0 retry later, 1 no free addrs, 2 data problem, 3 collision
    as discovered by the server.

  * Collision as discovered by the client: 0 reserved, 1 I see my MAC,
    2 I see my client addr, 3 reserved.

  In both cases the client shall send its own ID and MAC. If it reacts to
  an ACK it must stop processing, must verify its client ID, must request a
  new ID if verification fails, and may create a random MAC if that fails
  too.

  The reason for a data problem is noted in bits 7…3.


* bit 3: client is/shall be polled.

  This bit is set if/when the client periodically goes to deep sleep, i.e.
  it will not listen to the bus.

  If this bit is clear, servers may assume that the device has vanished if
  it doesn't answer (repeated) queries.

  If this bit is set, the next bytes contain two timer minifloats.
  The first states how long the client typically listens before shutting down.
  The second states how long the client typically sleeps.

  These values apply to both client- and server-generated messages.


  * Request: tell the server what the client would like to use.

  * ACK: tell the client which values the server would prefer, with no
  obligation to use them.

  * NACK: lower or upper limits for these timers if they're
  lower or higher than the ones supplied by the client, respectively.

  A zero value for one of these timers means "unspecified / don't care"; it
  is not allowed in a request. If the server doesn't need to change any of
  the client's timers it may clear bit 3. A server that doesn't understand
  polling clients shall reply with a "data problem" NACK.


* bit 4: address is random / connection is temporary.

  A client should set this bit if it has created a random serial# and uses
  it to register for the first time. The server *must* NACK the address
  if this bit is set and it has ever seen the address before.

  The client *must* remember the serial# in Flash or NVRAM, including
  through power failures, if (and only if) the server ACKs it with this bit
  cleared. (In a test installation, the server may tell the client not to do
  this by sending the ACK with bit 4 set.)

  The client *must* delay saving the serial# if bit 0 is set. It must
  restart if it receives a NACK after the fact, as described
  above. The server should set a delay appropriately.

  After the client saves the randomized serial#, it *must not* set this bit
  the next time it registers.

  If a registration with a randomized serial# fails, or looks in any way
  suspicous, a client *must* re-register with a new random serial.

  In an ACK this bit tells the client that its address is Limited.
  This means that if the device sleeps, it must acquire a new client
  address upon wake-up, it may not assume that any connections are still
  valid. Also this changes which poll broadcasts the device responds to.


* bit 5: unconfigured

  Use this bit for a device that requires configuration.

  An unconfigured device should reply to scans with bit 10 cleared instead
  of bit 8 or 9. It must not disconnect: all timer-related poll
  messages should be simulated but ignored.

  A client should set this bit if it thinks it is not configured. The
  authoritative state, however, is the one sent by the server.


* bit 6…7: reserved.


A device with an empty serial number shall randomly invent one. If the CPU
does not have a hardware RNG, the device must observe bus message timing
with a high-precision timer long enough to observe reasonable entropy.

It shall then send a request with bit 4 set. The server shall be extra
cautious before assigning a new address to such clients.

Clients must monitor all AA requests for their own serial number. If they
receive an ACK with their current client ID, they should update their state
and send a Poll broadcast. Otherwise they must send a collision message.

Clearing a random address that has been saved is not required (it might be
impossible).

Data Problem: Reason codes
--------------------------

These

* 0: unspecified

* 1: Server doesn't do polling

* 2: Server doesn't

* Others: reserved


Sample messages
---------------


Simple assignment
+++++++++++++++++

A client requests an address, server 1 assigns address 12 and requests a
2.5 second delay before the client sends its next message(s).

====== === === === ====================
From   src dst cmd data (hex)
====== === === === ====================
Client S0  S0   0  30 12 34 56 78
Server S1  12   0  38 12 34 56 78 01 0A
------ --- --- --- --------------------
                   [ 2.5 seconds pass ]
---------------------------------------
Client 12  S0   1  01
