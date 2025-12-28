# Setting up MoaT-Micro

We're setting up a couple of microcontrollers that can run MicroPython.
Let's start with an ESP32-S3 named "Baguette", which is particularly
breadboard friendly. You can get it from
[The Pi Hut](https://thepihut.com/products/baguette-s3-esp32-s3-prototyping-board).

.. note::
    Not an affiliate link. Satisfied customer here.

## Prerequisites

For ESP you need the ESP-IDF. This step is documented
[here](https://docs.espressif.com/projects/esp-idf/en/stable/esp32s3/get-started/index.html). Briefly:

```shell
cd /src-or-wherever
sudo apt install git wget flex bison gperf python3-dev python3-pip python3-venv \
    cmake ninja-build ccache libffi-dev libssl-dev dfu-util libusb-1.0-0-dev
git clone https://github.com/espressif/esp-idf.git
cd esp-idf
git checkout v5.5.1
git submodule update --init --recursive
./install.sh esp32s3  # add other chips as documented
source ./export.sh
```

The last step adds the ESP-IDF environment to your current environment.

## Configuration

Next we need to create a configuration file:
```shell
$ mkdir -p src/moat; cd src/moat
$ cp /usr/share/moat-micro/examples/moat-micro/esp-baguette.cfg ./esp-s3.cfg
$ vi esp-s3.cfg
```

You will have to edit the serial ports, as your device is unlikely to have
a MAC of XX:XX:XX:XX:XX:XX. 🤪 Also, your WLAN is unlikely to be named
"MyNetworkSSID".

The "board" tag must name a directory in either
`moat/micro/embed/boards/esp32` or `micropython/ports/esp32/boards`.

## Installation

Save the config file, then run `moat -V -c ./esp-s3.cfg micro setup -i -U -s skip -N`.

- `-V`: more verbosity
- `-c`: config file
- `-i`: install MicroPython (the board must be in bootloader mode)
- `-U`: sync MoaT modules and `boot.py`/`main.py`
- `-s`: the mode to run MoaT runtime in; "skip" means don't
- `-N`: reboot after setting up all of the above

If the installation aborts with a traceback that ends with

```
serial.serialutil.SerialException: [Errno 2] could not open port /dev/serial/by-id/usb-Espressif_Systems_Espressif_Device_XXXXXXXXXXXX0000-if00: [Errno 2] No such file or directory: …
```

you seem to have found a problem with `esptool`: sometimes it doesn't
hard-reset the ESP32-S3 despite being told to do so. If that happens, press
the Reset button on the board (or disconnect it and then plug it back in),
then repeat the above command without the `-i` argument.

## Initial start

The start mode `skip` means "don't start MoaT"; we'd like to make sure that
network setup and basic MoaT commands work before we commit ourselves. This
is especially important on systems with a direct USB connection because
debugging them is somewhat difficult — if we're unlucky, they take the USB
link with them before the debug trace can be retrieved.

Thus, we start a terminal:

```
$ pyserial-miniterm -f direct /dev/serial/by-id/usb-Espressif_Systems_Espressif_Device_9c139eef88a80000-if00
--- Miniterm on /dev/serial/by-id/usb-Espressif_Systems_Espressif_Device_XXXXXXXXXXXX0000-if00  9600,8,N,1 ---
--- Quit: Ctrl+] | Menu: Ctrl+T | Help: Ctrl+T followed by Ctrl+H ---
MoaT state: 'skip'
MicroPython v1.27.0-65.g2d7c14a6f3.dirty on 2025-12-21; MoaT ESP32-S3 with ESP32S3
Type "help()" for more information.
>>>
```
Looks good. Sometimes the initial text isn't shown, but as long as you get
a Python prompt when you press the Return key, all is well. If not, maybe
the board is still in raw mode (press `Ctrl-B`) or confused (reset it).

Otherwise, let's go:
```
>>> import moat
>>> moat.go("once")
*** STATE *** once ***
Start MoaT: 'once'
WLAN. - 192.168.1.42
Setup :
MoaT is up.

```

You should now be able to ping the board:

```shell
$ ping 192.168.1.42
PING 192.168.1.42 (192.168.1.42) 56(84) bytes of data.
64 bytes from 10.107.2.134: icmp_seq=1 ttl=63 time=37.9 ms
64 bytes from 10.107.2.134: icmp_seq=2 ttl=63 time=61.0 ms
^C
```

So let's talk to it. First we establish a link:

```shell
$ mtc() {
> moat -c ./esp-s3.cfg micro "$@"
> }
$ mtc run
```

Nothing much seems to happen, but that's OK. In yet another terminal, let's
review our board's configuration:

```shell
$ moat -c ./esp-s3.cfg util cfg moat.micro.cfg.r -y
apps:
  c: cfg.Cmd
  f: fs.Cmd
  n: net.tcp.Port
  s: _sys.Cmd
n:
  host: 192.168.1.42
  port: 27589
net: [ your network config ]
```

Let's ask the board what it can do:

```shell
$ mtc cmd dir_
C: true
d:
  c: Cmd
  f: Cmd
  n: _Port
  s: Cmd
```

(TODO: those command names need fixing.)

`dir_` means "get a directory". The `d` in the response also means
`directory`. Let's list one of them:

```shell
$ mtc cmd s.dir_
c:
- boot
- eval
- ping
- [ some others ]
...
```

All commands on the board know their own documentation. It's not very
verbose because they don't have a lot of memory, but it's a start when you
don't remember how to talk to a command.

```shell
$ mtc cmd s.ping.doc_
_d: Reply test
_r:
  m: any:Return data
m: any:Return data
```

So this is a "reply test" command, it wants a parameter `m` which gets
returned.

```shell
$ mtc cmd s.ping -s m ~Hello
m: Hello
$ mtc cmd s.ping -s m =123
m: 123
$ mtc cmd s.ping -s m =123.45
m: 123.44999694824219
$
```
Floating point accuracy on the board is worse than on CPython, so this is
not a surprise. What happens when we do it wrong?

```shell
$ mtc cmd s.ping -s x =123
e: TypeError
```

Oops.

If you look at the terminal window, you see the error with a backtrace:

```
Command Error <Msg:L37 r=L38:   ['s', 'ping'] [] {'n': 123}>: TypeError("unexpected keyword argument 'n'",)
Traceback (most recent call last):
  File "moat/lib/cmd/msg.py", line 525, in call_simple
TypeError: unexpected keyword argument 'n'
```

That's not helpful if the board is located somewhere else and you don't
have a USB connection to it. To fix that, we want to access the REPL using
our MoaT link, but we'll get to that a bit later.

## File System

The "fs" in the configuration's `fs.Cmd` means "file system". Let's have a look:

```shell
$ mtc cmd fs.dir_
- ls
- stat
- open
- rd
- wr
- ...
```

Looks promising.

```shell
$ mtc cmd f.ls
- boot.py
- main.py
- moat.cfg
- moat.state
```

If we want to do this a lot this is likely to be tedious.
Fortunately there's a better way:

```shell
$ sudo mkdir /mnt/py
$ sudo chown $UID /mnt/py
$ mtc mount /mnt/py
```

Switch to another terminal:

```shell
$ ls /mnt/py
boot.py   main.py   moat.cfg   moat.state
$ moat util convert -i /mnt/py/moat.cfg -d cbor -e yaml
[ same config output as above ]
$ less /mnt/py/boot.py
```

So it seems that we can access the board's file system from our desktop,
with normal tools. Nice.

The other direction is on the TODO list.


## Python evaluation

`s.dir_` told us there's an "eval" command, so let's check that out:


```shell
$ mtc cmd -s + '~1+2'
3
```

The `~` says to evaluate the argument as a string; otherwise the command
interpreter might evaluate the number or term itself and just send the
result back and forth. In fact, we can watch the message exchange:

```shell
$ moat -c ./esp-s3.cfg \
    -l moat.micro.proto.stack=DEBUG -s moat.micro.connect.r.log.txt '!L' \
    micro cmd s.eval -s + '~12'
09:22:41.602 DEBUG moat.micro.proto.stack:S:L  +2 [['t', 's', 'eval'], '12']
09:22:41.686 DEBUG moat.micro.proto.stack:R:L  -2 [12]
12
$ moat -c ./esp-s3.cfg \
    -l moat.micro.proto.stack=DEBUG -s moat.micro.connect.r.log.txt '!L' \
    micro cmd s.eval -s + '3'
09:25:26.622 DEBUG moat.micro.proto.stack:S:L  +2 [['t', 's', 'eval'], 3]
09:25:26.866 DEBUG moat.micro.proto.stack:R:L  -2 [3]
3
```

Note the missing quotes in the second example, at the end of the `S:L` line.

Using this method we can send arbitrary Python commands and expressions and
get some results back. For interactive use, however, there's a better way.


## The REPL

MoaT is able to hijack the MicroPython prompt. So let's add a REPL app.

```shell
$ mtc cfg -S -s apps.repl ~stdio.console \
    -s  repl.keep =f -s repl.repl =t
$
```

The interesting part happens in the terminal:

```
MoaT is in the background.
>>>
```

You now can pretend everything is as before. The neat part is that all the
commands from above still work while you're typing on the serial link. (Try them!)

The REPL can be controlled remotely:

```shell
$ mtc cmd repl.r
!bin "MoaT is in the background.\r\n>>> "
$ mtc cmd repl.w -s + "=b'1+2+3+4\r'"
$ mtc cmd repl.r
!bin "1+2+3+4\r\n10\r\n>>> "
$
```

Again, that's not very user friendly — but we can do better:
```shell
$ mtc repl
>>> 1+2+3+4
10
>>>
```

(I lied; the last part is still on the TODO list.)
