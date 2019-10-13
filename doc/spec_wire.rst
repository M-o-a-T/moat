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

A bus with N wires can assume 2^n states. The self-timing requirement
enforces *some* transiton between states, thus each time slot can transmit
log2(2^n-1) bits of information.

With even more wires, there's no longer an obvious best size that's
suitable for 8-bit CPUs. We'll settle on the fact that three transitions on
a four-wire bus carry 11.72 bits, while three transitions on a five-wire
bus carry 14.86 bits.

Since a message can contain excess bits, we can use an "illegal" sequence
to terminate the message. Our messages thus don't need a length byte and
can be generated on the fly if necessary.

The message is thus split into 11- or 14-bit frames. An incomplete last
frame is extended with 1-bits. Each frame is interpreted as an unsigned
number and repeatedly divided by 2^n-1. The list of remainders of this
operation is transmitted from the end, thus a sequence that would overflow
the frame can be used as an end-of-message marker without transmitting it
completely.

Each remainder from this list is incremented by 1. The result is
interpreted as a bit mask. When sending a bit, the mask is XOR'd with the
current bus state. Likewise, the receiver will read the bus state, XOR it
with the previous state, subtract one, and add the result to the current
frame's value (after multiplying the previous value by 2^n-1).


Bus Timing
++++++++++

Timer A is somewhat larger than the maximum signal round trip time on the
bus.

Timer B is the maximum delay allowed between "timer A expires" and "wire
state is sampled". This depends on the granularity of the participants'
timers, and on the interrupt latency for wire changes and
timer expiry.

Timer C is the timeout for collision recovery. Its initial value is A+B
(during a message) or 2A+B (transfer completed). It is started whenever
the bus is all-zero when timer A triggers.

Timer A controls both senders and receivers.

Timer B is only used when sending.

Timer C is used by any node which wants to send or receive a message.

At the beginning of each time slot, the sender pulls any number of wires
low. It then starts timer A. Any receiver which notices a transition on
any bus wire also starts timer A. The sender re-starts A when it notices
any wire changes.

When timer A expires, the sender checks whether the bus is in the state
it should be. If it is not, a collision occurred. The sender will de-assert
its bus lines, wait until the bus is idle, and try again. Otherwise it will
start timer B; when that fires, the sender sets the next piece of data by
flipping the state of at least one wire.

Receivers sample the bus when timer A expires, start timer C, then wait for
the next state change (at which time timer C is cancelled).

Senders start timer A when they change the wire state, verify that their
signal is on the bus when it expires, start timer B to ensure that all
receivers saw them, then start the next frame.

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
to the packet's priority, and starting a timer that runs for A+B. If any
higher-priority wire is also asserted during that time, the sender must
immediately de-assert its signal and try again later.

The bus is idle when it is de-asserted for 2A+B. A sender waiting for a
slot will delay some random time between A and 3A before trying to transmit.


Collision detection
+++++++++++++++++++

Detecting a collision is easy: a wire is set which you don't want to be
set. The problem is quick recovery: we need to separate "sender A has set
wire 1, while sender B has set wire 2" from "sender B has set both wires".
This is important because if both senders notice the collision and drop
their signal, the next state is "no wire is set", which is *still*
indistinguishable from "sender B releases both wires" in the second case.

Thus there are two possible approaches to collision resolution:

* restrict the state space. The naïve way would disallow asserting more
  than one wire at a time, plus imposing ordering when de-asserting.
  This method would make transactions longer and the implementation
  significantly more complex in general, so its usefulness is limited to a
  highly-congested bus, which MoatBus should not be – that's why we're
  trying to speed up transmission, after all.

* Dropping off the bus, timing out as quickly as possible, and restarting
  in a controlled way.

This process can be sped up by causing immanent collisions as quickly as
possible.

Also, all messages carry both sender and recipient addresses so that late
collisions (i.e. in the message body the header) cannot happen.


CRC check
+++++++++

All messages are protected by a CRC. The algorithm is CRC-8-MAXIM when the
message contains fewer than 8 data bytes, CRC-16-XMODEM otherwise.

This means that the message header must be decoded before the receiver can
verify the CRC. That is not a problem in practice because in order to save
power, the typical receiver will have done this anyway.

The sender simply appends the CRC to the message, high-end byte of the
CRC16 first.

The receiver ignores any partial byte. It first calculates the CRC over the
whole message except for the last byte. If the CRC is zero *and* the last
byte is 0xFF, that byte is removed along with the CRC. Otherwise the last
byte is mixed into the CRC; its value shall now be zero, otherwise an error
is signalled.

This process ensures that a fill byte inserted by the sender is recogized
correctly. This would not work with a fill byte of zero: if the CRC already
is zero, it would not be affected. In contrast, a zero CRC mixed with 0xFF
is always non-zero.


Acknowledgments
+++++++++++++++

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

