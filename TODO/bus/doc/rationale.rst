=========
Rationale
=========

--------------
Why a new bus?
--------------

Assume that you want to deploy 100 sensors, using cheap microcontrollers
and little or no bus attachment hardware, to a possibly-unshielded
random-topology bus.

There are multiple protocols for wireless data: WLAN, Zigbee, Enocean,
Bluetooth-BLE, ZWave, various bespoke protocols on 433/868/911/2400 MHz …)
but that requires additional hardware.

KNX is slow and requires additional hardware, though if you only have two
wires it's a fallback option.

A bus like 1wire is too fiddly to write reliable clients for. (Several
people have tried.) Also, 1wire doesn't have multi-master and you don't
want to poll the bus all the time.

You could use half-duplex serial but timing requirements are rather strong
(5%), and most built-in UARTs can't do good half duplex. Also, your MCU
might only have one serial port. You might rather use for debugging or to
control something.

Next problem: long wires have somewhat high impedance. This limits your
transmission speed. You could use something like I²C, but a software client
is annyoing to program and a hardware client is too susceptible to noise.
Worse, you need 16 bus transitions per byte. We can do better.

The MoaT bus offers a different solution. It requires four to six wires:
ground, power, and two to four data lines. The MoaT bus can send one bit
per baud on a two-wire bus without requiring start/stop bits or bit
stuffing; on three wires, the speed is 2.5 bits per baud, or 3.5 bits on
four wires.

It is multi-master, self-timing, and (mostly) resistant to transient noise.


Principle of operation
======================

A bus with N wires can assume 2^n states. The self-timing requirement
enforces *some* transiton between states; also, the idle state must be
avoided. Thus, each time slot can transmit log2(2^n-2) bits of information.

A two-wire system transmits one bit per slot.

On three- and four-wire systems, messages are chopped into 5- or 7-bit
chunks that get encoded to a dual bit-change mask.

Encoding
++++++++

The transmitted bits are encoded as numbers from 1 to 2^n-1, with the LSB
corresponding to the first wire. We change the state of the wires which
map to 1-bits. In order to avoid an all-zero result, the mask is
incremented by one when it is not smaller than the current wire state. Thus
the transmitted signal is in the interval ``[1;2^n-1] \ {wire_state}``.

::
	start_xmit:
		chunks = chunk_up(next_msg)
		prio = 1+next_msg_prio
		set_timeout()

	xmit(state):
		if prio:
			if state:
				return 0
			res = 1<<(prio-1)
			prio = 0
			return res
		if chunks:
			mask = xmit_table[next(chunks)]
			if mask >= state:
				mask += 1

			return state ^ mask

		wait_ack = true
		return 0


Typically this loop is implemented as a state machine that's unrolled
around the DELAY calls.


Decoding
++++++++

The decoder inverts the encoder's work. Its ``decode_step`` function is
invoked for every pin change.


The decoder runs alongside the sender.

::
	start_decoding:
		assert wire_state == 0
		t = current_time()
		s0 = s1 = s2 = 0

	decode_step:  # called whenever any wire's state changes
		cancel_timeout()
		t2 = current_time()
		s2 = wire_state
		if t2-t < BITRATE/6:  # glitch
			t2 = t
			return
		if sx and t2-t < BITRATE/3:  # collision
			if s2 !=

		t = t2
		if s0 == s1:
			pass  # glitch: ignored
		elif s0 == 0:  # state was idle, thus priority or Ack
			return
		else:
			bits = s0 ^ s1
			bits -= 1 + (s0 < s1)
			received(bits)

		s0 = s1
		s1 = s2
		if sending or s2 == 0:
			set_timeout()

	timeout:

		if sending:
			wire_state = sx = xmit(s1)

		if s0 != 0 and s0 != s1:
			bits = s0 ^ s1
			bits -= 1 + (s0 < s1)
			received(bits)
			# TODO: send ACK/NAK, if our message

		s0 = s1 = s2 = 0


Sending Ack/Nack
++++++++++++++++

After every message, the sender releases the bus. The recipient is expected
to immediately reply with a positive or negative Acknowledge state by
setting the first bus wire for a positive, the second wire for a negative
reply.

On a two-wire system, a negative ack sets both wires, in order to
distinguish a no-answer situation from a low-priority sender.

Systems that want to send a message with priority 0 (or 1, on >2 wires)
must observe the bus. If no Ack/Nack cycle has been observed after a
message, they must use priority 1 (or 2, on >2 wires) on their next attempt.


Collisions
++++++++++

Collisions are detected by observing an asserted wire that should not be.
Considerations:

* immediate de-assert vs. wait a short time, to check if the collision is transient?

* does the collision affect high- or low-priority bits?



Bus addressing
==============

There's no point in catering for more than ~100 devices on a bus: among
other reasons, they all need to be powered. The MoaT bus thus limits its
client addresses to 7-bit integers. Server systems get two bits: up to
three servers, and broadcast.
