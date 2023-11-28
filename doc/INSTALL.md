Installing the moat.micro client
================================

The *moat.micro* client is a Python program, running on MicroPython.

Most controllers have quite limited RAM. The first step is therefore to
build a version of MicroPython that includes the *moat.micro* core:

:: shell

    $ git submodule update --init
    $ cd lib/micropython/mpy-cross
    $ make
    $ cd ../ports/esp8266
    $ echo 'include("…/moat/micro/moat/micro/_embed/lib")' >> boards/manifest.py
    $ DEV=/dev/ttyUSB0
    $ BAUD=74880  # 115200 for ESP32

    # adjust as required
    $ make PORT=$DEV ESPTOOL=esptool BAUD=500000 deploy

    # Verify that it's working
    $ pyserial-miniterm -f direct /dev/ttyUSB0 74880

    # You might have to press ^T^D ^T^R
    MicroPython v1.20.0-468-ge8e839253  # or whatever
    >>> help("modules")
    [ a whole lot ]
    >>> ^TQ
    $

    # now let's deploy the MoaT main 
    $ cd ..  # to go …/src/moat
    $ ./mt -c micro/deploy/esp.cfg micro -v setup.r.port $DEV -e setup.r.mode.rate $BAUD setup

    

Connect to the board and verify that it works.

Write a fallback configuration for your board. It typically looks like
this YAML file::

    setup: &ms
      mode: serial
      serial: &ps
        port: "/dev/ttyUSB0"
        mode: &rs
          rate: 115200
          guarded: true
          reliable: true

    apps:
      s: serial.Link
      pu: ports.UnixPort
    s: *ps
      # some boards might accept "tx" and "rx" port numbers
    pu: &ru
      port: "moat.fallback"
    cfg:
      my_brd:
        apps:
          wdt: wdt.WDTCmd
          m: serial.Link
          f: fs.Cmd
        m: 
          port: 0
          mode: *rs
        wdt:
          s: 3
          t: 10
    
    multiplex:
      my_brd: *ms
    connect:
      mode: unix
      unix: *ru

.. note::

    The ``&foo`` and ``*foo`` tags are used to re-use data. You can write
    your YAML file without them, but this way ensures that essentials like
    the serial port or the baud rate are only specified once, thus can't
    get out of sync when you change them.

The *reliable* flag means that the MoaT link needs a reliability layer.
If the board emulates a USB serial port, i.e. it has a USB plug that's
connected directly to the MCU and does *not* carry an FTDI chip or a
similar USB-to-serial converter, you can change the "reliable" setting to
False.

The *guarded* flag prefixes every message with the MsgPack character for
"invalid packet"; this further protects against corrupted messages and
allows UTF-8 characters in console messages. Without guarded mode, console
data are restricted to ASCII.

.. note::
    If you're using reliable mode without guard mode, console output will
    not work at all. Do this only if the MCU's serial port is not used
    for the normal Python console.

Now run the setup program::

    cd …/moat
    ./mt micro -c /your/config setup -S fbskip -m



