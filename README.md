# SEW MOVITRAC modbus control

This is a simple controller for SEW MOVITRAC motor controllers.

## Instructions

Read section 10 of the controller's documentation
(that's the "installation" chapter).

Configure the controller.  Minimum initial configuration:

* P1-10: nominal motor speed in r/min.
* P1-01: max motor speed
* P1-02: min motor speed
* P1-07: motor voltage (V)
* P1-08: motor current (1/10 A)
* P1-09: motor AC frequency (50Hz)
* P4-01: control mode. See the documentation. You probably want 2.

* P1-12: 7 (Modbus)
* P1-15: 201 (extended control)
* P5-03: 0-4 (Baud rate, 9600 … 115200)
* P5-04: 0-3 (parity: no/no2/odd/even)
* P5-06: timeout in 1/10 sec, zero to disable (this is NOT recommended!)
* P5-09: 1 (speed as percentage of max)

Check that the motor can turn freely without injuring somebody
or breaking something. Check again.

Now connect the emergency switch. See section 6.3.2 in the documentation.
DO NOT proceed if this switch is not installed correctly.

The controller should now auto-tune its motor parameters. This takes
up to two minutes and may engage the motor. You can also trigger this process
manually by setting P4-02 to 1.

Write a config file along these lines::

    dev:
      sew:
        power: !P :mr.moat.sew.power
        state: !P :mr.moat.sew.state
        mqtt:
          codec: msgpack
          will:
            topic: !P :mr.moat.sew.state
            message: null
        modbus:
          port: "/dev/ttyUSB0"
          serial:
            rate: 19200
            parity: N
          unit: 1

Run "moat -c CONFIG dev sew run".

You now can operate the motor. Send a percentage to the topic `moat/dev/power`.
You definitely should use QOS=1.

Remember to use the correct encoding. If you don't like msgpack, use json.

## TODO

The ":mr" part in the paths means that they are interpreted as MQTT topics;
messages are sent without MoaT-KV attributes or retain flags.

This currently is (a) the default and (b) the only supported method,
but that may change.


