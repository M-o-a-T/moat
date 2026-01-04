"""
Compatibility layer for pymodbus 3.9 and 3.11+.

This module monkeypatches pymodbus 3.9 framers to add the 3.11+ handleFrame API,
and adds missing exception constants to ExceptionResponse for backward compatibility.
"""

from __future__ import annotations


def _setup_exception_codes():
    """
    Setup exception code compatibility.

    pymodbus 3.11 uses pymodbus.constants.ExcCodes with DEVICE_FAILURE.
    pymodbus 3.9 uses ExceptionResponse class attributes with SLAVE_FAILURE.

    We monkeypatch 3.9 to add DEVICE_FAILURE as an alias for SLAVE_FAILURE.
    """
    try:
        # Try 3.11 import first
        from pymodbus.constants import ExcCodes  # noqa: PLC0415
        # 3.11 is fine as-is
    except ImportError:
        # pymodbus 3.9 - need to create ExcCodes from ExceptionResponse
        import pymodbus.constants  # noqa: PLC0415
        from pymodbus.pdu import ExceptionResponse  # noqa: PLC0415

        class ExcCodes:
            """Compatibility shim for pymodbus 3.9"""

            DEVICE_FAILURE = ExceptionResponse.SLAVE_FAILURE
            GATEWAY_NO_RESPONSE = ExceptionResponse.GATEWAY_NO_RESPONSE

        pymodbus.constants.ExcCodes = ExcCodes


def _add_handle_frame_to_framer(framer_class):
    """
    Monkeypatch a pymodbus 3.9 framer class to add the handleFrame method.

    pymodbus 3.11+ uses: handleFrame(data, dev_id, tid)
    pymodbus 3.9 uses: processIncomingFrame(data)
    """
    if hasattr(framer_class, "handleFrame"):
        # Already has 3.11+ API, nothing to do
        return

    if not hasattr(framer_class, "processIncomingFrame"):
        # Not a framer we know how to patch
        return

    def handleFrame(self, data, dev_id=0, tid=0):  # noqa: ARG001
        """Compatibility wrapper that calls processIncomingFrame."""
        return self.processIncomingFrame(data)

    framer_class.handleFrame = handleFrame


def _setup_compat():
    """Setup compatibility patches for pymodbus."""
    # Setup exception codes compatibility
    _setup_exception_codes()

    # Try to import 3.9 framers and patch them (needed for 3.9)
    try:
        from pymodbus.framer.base import FramerBase  # noqa: PLC0415
    except ImportError:
        pass
    else:
        _add_handle_frame_to_framer(FramerBase)


# Apply patches on import
_setup_compat()
