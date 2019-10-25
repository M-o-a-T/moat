===========
Wire format
===========

The MoaT bus is designed to be a simple-to-implement, mostly-self-timing,
collision-resistant, error-resistant, open-collector, multi master bus
system.

"Mostly self timing" means that the bus doesn't signal when data are ready.
In contrast, when an I²C receiver sees a falling clock it knows that it may
read the data *now*, and that it may hold the clock low until it's ready
for the next bit. In contrast, the MoatBus uses a data change to signal
that the message will be ready when the data state is settled, as rise and
fall time may be different; if a receiver miss its time slot, it loses the
message.

"Collision resistant" means that while the system tries to avoid
collisions, they are not always avoidable. However, the senders involved
in a collision know how to resolve the problem so that one may proceed
unimpeded.

"Error resistant" means that every packet is CRC-checked and acknowledged.


Principle of operation
======================

Rationale
+++++++++

A bus with N wires can assume 2^n states. The self-timing requirement
enforces *some* transiton between states, thus each time slot can transmit
log2(2^n-1) bits of information:

=====  ======  ====
Wires  States  Bits
-----  ------  ----
  2       3    1.58
  3       7    2.81
  4      15    3.90
  5      31    4.95
=====  ======  ====

That's still wasteful: we can do better. Two transitions on a 2-wire system
can have 9 states, or 3.16 bits. The next best value is seven transitions:
3^7 = 2187 states or 11.09 bits.

With three wires, two transitions have 49 states or 5.61 bits. That's
wasteful; the next "really good" value is at 5 transitions: 14.04 bits.

The same calculation with four or even five wires ends up at 11.23 or 14.86
bits, with three transitions each. This is no longer an obvious "best" size
because the fractions decrease until 15^10 (39.07 bits) or even 31^21
(104.04 bits). But if we want to be able to implement this bus on an
ATMega8 or a similar small-but-power-saving 8-bit CPUs, we need to keep the
math simple, so the upper limit is 16 bits. Also, the end of a packet
shouldn't have carry too many "wasted" information.

Since a message can contain excess bits, we can use an "illegal" sequence
to terminate the message. Our messages thus don't need a length byte and
can be generated on the fly if necessary.

A 6-wire bus would carry an 11-bit frame in two transactions. That's the
limit of what an 8-wire cable can do, so we'll stop here.

Basics
++++++

The message is split into 11- or 14-bit frames. An incomplete last frame
is extended with 0-bits, plus one bit that indicates whether the padding is
longer than 7 bits. Each frame is interpreted as an unsigned number.

When a frame ends at a byte boundary, no filler bits are inserted. If
the padding is exactly 8 bits wide, this fact is encoded by adding 2^11
or 2^14 to the frame's numeric value. In this case there is no explicit
end-of-message marker (see below).

The frame is then repeatedly divided by 2^n-1, 'n' being the number of bus
wires, until the highest-possible frame number would be zero (i.e.
7/5/3/3/2 times, for 2/3/4/5/6-wire busses).

The list of remainders of this operation is reversed, i.e. the higher
powers are transmitted first ("big-endian").

Each remainder from this list is incremented by 1. The result is
interpreted as a bit mask. When sending a bit, the mask is XOR'd with the
current bus state. Likewise, the receiver will read the bus state, XOR it
with the previous state, subtract one, and add the result to the current
frame's value (after multiplying the previous value by 2^n-1), thus
recovering the frame's content.

Transmission is big-endian because the maximum number to be transmitted
(2^11+2^3-1 / 2^14+2^6-1) does not start with 3/2/1+ factors of 2^n-2. We
can thus use this sequence as an end-of-frame marker and skip transmitting
the remaining digits as soon as we see it.

Every end-of-message marker is followed by an 11-bit CRC. On a 3-wire bus,
the CRC frame is one bus transaction shorter than normal. CRC calculation
is described below.

Bus Timing
++++++++++

Timer A is somewhat larger than the maximum signal round trip time on the
bus, allowing for interrupt processing / polling overhead on the slowest
system on the bus.

Timer B is large enough for every bus participant to complete the work
caused by Timer A.

Timer A controls both senders and receivers. It is restarted whenever a
wire changes state.

Timer B is used by senders: it triggers setting the next wire state.

Additional timeouts are used for recognizing bus stalls and (re)starting a
transfer; they are specified in multiples of Timer A.

Time slots
----------

At the beginning of each time slot, a sender pulls any number of wires
low. This change starts timer A. Any receiver which notices a transition on
any bus wire also starts timer A. The timer is re-started when the systen
notices any wire changes.

When timer A expires, the sender checks whether the bus is in the state
it should be. If it is not, a collision occurred. The sender will de-assert
its bus lines, wait until the bus is idle, and try again. Otherwise it will
start timer B; when that fires, the sender sets the next piece of data by
flipping the state of at least one wire.

Receivers sample the bus when timer A expires, start timer 2*A, then wait for
the next state change.

If the sender sees a wire change while timer B is running, the
transmission is aborted. Changes while timer A is running are mostly
ignored (except that when a wire gets asserted that should not be, there's
a collision) because the line impedance may cause transitions to occur long
after the sender changes its state.

Senders involved in a collision must switch to receiving if the message
continues.


Ideas for improvement
---------------------
The plan is to add a Measure command that determines round-trip parameters
between two nodes. Timers can then be tightened to adjust safety margins.

When there is no danger of collision (i.e. after the sender's address has
been transmitted), bus timing can be sped up.


Bus arbitration
+++++++++++++++

Initially the bus is idle: all lines are de-asserted.

A MoaT bus transition starts with a sender asserting one wire, according
to the packet's priority (which starts Timer A). higher-priority wire is
also asserted during that time, the sender must immediately de-assert its
signal and try again later.

The bus is idle when it is de-asserted for 3A. A sender waiting for a
slot will back off exponentially before trying to transmit.


Collision detection
+++++++++++++++++++

Detecting a collision is easy: a wire is set which you don't want to be
set. The problem is quick recovery: we need to separate "sender A has set
wire 1, while sender B has set wire 2" from "sender B has set both wires".
This is important because if both senders notice the collision and drop
their signal, the next state is "no wire is set", which is *still*
indistinguishable from "sender B releases both wires" in the second case.

The MoaT bus works around this problem: in the first case both A and B
immediately drop their signal and set a fast-retry flag. 

Also, all messages carry both sender and recipient addresses so that late
collisions (i.e. in the message body the header) cannot happen. This
reduces the possible impact of any elaborate "recover from a collision
in-packet" protocol.


CRC check
+++++++++

All messages are protected by a CRC. The CRC is a 11-bit checksum
(generator 0x583, reversed). This polynomial has a Hamming distance of 4
(i.e. it can always recongnize three errors) for messages up to 1023 bits.
On a 2-wire bus that's 73 frames or 100 bytes of "real" data, which should
be sufficient. (119 on 3-wire, 116 on 4-wire.)

The CRC is calculated over the actual bus wire states, XOR'd with the
initial bus arbitration state, so that a complete message can be
pre-calculated. The end-of-message bus flips are included.

The CRC is transmitted directly after the end-of-message marker.

CRC selection criteria
----------------------

CRC selection was constrained by these parameters:

* The CRC should not be larger than one frame.

* It should be possible to pre-calculate the CRC, and indeed the whole
  message.

* It should be possible to not pre-calculate anything, and stream a message
  onto the bus as it is generated.

* It's not possible to protect the "real" message with a CRC. Due to the
  way messages are encoded on the bus, a single changed bit on the wire
  will always affect 2 … 16 bits in the message. A CRC is not designed to
  handle this; the test program `fakebus/test_handler_crc.c` demonstrates
  that a single bit error in a short message might result in a valid CRC.

* Bus errors are bursty. Protecting against a single error is not
  sufficient, i.e. a Hamming distance of 3 is required.

Embedding the CRC into a frame that also contains other data is a
non-trivial exercise. The test program `fakebus/test_handler_crc_bus.c`
demonstrates this. Thus, while the idea would significantly shorten smaller
messages, it has been abandoned.

The state after successful arbitration is XORed into the wire states as
they're fed to the CRC calculator. This ensures that the CRC does not
depend on the message's priority (which might change, due to a collision)
and thus can be pre-calculated if necessary.


Rejecton of per-message CRC check
---------------------------------

A more straightforward implementation would be to simply run a CRC over the
bytes of the message instead of the encoded frames' wire states. The only
problem is that this does not work as expected.

A test program (included in this archive, as of commit 1006054) has
demonstrated that a CRC over the "high-level" message has a Hamming
distance of two (2 wires) or even one (3+ wires). While this is a rare
occurrence, the test demonstrates that if there are *any* errors, the
resulting CRC is essentially random, thus a CRC-16 would admit a ~1/10⁶
probability of accepting a broken message. The odds for a faulty CRC-8,
which would otherwise be perfectly adequate for smaller messages, are even
higher.

The author is not quite comfortable with these odds.

Choice of CRC parameters
------------------------

CRC width polynomial selection is based on Table 3 (page 6) in
<http://users.ece.cmu.edu/~koopman/roses/dsn04/koopman04_crc_poly_embedded.pdf>.

Real-world CRCs frequently use non-zero start values to protect against
errors in initial runs of almost-zero data. Our protocol does not have
this problem because every wire change affects at least one bit.


Message Acknowledgment
++++++++++++++++++++++

All correctly-received messages must be acknowledged. Incorrect messages
(CRC error) *may* be reported.

To ack a message, the receiver will take over immediately after the last
change by the sender and assert wire 0. If that is not possible because
wire 0 currently is the only asserted wire, wire 1 is asserted instead.

To negative-ack a message, the receiver will assert wire 1, except when
either wire 1 is claimed by Ack or wire 1 and 2 are the only asserted
signals, in which case it will use wire 3. This results in no NAck being
sent if there is no third wire.

NB: Our CRC prevents single- or double- bit errors which change the
message's content, but it cannot protect against errors (even single-bit
ones) that mimic the end of a message. The correct message length must be
verified independently, by embedded explicit length and/or end-of-message
elements.

+++++++++++++++++++++++
A short example message
+++++++++++++++++++++++

We want to send the single byte "0xbf" (binary 101-110-11, i.e. server 1
sends a zero-byte message of type 3 to server 2).

Let's assume a 4-wire bus – the example is shortest that way.

Wires  State                                              CRC
=====  ================================================== ==================
    0  Bus is at rest
    1  Sender arbitrates the bus (low prio)               remember for `xor`
    -  CRC is zeroed                                      000
    -  Convert 0xbf, 0b10111011-000, 1496, to base 15
    -  Result : 6 9 B (hex): (6*15+10)*15+11
    -  Add one: 7 A C
    6  first nibble: 1 xor 7                              361 (add 1 xor 6)
    C  second nibble: 6 xor A                             098 (add 1 xor C)
    0  third nibble: C xor C                              5aa (add 1 xor 0)
    F  first (on a 4+-wire bus: only) reversal            661 (add 1 xor F)
    -  Convert CRC 0x661, 819, to base 15
    -  Result : 7 3 C (hex): (3*15+9)*15+9
    -  Add one: 8 4 D
    7  first CRC nibble: F xor 8
    3  second CRC nibble: 7 xor 4
    E  third CRC nibble: 3 xor D
    1  Receiver acknowledges the message
    0  Bus is again at rest

You can calculate the CRC value with this command::

   python3 moatbus/crc.py 4 1 6 c 0 f

The first argument is the number of wires, the second the initial bus
state.

The traditional way of verifying a CRC (append it to the message, the
receiver gets a result of zero (or -1)) does not work here because of
our bus encoding. Thus, the receiver must remember the CRC and check that
the incoming value matches.

..
   Notes on CRCs.
   
   CRC-16:
        2    3    4    5    6    7    8    9   10   11   <- min len @ errors
     8002    0  125   37   28   19   19   20   20   17   baad  2048/4
      258    0  261   52   27   25   20   17   19   19   ac9a  241/5
      152    0  153    0   22    0   17    0   18    0   c86c  135/6
    16384  380   36   41   37   25   21   17   19   19   968b  19/7
    32768    0   68    0   32    0   18    0   19    0   8fdb  15/8
    
    32768    0   17    0   21    0   18    0   21    0   8408  CCITT
   
   CRC-11:
        2    3    4    5    6    7    8    9   10   11   <- min len @ errors
       24    0   25    0   26   12   13   24   24   15   571  12/7
       34    0   35    0   12    0   14    0   13    0   532  22/6
     2048   40   38   15   14   14   13   12   15   16   5d7  26/5
     1023    0   18    0   12    0   13    0   14    0   591
     1024    0   29    0   12    0   14    0   15    0   583  1012/4
     2048  143   18   22   15   12   13   15   16   16   64d  2036/3
   
   CRC-8:
       18    0   19    9   10   13   9c    9/5
      128    0   12    0    9    0   97  119/4
      256   24   15    9   11   11   a6  247/3
  
      128    0    9    0   10    0   8c  Maxim
  
   CRC-6:
       64    7    8    9   21
       32    0    7    0   2c
