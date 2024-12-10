===========
Wire format
===========

Principle of operation
======================

Rationale
+++++++++

A bus with N wires can assume 2^n states. "Sloppy" timing requires
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

This table shows that transmitting an integer number of bits is wasteful
(we lose the fraction): we'd essentially reserve one wire.

However, we can do better by combining multiple transitions until the
fraction is as small as possible. Two transitions on a 2-wire system can
have 9 states, or 3.16 bits. The next-best value is at seven transitions:
3^7 = 2187 states or 11.09 bits.

With three wires, two transitions have 49 states or 5.61 bits. That's
still wasteful; a "good" value is at 5 transitions: 14.04 bits.

Using four or even five wires ends up at 11.23 or 14.86 bits, with three
transitions each (or six wires, two trnsitions, 11.95 bits). This is no
longer an obvious "best" size because the fractions decrease until 15^10
(39.07 bits), 31^21 (104.04 bits) or 63^44 (263.0003 bits).

However, we'd like to stay below 32 or even 16 bits: We should be able to
implement this bus on a "legacy" 8-bit CPUs, thus we need to keep the math
fast and simple.


The following table summarizes the result.  The last four columns contain
the message sizes (number of transitions required) for a given message
length (in bits). Message lengths have been adjusted according to "Further
Considerations", below.

=====  ======  ====  ===========  ======== === === === ==== ==== ====
Wires  States  Bits  Transitions  cum.Bits  32  48  64  128  132  256
-----  ------  ----  -----------  -------- --- --- --- ---- ---- ----
  2       3    1.58       7        11.09    24  35  45   87   87  168
  3       7    2.81       4        11.22    13  20  25   49   49   96
                          5        14.03    15  20  25   50   50   95
  4      15    3.90       3        11.72    10  15  19   36   37   72
                          4        15.62    12  16  20   36   36   72
  5      31    4.95       2         9.90     8  12  16   30   30   58
  5      31    4.95       3        14.86     9  12  15   30   30   57
  6      63    5.97       2        11.95     6  10  12   24   25   48
=====  ======  ====  ===========  ======== === === === ==== ==== ====

The outlier here is five wires. All other combinations support 11-bit
blocks as an "obviously quite good" message size.

Since a message can contain excess bits, we can use an "illegal" sequence
to terminate the message. Our messages thus don't need a length byte:
they can be generated on the fly if necessary, though the current
implementation doesn't take advantage of this.

Further Considerations
----------------------

Encoding a non-integer number of bits means that there's some code space
left over. We can use that space for early message termination.

For example, the larges "legal" state sequence on a 2-wire system is ``2 2
1 0 2 1 2``. Using ``2 2 2`` as an early termination signal allows us to
code a five-bit remainder (2212222₃-2210212₃ = 57), while ``2 2 2 2`` would allow
for six bits (2221222₃-2210212₃ = 111), a trade-off that's not interesting.

On the other hand, on 3-wire systems the maximum is ``5 6 5 4`` (four
transitions) / ``6 5 5 2 4`` (five), which can encode 3 / 6 bits. Requiring
an additional terminator yields 8 bits for both. This means that on average
and for short-ish messages, on 3-wire systems there's some advantage to
using shorter messages.

A 4-wire 4-transition system can already do 10 bits in its remainder, while
on five transitions the additional transition doesn't matter (13 vs. 14 bits).

Thus, limiting the MoaT bus to work exclusively with 11-bit blocks seems
reasonable and helps to simplify the code.


Basics
++++++

The message is split into 11-bit frames.
These frames are interpreted as big-endian unsigned integers.

The transmission order is big-endian due to the frame end sequence.

Each frame's value is repeatedly divided by 2^n-1, n being the
number of bus wires. The remainders of these divisions are collected in a
list of 7/4/3/… integers with a value between 0 and 2/6/14/… inclusive.

The last frame is likely to be incomplete. If more than 5/8/10 bits are left over,
the frame is extended with zero-valued bits and transmitted normally, followed by
a termination sequence of 3/2/1 states of "all wires inverted". The same
thing happens when there are no bits left.

Otherwise, the remaining bits are interpreted as an integer with bit 12
set. The resulting value is lower than 3⁷ / 7⁴ / 31³ and its encoding
doesn't start with the termination sequence, thus it can be transmitted
normally.

Each value on this list is incremented by 1. The result is interpreted as a
bit mask. When sending a bit, this mask is XOR'd with the current bus state.



To reverse this process, the receiver reads the current bus state, XOR it with
the previous state, subtracts one, and adds the result to the current frame's
value (after multiplying the previous value by 3/7/15/…, which is equivalent
to a shift-and-subtract), thus recovering the frame's content.


Error recovery
--------------

The message termination indication is immediately followed by an 11-bit CRC
frame. The CRC must not leave the bus in an all-zero state;
in this case the last value is inverted (i.e.. 2/6/14 - *value*, before the
increment-by-one).

After the CRC, one slot is used for message acknowledgment.


Bus Timing
++++++++++

The MoaT bus has four timers. Neither timer requires an interrupt.

Timer A governs the fact that signal propagation might be asymmetric
(pull-up vs. pull-down, differing twisted-pair impedance, et al.).
Bus changes that arrive while A is running are to be ignored. In other words,
when a bus change occurs as A is *not* running, the previous bus state is
processed and A is started.

Timer B is used for sending. It is larger than A by some margin, allowing
for maximum signal round trip time on the bus and interrupt processing /
polling overhead of the slowest system(s).

Timer C should be at least twice the value of Timer B. It is started
whenever the bus transitions to idle. A node that sends must wait until
timer C triggers.

Timer D governs the time a sender waits between the end of one frame and
the start of the next. It should be somewhat larger than C. Timer D shall
be increased temporarily when a bus collision occurred or when the next
message to be transmitted has a low priority. D may be decreased somewhat
(but not below its initial value) when a successful transmissions are
observed while the sender waits for it to expire.

Timer D has at least three possible values, which must be distinct and
increasing:

* fast retry
* high-priority messages
* low(er)-priority messages

Note that the bus natively supports priorities. See below.

Timer D shall be increased exponentially after a collision. It's
recommended to add a small(ish) random component.

Time slots
----------

At the beginning of each time slot, a sender starts timers A and B, and
pulls a number of wires low and/or releases them.

Any receiver that sees a bus change on checks whether its timer A is
running. If not, the *previous* state of the bus is processed and A is
started. In any case, the new state is saved as the 'new' previous state.

Timer A may or may not be re-started when the system notices additional
wire changes; this is a trade-off subject to real-world experimentation.

If the processed previous state is identical to the one before that, there
was a bus glitch. It *may* be ignored, but the more robust option is to abort
frame reception.

The sender monitors the bus state. If any wire is pulled down that's
not in the previous *or* the current intended bus state, the bus is
released and the transmission shall be retried. This also applies when a
bus change occurs while timer A is not running *or* when the current state
is not the intended state at the time A expires.

When a collision is detected, the sender will de-assert its bus lines,
stop timer B, and queue the current frame for retransmission.

Otherwise it will wait for timer B; when it fires, the sender sends the next
piece of data. As per the above rules, this changes the state of at least
one wire.

A receiver must start timer C whenever it detects an idle bus.
It is re-initialized if C has expired when a bus change from idle
state occurs.

Senders involved in a collision must switch to receiving if the message
continues. In practice this means that its receiver and the associated
wire-change interrupt should run continuously regardless of whether the
sender is active.


Ideas for improvement
---------------------
A Measure command that determines round-trip parameters between two nodes,
bus timing, etc., would be helpful.

Timers can then be tightened to adjust safety margins.

When there is no danger of collision (i.e. after the sender's address has
been transmitted), bus timing can be sped up.


Bus arbitration
+++++++++++++++

Initially the bus is idle: all lines are de-asserted.

A MoaT bus transition starts with a sender asserting one wire, according
to the packet's priority. If a higher-priority wire is also asserted during
that time, the sender must immediately de-assert its signal and try again
later; this *must* happen while every receiver's Timer A is still running.

A sender waiting for a slot should back off exponentially before trying to transmit.

The highest priority is zero, corresponding to wire 1 being set.

Messages *may* be preempted, i.e. if a sender notices that wire 2 is set
while its timer D has not yet expired, but it has a higer-priority message
queued, it may start sending right away. This does not apply for low-prio
messages (i.e. with priority > the number of bus wires).


Collision detection
+++++++++++++++++++

Detecting a collision is easy: a wire is set which you don't want to be
set. The problem is quick recovery: we need to separate "sender A has set
wire 1, while sender B has set wire 2" from "sender B has set both wires".
This is important because if both senders notice the collision and drop
their signal, the next state is "no wire is set", which is *still*
indistinguishable from "sender B releases both wires" in the second case.

The MoaT bus works around this problem: in the first case both A and B
immediately drop their signal and set their fast-retry flag. In the second
case, transmission continues as A will retry normally.

A fast retry works by temporarily changing the message's priority.
Specifically, each sender uses the wire which in its opinion was "wrong" as
the message's new priority, thus ensuring that a fast retry will not
collide again.

Senders which detect a collision must treat the incomplete message as
incoming data and switch to receive mode.


CRC check
+++++++++

All messages are protected by a CRC. The CRC is a 11-bit checksum
(generator 0x583, reversed). This polynomial has a Hamming distance of 4
(i.e. it can always recognize three errors) for messages up to 1012 bits.
On a 2-wire bus that's 73 frames or 100 bytes of "real" data, which should
be sufficient.

The CRC is calculated over the actual bus wire states, XOR'd with the
initial bus arbitration state. Thus a complete message's CRC can be
pre-calculated if necessary. The bus flips that may indicate end-of-message
are included in the CRC.

The CRC is transmitted directly after the end-of-message marker.


CRC selection criteria
----------------------

CRC selection was constrained by these parameters:

* The CRC should not be larger than one frame.

* It should be possible to pre-calculate the CRC.

* It should be possible to *not* pre-calculate the CRC and instead stream a
  message onto the bus as it is generated.

* Traditionally, CRCs are calculated using the message's "real", content, i.e.
  before encoding to a wire format. This is not possible here. See below.

* Bus errors will always affect at least two bits. As protecting against a
  single error is not sufficient, a Hamming distance of 4 is required.

The state at successful arbitration is XORed into the wire states as
they're fed to the CRC calculator. This ensures that the CRC does not
depend on the message's priority (which might change, e.g. if the message
acknowledges an earlier transmission and thus needs to arrive in time).


No message-level CRC check
--------------------------

A more straightforward implementation would be to simply run a CRC over the
bytes of the message instead of the encoded frames' wire states. The
problem is that this does not work as expected.

Due to the way messages are encoded on the bus, a single inverted bit on
the wire will always affect up to 16 bits of the resulting content.
A CRC is not designed to handle this.

The test program `fakebus/test_handler_crc.c` creates random messages,
encodes them, injects a number of random errors, decodes the result, and
checks whether the CRC is correct. This program demonstrates after a few
seconds that a single bit error in a three-byte message can result in a
valid CRC. Owch.

The test code also demonstrates that if there are *any* errors, the
resulting CRC is essentially random, thus even a CRC-16 would admit a
~1/10⁶ probability of accepting a broken message. The odds for a faulty
CRC-8, which would otherwise be adequate for smaller messages, are even
higher.

These odds are uncomfortable enough to choose a different algorithm.


Choice of CRC parameters
------------------------

Our CRC polynomial selection is based on Table 3 (page 6) in
<http://users.ece.cmu.edu/~koopman/roses/dsn04/koopman04_crc_poly_embedded.pdf>.

Real-world CRCs frequently use non-zero start values to protect against
errors in initial runs of almost-zero data. Our protocol does not have
this problem because every wire change affects at least one bit. Thus we
keep things simple: our start value is zero.

Real-world CRCs have the property that appending the CRC to the message
results in a zero CRC. We cannot do that on the MoaT bus because the result
might contain a sequence of repeated bus states. Instead, we interpret the
CRC as an 11-bit integer and send it as usual.


Message Acknowledgment
++++++++++++++++++++++

All correctly-received messages must be acknowledged.

To ack a message, a receiver will take over immediately after the last
change by the sender (i.e. the bus returns to idle after CRC reception ends)
and assert wire 0. If that is not possible because wire 0 was the only
asserted wire (need a change on the bus; transients don't count), wire 1 is
asserted instead.

The receiver(s) start timer B, and release the wire in question when
it expires.

There is no negative acknowledge.


Algorithm
+++++++++

Sender
------

Case distinctions are for 2/3/4 bus wires.

* wait for timer D and/or start of lower-priority message
* set wire [Prio]
* restart if lower-prio wire is asserted

* calculate header+data checksum, append to packet buffer
* repeat while the packet is not exhausted:
  * repeat for each 11-bit chunk
    * if last chunk:
      * if len(chunk) <= 5/8/10:
        * add 2^11
        * remember not to send an end-of-packet sequence
      * otherwise
        * shift left
    * clear flip sequence
    * repeat 7/4/3 times:
      * divide by (2^N-1)
      * append to flip sequence
    * repeat until flip sequence is empty:
      * take the sequence's last entry
      * add one
      * XOR that with the current state of the bus wires
      * set bus to the result
      * wait tB
* Send end-of-packet sequence (unless high value tells us not to):
  * 3/2/1 times:
    * set bus to ~(old_state)
    * wait tB
* Send 11-bit CRC (one frame, same as above)
  * Exception: if the sequence's last entry would leave the bus idle, invert
* Clear bus state
* Wait for Ack bit


Receiver
--------

* wait for bus idle
* wait until at least one wire is asserted
* wait tA
* if more than one wire is asserted:
  * wait until only one wire is asserted
  * if that doesn't happen for tA, abort
* fetch the first chunk
* check for valid destination
* read more chunks until end-of-message
* read and verify checksum

Fetching a chunk means
* set frame content to zero
* repeat 7/4/3 times (for N=2/3/4):
  * multiply frame content by (2^N-1)
    (i.e. shift left 2^N and subtract old value)
  * read bus state
  * XOR with previous bus state
  * subtract one
  * add to frame
  * after s=3/2/1 steps of this:
    * if frame == (2^N-1)^s -1:
      * set end-of-message
      * ignore incomplete byte
* if frame > 2^N-1:
  * subtract 2^N
  * shift left 8 bits, add to frame
  * set end-of-message
* add frame to buffer

Reading the bus state means:
* wait tA for any change of signal
  * None? error if any line is set, otherwise aborted.
* read bus state
  * in practice: wait for the next change with tA clear, process the previous state

Waiting for ACK means:
* if only wire 1 is set, ACK is on wire 2, otherwise it's on wire 1
* deassert all wires
* wait until bus idle
* only the ACK wire was set? success
* otherwise: fail. Retry later.


+++++++++++++++++++++++
A short example message
+++++++++++++++++++++++

We want to send the single byte "0xbb" (binary 101-110-11, i.e. server 1
sends a zero-byte message of type 3 to server 2).

Let's assume a 4-wire bus – the example is shortest that way.

Wires  State                                              CRC
=====  ================================================== ==================
    0  Bus is at rest
    1  Sender arbitrates the bus (high prio)              for `xor`, below
    -  CRC is zeroed                                      000
    -  Convert 0xbf, 0b10111011-000, 1496, to base 15
    -  Result : 6 9 B (hex): (6*15+9)*15+11
    -  Add one: 7 A C
    6  Send: 1 xor 7                                      767 (add 1 xor 6)
    C  Send: 6 xor A                                      392 (add 1 xor C)
    0  Send: C xor C                                      097 (add 1 xor 0)
    F  first (on a 4+-wire bus: only) reversal            343 (add 1 xor F)
    -  Convert CRC 0x661, 819, to base 15
    -  Result : 3 A A (hex): (3*15+10)*15+10
    -  Add one: 4 B B
    B  Send CRC nibble: F xor 4
    0  Send CRC nibble: B xor B
    B  Send CRC nibble: 0 xor B
    1  Receiver acknowledges the message
    0  Bus is again at rest

You can calculate the CRC value with this command::

    moat bus crc  4 1  6 c 0 f

The first argument is the number of wires, the second the initial bus
state, the others the actual bus values.



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
