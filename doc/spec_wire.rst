===========
Wire format
===========

Principle of operation
======================

Rationale
+++++++++

A bus with N wires can assume 2^n states. The timing requirement enforces
*some* transiton between states, thus each time slot can transmit
log2(2^n-1) bits of information:

=====  ======  ====
Wires  States  Bits
-----  ------  ----
  2       3    1.58
  3       7    2.81
  4      15    3.90
  5      31    4.95
  6      63    5.97
=====  ======  ====

That's somewhat wasteful, but we can do better by combining multiple
transitions until the fraction is as small as possible. Two transitions on
a 2-wire system can have 9 states, or 3.16 bits. The next-best value is at
seven transitions: 3^7 = 2187 states or 11.09 bits.

With three wires, two transitions have 49 states or 5.61 bits. That's
still wasteful; the next "good" value is at 5 transitions: 14.04 bits.

The same calculation with four or even five wires ends up at 11.23 or 14.86
bits, with three transitions each. This is no longer an obvious "best" size
because the fractions decrease until 15^10 (39.07 bits) or even 31^21
(104.04 bits).

However, there is a reason why we'd like to stay below 32 bits: If we want
to be able to implement this bus on an ATMega8 or a similar small (but
low-power) 8-bit CPUs, we need to keep the math simple.

You might think that another reason to keep the frames small is that
otherwise there'd be wasted space at the end of the last frame, but in
practice that problem doesn't exist; see below.

These considerations result in this final table:

=====  ======  ====  ===========  ========
Wires  States  Bits  Transitions  cum.Bits
-----  ------  ----  -----------  --------
  2       3    1.58       7        11.09
  3       7    2.81       5        14.03
  4      15    3.90       3        11.72
  5      31    4.95       3        14.86
  6      63    5.97       2        11.95
=====  ======  ====  ===========  ========

Since a message can contain excess bits, we can use an "illegal" sequence
to terminate the message. Our messages thus don't need a length byte and
can be generated on the fly if necessary.

Basics
++++++

The message is split into 11- or 14-bit frames, depending on bus width.
These frames are interpreted as big-endian unsigned integers.

An incomplete last frame is extended to the right with 0-bits if that
extension is shorter than 8 bits. Otherwise, bit 11 / 14 is set. This
results in a 12- or 15-bit number, but its value is still lower than
3^7 or 7^5.

This value is repeatedly divided by 3/7/…, or 2^n-1, n being the number of
bus wires. The remainders of these divisions are collected in a list of
7/5/… integers with a value between 0 and 3/7/….

The list of remainders of this operation is reversed, i.e. the higher
powers are transmitted first. We'll see later why this is important.

Each value on this list is incremented by 1. The result is interpreted as a
bit mask. When sending a bit, the mask is XOR'd with the current bus state.

To reverse this, the receiver will read the bus state, XOR it with the previous
state, subtract one, and add the result to the current frame's value (after
multiplying the previous value by 3/7/…), thus recovering the frame's
content.

Big-endianness and message termination
--------------------------------------

Examining the maximum value the highest-power integers on this list reveals
that on a two-wire system, the last three entries (those with the highest
power, contributing 3^6, 3^5 and 3^4) cannot all be 2, as 2*(3^6+3^5+3^4)
is greater than 2^11+2^3. Similarly, the last two on a three-wire system
can't all be 6 and the last remainder on a four-wire system can't be 14.

The MoaTbus uses this fact to signal the end of a message if the excess bit
was clear; if it was set, that's already unambiguous.
We can save even more: setting the excess bit on the last message signals

Error recovery
--------------

Every end-of-message marker is followed by an 11-bit CRC. On a 3-wire bus,
the CRC frame requires one bus transaction less than normal frames. CRC
calculation is described below.

After the CRC, one slot is used for message acknowledgment.

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
immediately drop their signal and set a fast-retry flag. In the second case
transmission continues, A will retry normally.


CRC check
+++++++++

All messages are protected by a CRC. The CRC is a 11-bit checksum
(generator 0x583, reversed). This polynomial has a Hamming distance of 4
(i.e. it can always recognize three errors) for messages up to 1023 bits.
On a 2-wire bus that's 73 frames or 100 bytes of "real" data, which should
be sufficient. (119 on 3-wire, 116 on 4-wire.)

The CRC is calculated over the actual bus wire states, XOR'd with the
initial bus arbitration state, so that a complete message's CRC can be
pre-calculated. The bus flips that indicate end-of-message are included in
the CRC.

The CRC is transmitted directly after the end-of-message marker.

CRC selection criteria
----------------------

CRC selection was constrained by these parameters:

* The CRC should not be larger than one frame.

* It should be possible to pre-calculate the CRC, and indeed the whole
  message.

* It should be possible to not pre-calculate anything, and stream a message
  onto the bus as it is generated.

* CRCs are usually calculated using the message's "real", content, i.e.
  before encoding to a wire format. This is not possible here. See below.

* Bus errors are likely to affect mutiple bits. Protecting against a single
  error is not sufficient, i.e. a Hamming distance of 3 is required.

Embedding the CRC into a frame that also contains other data is a
non-trivial exercise. The test program `fakebus/test_handler_crc_bus.c`
demonstrates this. Thus, while the idea would significantly shorten smaller
messages, it has been abandoned.

The state at successful arbitration is XORed into the wire states as
they're fed to the CRC calculator. This ensures that the CRC does not
depend on the message's priority (which might change due to a collision)
and thus can be pre-calculated if necessary.


Rejecton of per-message CRC check
---------------------------------

A more straightforward implementation would be to simply run a CRC over the
bytes of the message instead of the encoded frames' wire states. The only
problem is that this does not work as expected.

Due to the way messages are encoded on the bus, a single changed bit on the
wire will always affect 3 … 16 bits of the message's resulting content. A
CRC is not designed to handle this. The test program
`fakebus/test_handler_crc.c` demonstrates that a single bit error in a
short message can result in a valid CRC.

The test also demonstrates that if there are *any* errors, the resulting
CRC would essentially be random, thus a CRC-16 would admit a ~1/10⁶
probability of accepting a broken message. The odds for a faulty CRC-8,
which would otherwise be adequate for smaller messages, are even higher.

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
either wire 1 is claimed by Ack – or when wire 1 and 2 are the only
asserted signals, in which case it will use wire 3. This results in no NACK
being sendable if there is no third wire.

Algorithm
+++++++++

Thus, the complete algorithms are:

* calculate header+data checksum, append to packet buffer
* repeat while the packet is not exhausted:
  * repeat for each 11- or 14-bit chunk (14 bits for odd N)
    * if last chunk:
      * if more than 7 free bits:
        * add 2^11 / 2^14
        * remember not to send an end-of-packet sequence
      * otherwise
        * shift left
    * clear flip sequence
    * repeat 7/5/3/3 times (for N=2/3/4/5) (N=3: header requires 4 steps):
      * divide by (2^N-1)
      * add one
      * append to flip sequence
    * repeat until flip sequence is empty:
      * take the last entry
      * XOR that with the current state of the bus wires
      * set bus to the result
      * wait tA+tB
* Send end-of-packet sequence (unless high value tells us not to):
  * Once (N>3) / twice (N=2) / thre times (N=2),
    * set to ~(old_state)
    * wait tA+tB
* Send 11-bit CRC (one frame, same as above but 4 not 5 transitions if N=3)
* Clear bus state
* Wait for Ack bit

Each receiver will:

* wait for bus idle (unless expecting an Ack frame)
* wait until at least one wire is asserted
* wait tA
* if more than one wire is asserted:
  * wait until only one wire is asserted
  * if that doesn't happen for tA, abort
* fetch the first chunk
* check for valid destination
* read more chunks until end-of-message
* verify checksum

Fetching a chunk means
* set frame content to zero
* repeat 7/5/3/3 times (for N=2/3/4/5):
  * multiply frame content by (2^N-1)
    (i.e. shift left 2^N and subtract old value)
  * read bus state
  * XOR with previous bus state
  * subtract one
  * add to frame
  * after s=2(N=2: 3) steps of this:
    * if frame == (2^N-1)^s -1:
      * set end-of-message
      * ignore incomplete frame
* if frame > 2^N-1:
  * subtract 2^N
  * shift left 8 bits, add to frame
  * set end-of-message
* add frame to buffer

Reading the bus state means:
* wait 2*tB for any change of signal
  * None? error if any line is set, otherwise aborted.
* wait tA
* read bus state

Waiting for ACK means:
* if only wire 1 is set, ACK is on wire 2, otherwise wire 1
* deassert all wires
* wait tA+tB
* only the ACK wire is set? success
* otherwise: fail. Retry later.

There's also a NACK signal:
* on a two wire system, it's wire 2 if no wires are set, otherwise there is no NACK.
* if only wire 1, or only 1 and 2, is set, it's on wire 3.
* otherwise it's on wire 2.

The sender then decides whether to retry, and how often, depending on
whether only ACK is set (success), only NACK (retry) or possibly ACK plus
NACK (no retry) are set, or any other wires are held (collision).


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
    -  Result : 6 9 B (hex): (6*15+9)*15+11
    -  Add one: 7 A C
    6  first nibble: 1 xor 7                              767 (add 1 xor 6)
    C  second nibble: 6 xor A                             392 (add 1 xor C)
    0  third nibble: C xor C                              097 (add 1 xor 0)
    F  first (on a 4+-wire bus: only) reversal            343 (add 1 xor F)
    -  Convert CRC 0x661, 819, to base 15
    -  Result : 3 A A (hex): (3*15+10)*15+10
    -  Add one: 4 B B
    B  first CRC nibble: F xor 4
    0  second CRC nibble: B xor B
    B  third CRC nibble: 0 xor B
    1  Receiver acknowledges the message
    0  Bus is again at rest

You can calculate the CRC value with this command::

   python3 moatbus/crc.py 4 1 6 c 0 f

The first argument is the number of wires, the second the initial bus
state.



..
   These tables collect various results of generating minimal message
   lengths for a given CRC polynomial / error count.
   
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
