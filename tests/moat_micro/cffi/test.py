"""
Callback framework
"""

from __future__ import annotations

from pathlib import Path

from cffi import FFI

from typing import Self


class ItestWrapper:
    """CFFI wrapper for itest.so library."""

    def __init__(self, fn, param):
        self.fn = fn
        self.param = param
        self.ffi = FFI()

        # Define the C interface
        self.ffi.cdef("""
            struct itest;

            struct itest_cb {
                void *user;
                int (*callback)(void *user, int param);
            };

            struct itest *itest_setup(struct itest_cb *cb, int param);
            void itest_free(struct itest *);
            int itest_call(struct itest *, int param);
        """)

    def __enter__(self) -> Self:
        "dynamically load itest.so here"
        # Load the shared library from the same directory as this file
        lib_path = Path(__file__).parent / "itest.so"
        self.lib = self.ffi.dlopen(str(lib_path))

        # Create the callback function that wraps our Python function
        @self.ffi.callback("int(void *, int)")
        def callback_wrapper(_user, param):
            # Call the Python function
            return self.fn(param)

        # Keep a reference to prevent garbage collection
        self._callback_wrapper = callback_wrapper

        # Create the callback structure
        self.cb = self.ffi.new("struct itest_cb *")
        self.cb.user = self.ffi.NULL  # We don't need user data
        self.cb.callback = callback_wrapper

        # Setup the itest instance
        self.itest = self.lib.itest_setup(self.cb, self.param)

        return self

    def __exit__(self, *exc):
        "unload itest.so"
        if hasattr(self, "itest") and self.itest:
            self.lib.itest_free(self.itest)
            del self.itest
        if hasattr(self, "_callback_wrapper"):
            del self._callback_wrapper
        if hasattr(self, "lib"):
            self.ffi.dlclose(self.lib)
            del self.lib

    def call(self, param: int) -> int:
        "call itest_call(param) and return its result"
        return self.lib.itest_call(self.itest, param)
