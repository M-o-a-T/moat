from __future__ import annotations

import anyio
import logging
import sys
import time
from pathlib import Path

from gpiod import Chip as _Chip
from gpiod import LineSettings, is_gpiochip_device
from gpiod.edge_event import EdgeEvent
from gpiod.line import Bias, Direction, Drive, Edge, Value

from typing import TYPE_CHECKING, Any, NoReturn, Self

if TYPE_CHECKING:
    from types import TracebackType

Type = EdgeEvent.Type

__all__ = ["Bias", "Chip", "Direction", "Drive", "Edge", "Type"]

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

    _chip: _Chip | None = None
    __chip: _Chip | None = None

    def __init__(
        self, num: int | None = None, label: str | None = None, consumer: str = sys.argv[0]
    ) -> None:
        if (num is None) == (label is None):
            raise ValueError("Specify either label or num")
        self._num = num
        self._label = label
        self._consumer = consumer

    def __repr__(self) -> str:
        if self._label is None:
            return f"{self.__class__.__name__}({self._num})"
        else:
            return f"{self.__class__.__name__}({self._label})"

    def _current_chip(self) -> _Chip:
        chip = self._chip
        if chip is None:
            raise RuntimeError("Chip is not open", self)
        return chip

    @property
    def name(self) -> str:
        "name (NOT the file name)"
        return self._current_chip().get_info().name

    @property
    def num_lines(self) -> int:
        "#lines on this chip"
        return self._current_chip().get_info().num_lines

    @property
    def label(self) -> str:
        "Label"
        return self._current_chip().get_info().label

    @property
    def consumer(self) -> str:
        "Consumer"
        return self._consumer

    def __enter__(self) -> Self:
        chip: _Chip | None = None
        try:
            if self._label is None:
                chip = _Chip(f"/dev/gpiochip{self._num}")
            else:
                for name in Path("/dev/").glob("gpiochip*"):
                    if not is_gpiochip_device(str(name)):
                        continue
                    try:
                        chip = _Chip(str(name))
                    except Exception as exc:
                        _logger.warning("unable to open %r: %s", str(name), repr(exc))
                        continue
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

        if chip is None:
            raise RuntimeError("GPIO chip could not be opened")
        self._chip = chip.__enter__()
        self.__chip = chip
        return self

    async def __aenter__(self) -> Self:
        return self.__enter__()

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> bool | None:
        chip = self.__chip
        if chip is None:
            return None
        try:
            return chip.__exit__(exc_type, exc, tb)
        finally:
            self.__chip = self._chip = None

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> bool | None:
        return self.__exit__(exc_type, exc, tb)

    def line(self, offset: int, consumer: str | None = None, **kw: Any) -> Line:
        """Get a descriptor for a single GPIO line.

        Arguments:
            offset: GPIO number within this chip. No default.
            consumer: override the chip's consumer, if required.
        """
        if consumer is None:
            consumer = self._consumer
        return Line(self._current_chip(), offset, consumer=consumer, **kw)


class Line:
    """Represents a single GPIO line.

    Create this object by calling :meth:`Chip.line`.
    """

    def __init__(
        self,
        chip: _Chip,
        offset: int,
        consumer: str = sys.argv[0][:-3],
        settings: LineSettings | None = None,
        **kw: Any,
    ) -> None:
        self._chip = chip
        self._offset = offset
        self._consumer = consumer.encode("utf-8", errors="surrogateescape")
        self._line: Any | None = None
        if settings is not None and kw:
            raise TypeError("Either implicit or explicit settings please.")
        if settings is None:
            settings = LineSettings(direction=Direction.INPUT)
        self._settings = settings
        for k, v in kw.items():
            setattr(self._settings, k, v)

    def __repr__(self) -> str:
        return "<%s %s:%d %s>" % (  # noqa:UP031
            self.__class__.__name__,
            self._chip,
            self._offset,
            self._line,
        )

    def open(self, direction: bool | Direction | None = None) -> Self:
        """
        Create a context manager for controlling this line's input or output.

        Arguments:
            direction: input or output. Default: Direction.INPUT.
            settings: LineSettings for fine control

        Example::

            with gpio.Chip(0) as chip:
                line = chip.line(16)
                with line.open(direction=Direction.INPUT) as wire:
                    print(wire.value)
        """
        if self._line is not None:
            raise OSError("This line is already in use")
        if not isinstance(direction, Direction):
            if direction is None:
                direction = self._settings.direction
            else:
                direction = Direction.OUTPUT if direction else Direction.INPUT
        self._settings.direction = direction
        return self

    def monitor(self, type: Edge | bool | None = Edge.BOTH) -> Self:  # noqa: A002
        """
        Monitor events on this line.

        Arguments:
            type: which edge(s) to monitor
            flags: REQUEST_FLAG_* values (ORed)

        Usage::

            with gpio.Chip(0) as chip, chip.line(13).monitor() as line:
                async for event in line:
                    print(event)
        """
        if self._line is not None:
            raise OSError("This line is already in use")
        if type is None:
            type = Edge.BOTH  # noqa:A001
        elif isinstance(type, bool):
            type = Edge.RISING if type else Edge.FALLING  # noqa:A001
        self._settings.edge_detection = type
        return self

    def __enter__(self) -> Self:
        """Context management for use with :meth:`open` and :meth:`monitor`."""
        if self._line is not None:
            raise OSError("This line is already in use")
        line = self._chip.request_lines({(self._offset,): self._settings})

        try:
            line.__enter__()
        except BaseException:
            line.release()
            raise

        self._line = line
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if self._line is not None:
            try:
                self._line.release()
            finally:
                self._line = None

    def _is_open(self) -> None:
        if self._line is None:
            raise RuntimeError("Line is not open", self)

    def _current_line(self) -> Any:
        line = self._line
        if line is None:
            raise RuntimeError("Line is not open", self)
        return line

    @property
    def value(self) -> bool:
        "Value"
        return bool(self._current_line().get_value(self._offset))

    @value.setter
    def value(self, value: bool) -> None:
        "Set Value"
        self._current_line().set_value(self._offset, Value.ACTIVE if value else Value.INACTIVE)

    @property
    def direction(self) -> bool:
        if self._line is None:
            return self._settings.direction == Direction.OUTPUT
        return self._chip.get_line_info(self._offset).direction == Direction.OUTPUT

    @property
    def active_low(self) -> bool:
        return self._chip.get_line_info(self._offset).active_low

    @property
    def is_pull_up(self) -> bool:
        "True if configured with pull-up"
        return self._chip.get_line_info(self._offset).bias == Bias.PULL_UP

    @property
    def is_pull_down(self) -> bool:
        "True if configured with pull-down"
        return self._chip.get_line_info(self._offset).bias == Bias.PULL_DOWN

    @property
    def is_open_none(self) -> bool:
        "True if configured with pull-down"
        return self._chip.get_line_info(self._offset).drive == Drive.PUSH_PULL

    @property
    def is_open_drain(self) -> bool:
        "True if configured as open-drain"
        return self._chip.get_line_info(self._offset).drive == Drive.OPEN_DRAIN

    @property
    def is_open_source(self) -> bool:
        "True if configured as open-source"
        return self._chip.get_line_info(self._offset).drive == Drive.OPEN_SOURCE

    @property
    def is_used(self) -> bool:
        "True if in use"
        return self._chip.get_line_info(self._offset).used

    @property
    def offset(self) -> int:
        "Offset"
        return self._offset

    @property
    def name(self) -> str:
        "Name"
        return self._chip.get_line_info(self._offset).name

    @property
    def consumer(self) -> str:
        return self._chip.get_line_info(self._offset).consumer

    def __iter__(self) -> NoReturn:
        raise RuntimeError("You need to use 'async for', not 'for'")

    async def __aenter__(self) -> NoReturn:
        raise RuntimeError("You need to use 'with', not 'async with'")

    async def __aexit__(self, *_: object) -> NoReturn:
        raise RuntimeError("You need to use 'with', not 'async with'")

    def __aiter__(self) -> Self:
        if self._settings.edge_detection == Edge.NONE:
            raise RuntimeError("You need to call 'with LINE.monitor()'")
        return self

    async def __anext__(self) -> Event:
        line = self._current_line()
        await anyio.wait_readable(line.fd)
        res = line.read_edge_events(max_events=1)
        return Event(res[0])

    async def aclose(self) -> None:
        """close the iterator."""
        pass


class Event:
    """Store a Pythonic representation of an event"""

    value: bool

    def __init__(self, ev: EdgeEvent) -> None:
        if ev.event_type == Type.RISING_EDGE:
            self.value = True
        elif ev.event_type == Type.FALLING_EDGE:
            self.value = False
        else:
            raise RuntimeError("Unknown event type", ev)
        self._ts = ev.timestamp_ns

    @property
    def timestamp(self) -> int:
        """nanosecond timestamp, TIME_MONOTONIC"""
        return self._ts

    @property
    def time(self) -> float:
        """Return the event's wall-clock time"""
        now_bns = time.clock_gettime_ns(time.CLOCK_MONOTONIC)
        return time.time() - (now_bns - self._ts) / 1000000000

    def __repr__(self) -> str:
        return f"<{self.value} @{self.time}>"
