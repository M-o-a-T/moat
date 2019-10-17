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

The message is split into 11- or 14-bit frames. (An incomplete last frame
is extended with 1-bits.) Each frame is interpreted as an unsigned number
and repeatedly divided by 2^n-1, 'n' being the number of bus wires, until
the highest-possible frame number would be zero (i.e. 7/5/3/3/2 times, for
2/3/4/5/6-wire busses).

The list of remainders of this operation is transmitted from the end. Thus
a sequence that would overflow the frame can be used as an end-of-message
marker without transmitting it completely; this ends up as 3/2/1/1/1
complete reversals.

Each remainder from this list is incremented by 1. The result is
interpreted as a bit mask. When sending a bit, the mask is XOR'd with the
current bus state. Likewise, the receiver will read the bus state, XOR it
with the previous state, subtract one, and add the result to the current
frame's value (after multiplying the previous value by 2^n-1), thus
recovering the frame's content.


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

All messages are protected by a CRC. The algorithm uses polynomial x197
when the message contains fewer than 8 data bytes, x1BAAD otherwise,
no reflection.

This means that the message header must be decoded before the receiver can
verify the CRC. That is not a problem in practice because in order to save
power, the typical receiver will have done this anyway.

The sender simply appends the CRC to the message. It pads the last frame
wit 1-bits.

The receiver ignores any partial byte. It first calculates the CRC over the
whole message except for the last byte. If the CRC is zero *and* the last
byte is 0xFF, that byte is removed along with the CRC. Otherwise the last
byte is mixed into the CRC; its value shall now be zero, otherwise the
packet is dropped.

This process ensures that a fill byte inserted by the sender is recogized
correctly. A fill byte of zero would not work: when the CRC already is zero
it would not be affected. In contrast, a zero CRC mixed with 0xFF (or in
fact any other value) is always non-zero.

Choice of CRC parameters
------------------------

The polynomials have been described by Koopman and Chakravarty in
<http://users.ece.cmu.edu/~koopman/roses/dsn04/koopman04_crc_poly_embedded.pdf>
as providing optimal Hamming distance (4).

However, our errors do not directly affect the data; a single bit error
changes anywhere between 1 and ~10 bits. Further research is required.


Message Acknowledgment
++++++++++++++++++++++

All correctly-received messages must be acknowledged. Incorrect messages
(CRC error) *may* be reported.

To ack a message, the receiver will take over immediately after the last
change by the sender and assert wire 0. If that is not possible because
wire 0 currently is the only asserted wire, wire 1 is asserted instead.

To nack a message, the receiver will assert wire 1, except when either wire
1 is claimed by Ack or wire 1 and 2 are the only asserted signals, in which
case it will use wire 3.

If the current state is not "no lines asserted", a two-wire system cannot
send a NACK. As negative Acks are by definition unreliable, adding another
cycle just to transmit a NACK isn't useful.

