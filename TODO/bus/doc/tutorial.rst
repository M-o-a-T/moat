Tutorial
========

The MoatBus system is somewhat non-trivial, so here's a step-by-step
documentation how to set it up.

First, you need a couple of programmable MCUs. The test setup consists of
three STM32F103 Blue Pill evaluation boards, so we'll start with these.

Grab a Raspberry Pi 2 and two 3.3V serial-to-USB interfaces – or anything
else that runs Linux and has three 3.3V serial ports and lots of free GPIO
pins: you need two GPIOs per pill to program and reset them. Another two
are very useful for debugging, but not strictly required.

The following assumes that you have a Pi and a "real" computer for testing. 
Compiling the firmware may be annoyingly slow on the Pi, so we'll
do that on something faster. Unless you have a Pi 4 and/or decide not to
bother; asjust as appropriate.

See `hacking`_ how to wire up the Pills. Teaching the test system which
GPIO pins do what is also described there.

Copy ``ci/rc.local`` to your Pi's ``/etc/rc.local``, enable it (``systemctl
enable rc-local`` and ``chmod +x /etc/rc.local``), copy
``ci/71-serial.rules`` to ``/etc/udev/rules.d``, change it to match your
serial adapters, don't forget to disable the serial console if you use it
for one of the Pills, and reboot the Pi.

Set up DistKV. Both your development machine and the pi will want to talk
to it.

On your build machine, install Meson+Ninja and run "make.sh". You now have
a ``.pio/build/moat_gate/firmware.bin`` file. 

The following commands use ``mb`` as an alias for ``distkv client
moatbus`` and ``mbv`` for ``distkv -v …``. You shoud teach your shell to
expand that if you don't want to type so much.

``mb bus test add -n "Test bus"`` creates a new MoaT bus.

``mb bus test gate NAME add -n "Test gateway" -t serial -a device /dev/ttyACM0
-a speed 115200`` creates a new gateway to your test bus. *NAME* should be
the one you gave your Pi when setting up DistKV.

On the Pi, start ``mbv bus test run -s``. It should say "Ready"
and not crash immediately. ;-) ``-s`` is stand-alone mode. Redundant mode
isn't implemented yet. Then interrupt it: this command will be started by
the ``ci/run`` program, later, and running it twice in parallel won't work.

On your development machine, start ``mbv bus test serve addr -s1``. This starts
the address assignment daemon in stand-alone mode. Again, no redundant mode
yet.

Open three shells on your Pi. Run ``ci/run a``, ``ci/run b`` and ``ci/run c``.

Do ``export TESTER=root@your-test-pi`` on the development system.
Subsequently, ``make pio copy run`` will build the firmware, copy it onto
the Pi, re-program the Pills, and start serial monitors plus the gateway.

NB: keep in mind that the Flash storage on the Pills can't be reprogrammed
infinitely often. 10'000 cycles are OK for a year or so if you do 30 tests
per day (which on average you probably won't), but if you run the tests in
an endless loop you'll be disappointed a lot sooner than that.

