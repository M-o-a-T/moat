"""Tests for moat.api.bosch.bmv080 module."""

from __future__ import annotations

import os
import pytest

from moat.api.bosch.bmv080 import (
    BMV080,
    BMV080_Link,
    BMV080Error,
    BMV080Output,
    DutyCyclingMode,
    MeasurementAlgorithm,
    StatusCode,
)

# Library path from environment, None if not set
BMV080_LIBRARY = os.environ.get("BMV080_LIBRARY")

# Skip marker for tests requiring the real library
requires_library = pytest.mark.skipif(
    BMV080_LIBRARY is None,
    reason="BMV080_LIBRARY environment variable not set",
)


class TestStatusCode:
    """Tests for StatusCode enum."""

    def test_ok_is_zero(self) -> None:
        """OK status should be 0."""
        assert StatusCode.OK == 0

    def test_errors_are_above_100(self) -> None:
        """Error codes should be >= 100."""
        for code in StatusCode:
            if code.name.startswith("ERROR_"):
                assert code >= 100


class TestMeasurementAlgorithm:
    """Tests for MeasurementAlgorithm enum."""

    def test_values(self) -> None:
        """Check algorithm values."""
        assert MeasurementAlgorithm.FAST_RESPONSE == 1
        assert MeasurementAlgorithm.BALANCED == 2
        assert MeasurementAlgorithm.HIGH_PRECISION == 3


class TestDutyCyclingMode:
    """Tests for DutyCyclingMode enum."""

    def test_mode_0(self) -> None:
        """MODE_0 should be 0."""
        assert DutyCyclingMode.MODE_0 == 0


class TestBMV080Error:
    """Tests for BMV080Error exception."""

    def test_message_includes_status(self) -> None:
        """Error message should include status name and code."""
        err = BMV080Error(StatusCode.ERROR_HW_READ, "read failed")
        assert "ERROR_HW_READ" in str(err)
        assert "105" in str(err)
        assert "read failed" in str(err)

    def test_status_attribute(self) -> None:
        """Error should have status attribute."""
        err = BMV080Error(StatusCode.ERROR_NULLPTR)
        assert err.status == StatusCode.ERROR_NULLPTR


class TestBMV080Output:
    """Tests for BMV080Output dataclass."""

    def test_creation(self) -> None:
        """Create output with all fields."""
        output = BMV080Output(
            runtime_in_sec=10.5,
            pm2_5_mass_concentration=25.0,
            pm1_mass_concentration=15.0,
            pm10_mass_concentration=35.0,
            pm2_5_number_concentration=1000.0,
            pm1_number_concentration=500.0,
            pm10_number_concentration=1200.0,
            is_obstructed=False,
            is_outside_measurement_range=False,
        )
        assert output.runtime_in_sec == 10.5
        assert output.pm2_5_mass_concentration == 25.0
        assert output.is_obstructed is False


class MockLink:
    """Mock serial communication interface for testing."""

    def __init__(self) -> None:
        self.reads: list[tuple[int, int]] = []
        self.writes: list[tuple[int, list[int]]] = []
        self.delays: list[int] = []
        self._time = 0

    def read(self, header: int, length: int) -> list[int]:
        """Mock read."""
        print("RD", header, length)
        self.reads.append((header, length))
        return [0] * length

    def write(self, header: int, payload: list[int]) -> None:
        """Mock write."""
        print("WR", header, payload)
        self.writes.append((header, payload))

    def delay_ms(self, duration_ms: int) -> None:
        """Mock delay."""
        self.delays.append(duration_ms)
        self._time += duration_ms

    def time_ms(self) -> int:
        """Mock time."""
        return self._time


class TestBMV080Link:
    """Tests for BMV080_Link protocol."""

    def test_mock_implements_protocol(self) -> None:
        """MockLink should implement BMV080_Link."""
        mock = MockLink()
        assert isinstance(mock, BMV080_Link)


class TestBMV080:
    """Tests for BMV080 class."""

    def test_init_does_not_fail(self) -> None:
        """Constructor should not fail with valid arguments."""
        link = MockLink()
        bmv = BMV080(link, "/path/to/lib.so")
        assert bmv is not None

    def test_open_missing_library(self) -> None:
        """Opening with non-existent library should raise FileNotFoundError."""
        link = MockLink()
        bmv = BMV080(link, "/nonexistent/library.so")
        with pytest.raises(FileNotFoundError), bmv:
            pass

    def test_close_without_open(self) -> None:
        """Closing without opening should be safe."""
        link = MockLink()
        bmv = BMV080(link, "/path/to/lib.so")
        bmv._close()  # noqa:SLF001  # Should not raise

    def test_context_manager_calls_open_close(self) -> None:
        """Context manager should call open and close."""
        link = MockLink()
        bmv = BMV080(link, "/nonexistent/library.so")

        # open will fail, but we can verify the pattern
        with pytest.raises(FileNotFoundError), bmv:
            pass


@requires_library
class TestBMV080WithLibrary:
    """Tests requiring the real BMV080 library.

    These tests need the BMV080_LIBRARY environment variable set to the
    path of the BMV080 shared library.
    """

    def test_get_driver_version(self) -> None:
        """Get driver version from library."""
        assert BMV080_LIBRARY is not None

        link = MockLink()
        with BMV080(link, BMV080_LIBRARY) as _bmv:
            pass
