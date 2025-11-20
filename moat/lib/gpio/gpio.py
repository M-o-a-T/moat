from __future__ import annotations  # noqa: D100

import anyio
import datetime
import logging
import sys
from pathlib import Path

import gpiod

_logger = logging.getLogger(__name__)


class Chip:
    """Represents a GPIO chip.

    Arguments:
        label: Chip label. Run "gpiodetect" to list GPIO chip labels.

        num: Chip number. Deprecated. Defaults to zero.
            Only used if you don't use a label.

        consumer: A string for display by kernel utilities.
            Defaults to the program name.

    """

    _chip = None

    def __init__(self, num=None, label=None, consumer=sys.argv[0]):
        if (num is None) == (label is None):
            raise ValueError("Specify either label or num")
        self._num = num
        self._label = label
        self._consumer = consumer

    def __repr__(self):
        if self._label is None:
            return f"{self.__class__.__name__}({self._num})"
        else:
            return f"{self.__class__.__name__}({self._label})"

    def __enter__(self):
        chip = None
        try:
            if self._label is None:
                chip = gpiod.Chip("/dev/gpiochip{self._num}")
            else:
                for name in Path("/dev/").glob("gpiochip*"):
                    if not gpiod.is_gpiochip_device(str(name)):
                        continue
                    try:
                        chip = gpiod.Chip(str(name))
                    except Exception as exc:
                        _logger.warning("unable to open %r: %s", str(name), repr(exc))
                    info = chip.get_info()
                    if info.label == self._label:
                        break
                    chip.close()
                    chip = None
                else:
                    raise RuntimeError(f"GPIO chip {self._label!r} not found")

        except BaseException:
            if chip is not None:
                chip.close()
            raise

        self._chip = chip
        return self

    def __exit__(self, *tb):
        gpiod.chip_close(self._chip)
        self._chip = None

    def line(self, offset, consumer=None):
        """Get a descriptor for a single GPIO line.

        Arguments:
            offset: GPIO number within this chip. No default.
            consumer: override the chip's consumer, if required.
        """
        if consumer is None:
            consumer = self._consumer
        return Line(self._chip, offset, consumer=consumer)


_FREE = 0
_PRE_IO = 1
_IN_IO = 2
_PRE_EV = 3
_IN_EV = 4
_IN_USE = {_IN_IO, _IN_EV}


class Line:
    """Represents a single GPIO line.

    Create this object by calling :meth:`Chip.line`.
    """

    _line = None
    _direction = None
    _default = None
    _flags = None
    _ev_flags = None
    _state = _FREE

    _type = None

    def __init__(self, chip, offset, consumer=sys.argv[0][:-3]):
        self._chip = chip
        self._offset = offset
        self._consumer = consumer.encode("utf-8")

    def __repr__(self):
        return "<%s %s:%d %s=%d>" % (  # noqa:UP031
            self.__class__.__name__,
            self._chip,
            self._offset,
            self._line,
            self._state,
        )

    def open(self, direction=gpiod.line.Direction.INPUT, default=False, flags=0):
        """
        Create a context manager for controlling this line's input or output.

        Arguments:
            direction: input or output. Default: gpiod.line.Direction.INPUT.
            flags: to request pull-up/down resistors or open-collector outputs.

        Example::
            with gpio.Chip(0) as chip:
                line = chip.line(16)
                with line.open(direction=gpiod.line.Direction.INPUT) as wire:
                    print(wire.value)
        """
        if self._state in _IN_USE:
            raise OSError("This line is already in use")
        self._direction = direction
        self._default = default
        self._flags = flags
        self._state = _PRE_IO
        return self

    def __enter__(self):
        """Context management for use with :meth:`open` and :meth:`monitor`."""
        if self._state in _IN_USE:
            raise OSError("This line is already in use")
        if self._state == _FREE:
            raise RuntimeError("You need to call .open() or .monitor()")
        self._line = self._chip.request_lines({self._offset: gpiod.line.Direction.INPUT})

        if self._state == _PRE_IO:
            self._enter_io()
        elif self._state == _PRE_EV:
            self._enter_ev()
        else:
            raise RuntimeError("wrong state", self)
        try:
            self._line.__enter__()
        except BaseException:
            self._line.release()
            raise

        return self

    def _enter_io(self):
        self._state = _IN_IO
        return self

    def _enter_ev(self):
        self._state = _IN_EV

    def __exit__(self, *tb):
        if self._line is not None:
            try:
                gpiod.line_release(self._line)
            finally:
                self._line = None
        self._state = _FREE

    def _is_open(self):
        if self._state not in _IN_USE:
            raise RuntimeError("Line is not open", self)

    @property
    def value(self) -> bool:
        "Value"
        return bool(self._line.get_value(self._offset))

    @value.setter
    def value(self, value):
        "Set Value"
        gpiod.line_set_value(
            self._line, gpiod.line.Value.ACTIVE if value else gpiod.line.Value.INACTIVE
        )

    @property
    def direction(self) -> bool:  # noqa: D102
        if self._line is None:
            return self._direction
        return gpiod.line_direction(self._line)

    @property
    def active_state(self):  # noqa: D102
        self._is_open()
        return gpiod.line_active_state(self._line)

    @property
    def is_open_drain(self) -> bool:
        "True if configured as open-drain"
        return self._chip.get_line_info(self._offset).drive == gpiod.line.Drive.OPEN_DRAIN

    @property
    def is_open_source(self):
        "True if configured as open-source"
        return self._chip.get_line_info(self._offset).drive == gpiod.line.Drive.OPEN_SOURCE

    @property
    def is_used(self) -> bool:
        "True if in use"
        return self._chip.get_line_info(self._offset).used

    @property
    def offset(self) -> int:
        "Offset"
        return self._offset

    @property
    def name(self):
        "Name"
        return self._chip.get_line_info(self._offset).name

    @property
    def consumer(self):  # noqa: D102
        return self._chip.get_line_info(self._offset).consumer

    def monitor(self, type=gpiod.line.Edge.BOTH, flags=0):  # noqa: A002
        """
        Monitor events.

        Arguments:
            type: which edge(s) to monitor
            flags: REQUEST_FLAG_* values (ORed)

        Usage::

            with gpio.Chip(0) as chip:
                with chip.line(13).monitor() as line:
                    async for event in line:
                        print(event)
        """
        if self._state in _IN_USE:
            raise OSError("This line is already in use")
        self._state = _PRE_EV
        self._type = type
        self._flags = flags
        return self

    def _update(self):
        self._is_open()
        if gpiod.line_update(self._line) == -1:
            raise OSError("unable to update state")

    def __iter__(self):
        raise RuntimeError("You need to use 'async for', not 'for'")

    async def __aenter__(self):
        raise RuntimeError("You need to use 'with', not 'async with'")

    async def __aexit__(self, *_):
        raise RuntimeError("You need to use 'with', not 'async with'")

    def __aiter__(self):
        if self._state != _IN_EV:
            raise RuntimeError("You need to call 'with LINE.monitor() / async for event in LINE'")
        return self

    async def __anext__(self):
        if self._state != _IN_EV:
            raise RuntimeError("wrong state")

        await anyio.wait_readable(self._line.fd)
        res = self._line.read_edge_events(max_events=1)
        return Event(res[0])

    async def aclose(self):
        """close the iterator."""
        pass


class Event:
    """Store a Pythonic representation of an event"""

    def __init__(self, ev):
        if ev.event_type == gpiod.EdgeEvent.Type.RISING_EDGE:
            self.value = 1
        elif ev.event_type == gpiod.EdgeEvent.Type.FALLING_EDGE:
            self.value = 0
        else:
            raise RuntimeError("Unknown event type")
        self._ts_sec = ev.ts.tv_sec
        self._ts_nsec = ev.ts.tv_nsec

    @property
    def timestamp(self):
        """Return a (second,nanosecond) tuple for fast timestamping"""
        return (self._ts_sec, self._ts_nsec)

    @property
    def time(self):
        """Return the event's proper datetime"""
        return datetime.datetime.fromtimestamp(
            self._ts_sec + self._ts_nsec / 1000000000, tz=datetime.UTC
        )

    def __repr__(self):
        return f"<{self.value} @{self.time}>"
