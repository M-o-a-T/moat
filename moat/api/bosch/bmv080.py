"""
CFFI-based interface to the Bosch BMV080 particulate matter sensor.

This module provides a Python wrapper around the BMV080 C library,
allowing measurement of PM1, PM2.5, and PM10 concentrations.
"""

from __future__ import annotations

import os
from anyio import ContextManagerMixin
from contextlib import contextmanager
from dataclasses import dataclass
from enum import IntEnum

from moat.api._dll import DLL

from typing import TYPE_CHECKING, Protocol, Self, runtime_checkable

if TYPE_CHECKING:
    from cffi import FFI

    from collections.abc import Generator

__all__ = [
    "BMV080",
    "BMV080Error",
    "BMV080Output",
    "BMV080_Link",
    "DutyCyclingMode",
    "MeasurementAlgorithm",
    "StatusCode",
]

# Required library version: >= 11.2.0, < 12.0.0
_MIN_VERSION = (24, 2, 0)
_MAX_VERSION = (25, 0, 0)


class StatusCode(IntEnum):
    """Status codes returned by the BMV080 sensor driver."""

    OK = 0

    # Warnings
    WARNING_INVALID_REG_READ = 1
    WARNING_INVALID_REG_WRITE = 2
    WARNING_FIFO_READ = 3
    WARNING_FIFO_EVENTS_OVERFLOW = 4
    WARNING_FIFO_SW_BUFFER_SIZE = 208
    WARNING_FIFO_HW_BUFFER_SIZE = 209

    # Errors
    ERROR_NULLPTR = 100
    ERROR_REG_ADDR = 101
    ERROR_PARAM_LOCKED = 179
    ERROR_PARAM_INVALID = 115
    ERROR_PARAM_INVALID_CHANNEL = 102
    ERROR_PARAM_INVALID_VALUE = 123
    ERROR_PARAM_INVALID_INTERNAL_CONFIG = 104
    ERROR_PRECONDITION_UNSATISFIED = 180
    ERROR_HW_READ = 105
    ERROR_HW_WRITE = 106
    ERROR_MISMATCH_CHIP_ID = 107
    ERROR_MISMATCH_REG_VALUE = 160
    ERROR_OPERATION_MODE_INVALID = 116
    ERROR_OPERATION_MODE_CHANGE = 113
    ERROR_OPERATION_MODE_CHANNELS_OUT_OF_SYNC = 114
    ERROR_ASIC_NOT_CONFIGURED = 157
    ERROR_MEM_READ = 133
    ERROR_MEM_ADDRESS = 135
    ERROR_MEM_CMD = 136
    ERROR_MEM_TIMEOUT = 137
    ERROR_MEM_INVALID = 138
    ERROR_MEM_OBSOLETE = 139
    ERROR_MEM_OPERATION_MODE = 140
    ERROR_MEM_DATA_INTEGRITY = 153
    ERROR_MEM_DATA_INTEGRITY_INTERNAL_TEST_1 = 154
    ERROR_MEM_INTERNAL_TEST_1 = 156
    ERROR_MEM_DATA_INTEGRITY_INTERNAL_TEST_2 = 159
    ERROR_MEM_INTERNAL_TEST_2 = 181
    ERROR_FIFO_FORMAT = 210
    ERROR_FIFO_EVENTS_COUNT_SATURATED = 213
    ERROR_FIFO_UNAVAILABLE = 174
    ERROR_FIFO_EVENTS_COUNT_DIFF = 214
    ERROR_SYNC_COMM = 161
    ERROR_SYNC_CTRL = 162
    ERROR_SYNC_MEAS = 163
    ERROR_SYNC_LOCKED = 164
    ERROR_DC_CANCEL_RANGE = 165
    ERROR_DC_ESTIM_RANGE = 166
    ERROR_LPWR_T = 167
    ERROR_LPWR_RANGE = 168
    ERROR_POWER_DOMAIN = 169
    ERROR_HEADROOM_VDDL = 170
    ERROR_HEADROOM_LDV_OUTPUT = 171
    ERROR_HEADROOM_LDV_REF = 172
    ERROR_HEADROOM_INTERNAL = 173
    ERROR_SAFETY_PRECAUTION = 120
    ERROR_TIMESTAMP_DIFFERENCE = 211
    ERROR_TIMESTAMP_OVERFLOW = 212
    ERROR_LIB_VERSION_INCOMPATIBLE = 300
    ERROR_INTERNAL_PARAMETER_VERSION_INVALID = 301
    ERROR_INTERNAL_PARAMETER_INDEX_INVALID = 302
    ERROR_MEMORY_ALLOCATION = 403
    ERROR_CALLBACK_DELAY = 303
    ERROR_INCOMPATIBLE_SENSOR_HW = 418


class MeasurementAlgorithm(IntEnum):
    """Measurement algorithm choices."""

    FAST_RESPONSE = 1
    BALANCED = 2
    HIGH_PRECISION = 3


class DutyCyclingMode(IntEnum):
    """Modes of performing a duty cycling measurement."""

    MODE_0 = 0  # Fixed duty cycle, ON time = integration_time, OFF time = sleep time


class BMV080Error(Exception):
    """Exception raised for BMV080 errors."""

    def __init__(self, status: StatusCode, message: str = "") -> None:
        self.status = status
        name_val = f"{status.name} ({status.value})"
        super().__init__(f"{name_val}: {message}" if message else name_val)


@dataclass
class BMV080Output:
    """Output data from BMV080 sensor measurement.

    Attributes:
        runtime_in_sec: Estimate of time passed since measurement start, in seconds.
        pm2_5_mass_concentration: PM2.5 value in µg/m³.
        pm1_mass_concentration: PM1 value in µg/m³.
        pm10_mass_concentration: PM10 value in µg/m³.
        pm2_5_number_concentration: PM2.5 value in particles/cm³.
        pm1_number_concentration: PM1 value in particles/cm³.
        pm10_number_concentration: PM10 value in particles/cm³.
        is_obstructed: Whether the sensor is obstructed.
        is_outside_measurement_range: Whether PM2.5 is outside 0..1000 µg/m³.
    """

    runtime_in_sec: float
    pm2_5_mass_concentration: float
    pm1_mass_concentration: float
    pm10_mass_concentration: float
    pm2_5_number_concentration: float
    pm1_number_concentration: float
    pm10_number_concentration: float
    is_obstructed: bool
    is_outside_measurement_range: bool


@runtime_checkable
class BMV080_Link(Protocol):
    """Protocol for serial communication interface to BMV080.

    The caller must provide an object implementing these methods.
    """

    def read(self, header: int, length: int) -> list[int]:
        """Read data from the sensor.

        Args:
            header: 16-bit header information.
            length: Number of 16-bit words to read.

        Returns:
            List of 16-bit words read from sensor.

        Raises:
            IOError: If read fails.
        """
        ...

    def write(self, header: int, payload: list[int]) -> None:
        """Write data to the sensor.

        Args:
            header: 16-bit header information.
            payload: List of 16-bit words to write.

        Raises:
            IOError: If write fails.
        """
        ...

    def delay_ms(self, duration_ms: int) -> None:
        """Delay for specified milliseconds.

        Args:
            duration_ms: Duration in milliseconds.
        """
        ...

    def time_ms(self) -> int:
        """Get current tick value in milliseconds.

        Returns:
            Current tick value for timing purposes.
        """
        ...


# C declarations for CFFI
_CDEF = """
typedef int8_t bmv080_status_code_t;
typedef void* bmv080_handle_t;
typedef void* bmv080_sercom_handle_t;

typedef enum {
    E_BMV080_DUTY_CYCLING_MODE_0 = 0
} bmv080_duty_cycling_mode_t;

typedef enum {
    E_BMV080_MEASUREMENT_ALGORITHM_FAST_RESPONSE = 1,
    E_BMV080_MEASUREMENT_ALGORITHM_BALANCED = 2,
    E_BMV080_MEASUREMENT_ALGORITHM_HIGH_PRECISION = 3
} bmv080_measurement_algorithm_t;

struct bmv080_extended_info_s;

typedef struct {
    float runtime_in_sec;
    float pm2_5_mass_concentration;
    float pm1_mass_concentration;
    float pm10_mass_concentration;
    float pm2_5_number_concentration;
    float pm1_number_concentration;
    float pm10_number_concentration;
    bool is_obstructed;
    bool is_outside_measurement_range;
    float reserved_0;
    float reserved_1;
    float reserved_2;
    struct bmv080_extended_info_s *extended_info;
} bmv080_output_t;

typedef int8_t(*bmv080_callback_read_t)(bmv080_sercom_handle_t sercom_handle, uint16_t header,
    uint16_t* payload, uint16_t payload_length);
typedef int8_t(*bmv080_callback_write_t)(bmv080_sercom_handle_t sercom_handle, uint16_t header,
    const uint16_t* payload, uint16_t payload_length);
typedef int8_t(*bmv080_callback_delay_t)(uint32_t duration_in_ms);
typedef uint32_t(*bmv080_callback_tick_t)(void);
typedef void(*bmv080_callback_data_ready_t)(bmv080_output_t bmv080_output,
    void* callback_parameters);

bmv080_status_code_t bmv080_open(bmv080_handle_t* handle,
    const bmv080_sercom_handle_t sercom_handle, const bmv080_callback_read_t read,
    const bmv080_callback_write_t write, const bmv080_callback_delay_t delay_ms);

bmv080_status_code_t bmv080_get_driver_version(uint16_t* major, uint16_t* minor, uint16_t* patch,
    char git_hash[12], int32_t* num_commits_ahead);

bmv080_status_code_t bmv080_reset(const bmv080_handle_t handle);

bmv080_status_code_t bmv080_get_parameter(const bmv080_handle_t handle,
    const char* key, void* value);

bmv080_status_code_t bmv080_set_parameter(const bmv080_handle_t handle, const char* key,
    const void* value);

bmv080_status_code_t bmv080_get_sensor_id(const bmv080_handle_t handle, char id[13]);

bmv080_status_code_t bmv080_start_continuous_measurement(const bmv080_handle_t handle);

bmv080_status_code_t bmv080_start_duty_cycling_measurement(const bmv080_handle_t handle,
    const bmv080_callback_tick_t get_tick_ms, bmv080_duty_cycling_mode_t duty_cycling_mode);

bmv080_status_code_t bmv080_serve_interrupt(const bmv080_handle_t handle,
    bmv080_callback_data_ready_t data_ready, void* callback_parameters);

bmv080_status_code_t bmv080_stop_measurement(const bmv080_handle_t handle);

bmv080_status_code_t bmv080_close(bmv080_handle_t* handle);
"""


class BMV080(ContextManagerMixin):
    """CFFI-based interface to the BMV080 particulate matter sensor.

    This class wraps the BMV080 C library, providing a Pythonic interface
    for measuring particulate matter concentrations.

    Args:
        link: Serial communication interface implementing read/write/delay_ms/time_ms.
        libs_path: Path to the BMV080 shared libraries (.so/.dll). The lib_postProcessor.so
            library must be loaded first.

    Example:
        >>> class MySPI:
        ...     def read(self, header, length): ...
        ...     def write(self, header, payload): ...
        ...     def delay_ms(self, ms): ...
        ...     def time_ms(self): ...
        >>> with BMV080(MySPI(), "/path/to/libbmv080.so") as sensor:
        ...     sensor.start_continuous_measurement()
        ...     sensor.serve_interrupt()
        ...     sensor.stop_measurement()
    """

    def __init__(self, link: BMV080_Link, libs_path: str) -> None:
        """Initialize BMV080 interface.

        Args:
            link: Object with read/write/delay_ms/time_ms methods.
            libs_path: Paths to the BMV080 shared libraries, colon-separated
                (use semicolon on Windows).
        """
        self._link = link
        self._libs_path = libs_path

        self._ffi: FFI | None = None
        self._lib = None
        self._handle = None
        self._handle_ptr = None

        # Store callbacks to prevent garbage collection
        self._read_cb = None
        self._write_cb = None
        self._delay_cb = None
        self._tick_cb = None
        self._data_ready_cb = None

        # Store exception from callback for re-raising
        self._logged_exc: BaseException | None = None

    @contextmanager
    def __contextmanager__(self) -> Generator[Self]:
        with DLL("moat.api.bosch.bmv080", _CDEF, *self._libs_path.split(os.pathsep)) as (
            self._ffi,
            self._lib,
        ):
            try:
                self._open()
                yield self
            finally:
                self._close()

    def _log_exc(self, exc: BaseException) -> None:
        """Store an exception from a callback for later re-raising.

        Args:
            exc: The exception to store.
        """
        if self._logged_exc is None:
            self._logged_exc = exc

    def _check_status(self, status: int) -> None:
        """Check status code and raise exception if error.

        Args:
            status: Status code from C library.

        Raises:
            BMV080Error: If status indicates an error (>= 100).
            BaseException: Re-raises stored callback exception if status is -1.
        """
        if status == -1 and self._logged_exc is not None:
            exc = self._logged_exc
            self._logged_exc = None
            raise exc
        if status >= 100:
            raise BMV080Error(StatusCode(status))

    def _open(self) -> None:
        """Open connection to the BMV080 sensor.

        Initializes the C library and creates a sensor handle.
        Verifies that the library version is compatible (>= 11.2, < 12).

        Raises:
            BMV080Error: If opening fails.
            FileNotFoundError: If library file not found.
            RuntimeError: If library version is incompatible.
        """
        if self._handle is not None:
            return

        # Check library version before proceeding
        version = self._get_driver_version_raw()
        if version < _MIN_VERSION or version >= _MAX_VERSION:
            min_str = ".".join(str(x) for x in _MIN_VERSION)
            max_str = ".".join(str(x) for x in _MAX_VERSION)
            ver_str = ".".join(str(x) for x in version)
            raise RuntimeError(
                f"BMV080 library version {ver_str} not supported "
                f"(requires >= {min_str}, < {max_str})"
            )

        # Create callbacks
        # sercom_handle is passed by the C library but unused; we use self._link
        @self._ffi.callback("bmv080_callback_read_t")
        def read_cb(
            sercom_handle: object,  # noqa: ARG001
            header: int,
            payload: object,
            length: int,
        ) -> int:
            try:
                data = self._link.read(header, length)
                for i, val in enumerate(data[:length]):
                    payload[i] = val
                return 0
            except BaseException as exc:
                self._log_exc(exc)
                return -1

        @self._ffi.callback("bmv080_callback_write_t")
        def write_cb(
            sercom_handle: object,  # noqa: ARG001
            header: int,
            payload: object,
            length: int,
        ) -> int:
            try:
                data = [payload[i] for i in range(length)]
                self._link.write(header, data)
                return 0
            except BaseException as exc:
                self._log_exc(exc)
                return -1

        @self._ffi.callback("bmv080_callback_delay_t")
        def delay_cb(duration_ms: int) -> int:
            try:
                self._link.delay_ms(duration_ms)
                return 0
            except BaseException as exc:
                self._log_exc(exc)
                return -1

        self._read_cb = read_cb
        self._write_cb = write_cb
        self._delay_cb = delay_cb

        # Create handle
        self._handle_ptr = self._ffi.new("bmv080_handle_t*")
        status = self._lib.bmv080_open(
            self._handle_ptr,
            self._handle_ptr,  # self._ffi.NULL -- not used but lib complains if NULL
            self._read_cb,
            self._write_cb,
            self._delay_cb,
        )
        self._check_status(status)
        self._handle = self._handle_ptr[0]

    def _get_driver_version_raw(self) -> tuple[int, int, int]:
        """Get the driver version without requiring an open handle.

        Returns:
            Tuple of (major, minor, patch) version numbers.

        Raises:
            BMV080Error: If getting version fails.
        """
        major = self._ffi.new("uint16_t*")
        minor = self._ffi.new("uint16_t*")
        patch = self._ffi.new("uint16_t*")
        git_hash = self._ffi.new("char[12]")
        commits = self._ffi.new("int32_t*")

        status = self._lib.bmv080_get_driver_version(major, minor, patch, git_hash, commits)
        self._check_status(status)
        return (major[0], minor[0], patch[0])

    def _close(self) -> None:
        """Close connection to the BMV080 sensor.

        Releases the sensor handle and resources.
        """
        if self._handle is not None:
            self._lib.bmv080_close(self._handle_ptr)
            self._handle = None

        self._handle_ptr = None
        self._read_cb = None
        self._write_cb = None
        self._delay_cb = None
        self._tick_cb = None
        self._data_ready_cb = None
        self._lib = None
        self._ffi = None
        self._logged_exc = None

    def reset(self) -> None:
        """Reset the sensor including hardware and software.

        All parameters revert to defaults.

        Raises:
            BMV080Error: If reset fails.
        """
        status = self._lib.bmv080_reset(self._handle)
        self._check_status(status)

    def get_driver_version(self) -> tuple[int, int, int]:
        """Get the driver version.

        Returns:
            Tuple of (major, minor, patch) version numbers.

        Raises:
            BMV080Error: If getting version fails.
        """
        return self._get_driver_version_raw()

    def get_sensor_id(self) -> str:
        """Get the sensor ID.

        Returns:
            13-character sensor ID string.

        Raises:
            BMV080Error: If getting ID fails.
        """
        id_buf = self._ffi.new("char[13]")
        status = self._lib.bmv080_get_sensor_id(self._handle, id_buf)
        self._check_status(status)
        return self._ffi.string(id_buf).decode("ascii")

    def set_parameter(self, key: str, value: bool | float | str) -> None:
        """Set a sensor parameter.

        Args:
            key: Parameter key (e.g., "integration_time", "do_vibration_filtering").
            value: Parameter value of appropriate type. Use int for integer params.

        Raises:
            BMV080Error: If setting parameter fails.
            TypeError: If value type is not supported.
        """
        key_bytes = key.encode("utf-8")

        if isinstance(value, bool):
            val_ptr = self._ffi.new("bool*", value)
        elif isinstance(value, int):
            # int is a subtype of float in type hints but not at runtime
            val_ptr = self._ffi.new("uint16_t*", value)
        elif isinstance(value, float):
            val_ptr = self._ffi.new("float*", value)
        elif isinstance(value, str):
            val_ptr = self._ffi.new("char[]", value.encode("utf-8"))
        else:
            raise TypeError(f"Unsupported parameter type: {type(value)}")

        status = self._lib.bmv080_set_parameter(self._handle, key_bytes, val_ptr)
        self._check_status(status)

    def get_parameter_bool(self, key: str) -> bool:
        """Get a boolean parameter.

        Args:
            key: Parameter key.

        Returns:
            Parameter value.

        Raises:
            BMV080Error: If getting parameter fails.
        """
        key_bytes = key.encode("utf-8")
        val_ptr = self._ffi.new("bool*")
        status = self._lib.bmv080_get_parameter(self._handle, key_bytes, val_ptr)
        self._check_status(status)
        return val_ptr[0]

    def get_parameter_int(self, key: str) -> int:
        """Get an integer parameter.

        Args:
            key: Parameter key.

        Returns:
            Parameter value.

        Raises:
            BMV080Error: If getting parameter fails.
        """
        key_bytes = key.encode("utf-8")
        val_ptr = self._ffi.new("uint16_t*")
        status = self._lib.bmv080_get_parameter(self._handle, key_bytes, val_ptr)
        self._check_status(status)
        return val_ptr[0]

    def get_parameter_float(self, key: str) -> float:
        """Get a float parameter.

        Args:
            key: Parameter key.

        Returns:
            Parameter value.

        Raises:
            BMV080Error: If getting parameter fails.
        """
        key_bytes = key.encode("utf-8")
        val_ptr = self._ffi.new("float*")
        status = self._lib.bmv080_get_parameter(self._handle, key_bytes, val_ptr)
        self._check_status(status)
        return val_ptr[0]

    def get_parameter_str(self, key: str) -> str:
        """Get a string parameter.

        Args:
            key: Parameter key.

        Returns:
            Parameter value (max 256 characters).

        Raises:
            BMV080Error: If getting parameter fails.
        """
        key_bytes = key.encode("utf-8")
        val_ptr = self._ffi.new("char[256]")
        status = self._lib.bmv080_get_parameter(self._handle, key_bytes, val_ptr)
        self._check_status(status)
        return self._ffi.string(val_ptr).decode("utf-8")

    def start_continuous_measurement(self) -> None:
        """Start particle measurement in continuous mode.

        The sensor stays in measurement mode until stop_measurement() is called.
        Call serve_interrupt() regularly to get data.

        Raises:
            BMV080Error: If starting measurement fails.
        """
        status = self._lib.bmv080_start_continuous_measurement(self._handle)
        self._check_status(status)

    def start_duty_cycling_measurement(
        self,
        mode: DutyCyclingMode = DutyCyclingMode.MODE_0,
    ) -> None:
        """Start particle measurement in duty cycling mode.

        Args:
            mode: Duty cycling mode (currently only MODE_0).

        Raises:
            BMV080Error: If starting measurement fails.
        """

        @self._ffi.callback("bmv080_callback_tick_t")
        def tick_cb() -> int:
            return self._link.time_ms() & 0xFFFFFFFF

        self._tick_cb = tick_cb

        status = self._lib.bmv080_start_duty_cycling_measurement(self._handle, self._tick_cb, mode)
        self._check_status(status)

    def stop_measurement(self) -> None:
        """Stop particle measurement.

        Raises:
            BMV080Error: If stopping measurement fails.
        """
        status = self._lib.bmv080_stop_measurement(self._handle)
        self._check_status(status)

    def serve_interrupt(self) -> None:
        """Service an interrupt.

        Should be called regularly (at least once per second in duty cycling mode).
        Calls the overrideable process() method for each available output.

        Raises:
            BMV080Error: If serving interrupt fails.
        """

        # params is passed by the C library but unused
        @self._ffi.callback("bmv080_callback_data_ready_t")
        def data_ready_cb(output: object, params: object) -> None:  # noqa: ARG001
            out = BMV080Output(
                runtime_in_sec=output.runtime_in_sec,
                pm2_5_mass_concentration=output.pm2_5_mass_concentration,
                pm1_mass_concentration=output.pm1_mass_concentration,
                pm10_mass_concentration=output.pm10_mass_concentration,
                pm2_5_number_concentration=output.pm2_5_number_concentration,
                pm1_number_concentration=output.pm1_number_concentration,
                pm10_number_concentration=output.pm10_number_concentration,
                is_obstructed=output.is_obstructed,
                is_outside_measurement_range=output.is_outside_measurement_range,
            )
            self.process(out)

        self._data_ready_cb = data_ready_cb

        status = self._lib.bmv080_serve_interrupt(
            self._handle, self._data_ready_cb, self._ffi.NULL
        )
        self._check_status(status)

    def process(self, output: BMV080Output) -> None:
        """Process a measurement output.

        Override this method to handle measurements. Called for each
        output from serve_interrupt().

        Args:
            output: Measurement data from the sensor.
        """
