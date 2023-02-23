# MoaT micro

This module contains code to talk to MoaT satellites running MicroPython.

## Supported devices

Basically, anything that can run MicroPython and has barely enough RAM.

This does include the ESP8266, though you need to compile the MoaT support
code directly into Flash.

## Message structure

Messages are encoded using MsgPack dicionaries.

## Supported links

Either serial console or TCP works.

### TCP

The default is port 27587. We directly send MsgPack messages; they're
self-terminating, thus no length bytes or related silliness is required.

### Serial data

Serial data come in two flavors, either lossy (your basic UART signal) or
lossless (the microcontroller emulates a serial interface over USB).

In the first case we use the `SerialPacker` module, with a start byte,
to transmit single MsgPack messages. (Anything not introduced with the
start byte is console output.) On top of this we add basic recovery.

For the second case we can use a MsgPack data stream directly. As MsgPack
encodes integers (0…127) as single bytes, we also can interleave console
output with our messages.

## Shared link

The connection to the microcontroller is a 1:1 link. (This is obvious when
using serial data, but using just one TCP connection also conserves
controller memory.)

In order to support multiple parallel usages, a simple multiplexing
protocol allows clients to connect using a Unix-domain socket.

## Modular applications

As controllers have different functions, it's possible – and in fact quite
simple – to send specialized applications to it.

Applications are activated using a configuration file which can be updated
remotely.

Modules can use all resources on the controller but should be careful not
to use blocking code if possible.

In order to support long-running applications and complex operations for which
the controller isn't suited, application modules can also run on the muktiplexer.

### File system access

The LittteFS file system on the client can be mounted on the server via
FUSE.

