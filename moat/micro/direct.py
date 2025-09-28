"""
This module implements the direct connection to a micropython board.

MoaT uses this to can sync the initial files and get things running.
"""

from __future__ import annotations

import anyio
import ast
import logging
import os
import re
from anyio.streams.buffered import BufferedByteReceiveStream
from functools import partial

from moat.micro.proto.stream import SingleAnyioBuf
from moat.util.compat import AC_use

from .os_error_list import os_error_mapping

# Typing
from typing import TYPE_CHECKING  # isort:skip

if TYPE_CHECKING:
    from moat.micro.proto.stack import BaseBuf


logger = logging.getLogger(__name__)

re_oserror = re.compile(r"OSError: (\[Errno )?(\d+)(\] )?")
re_exceptions = re.compile(r"(ValueError|KeyError|ImportError): (.*)")


async def _noop_hook(ser):
    pass


class DirectREPL(SingleAnyioBuf):
    """
    Interface to the remote REPL
    """

    serial: BaseBuf = None  # pylint:disable=used-before-assignment # WTF
    srbuf: BufferedByteReceiveStream = None

    async def stream(self):
        "Context. Tries hard to exit special MicroPython modes, if any"
        self.serial = await super().stream()
        await AC_use(self, partial(self.serial.send, b"\x02\x03\x03"))

        self.srbuf = BufferedByteReceiveStream(self.serial)

        await self.serial.send(b"\x02")  # exit raw repl, CTRL+C
        await self.flush_in(0.5)
        await self.serial.send(b"\x03")  # exit raw repl, CTRL+C
        await self.flush_in(0.5)
        await self.serial.send(b"\x01")  # CTRL+C, enter raw repl
        await self.flush_in(0.2)

        # Rather than wait for a longer timeout we try sending a command.
        # Most likely the first time will go splat because the response
        # doesn't start with "OK", but that's fine, just try again.
        try:
            await self.exec_raw("print(1)")
        except (OSError, TimeoutError):
            await self.serial.send(b"\x02\x03")  # exit raw repl, CTRL+C
            await self.flush_in(0.2)
            await self.serial.send(b"\x03\x01")  # CTRL+C, enter raw repl
            try:
                await anyio.sleep(0.2)
                await self.exec_raw("print(2)")
            except OSError:
                await anyio.sleep(0.2)
                await self.exec_raw("print(3)")
        return self.serial

    async def flush_in(self, timeout=0.1):
        "flush incoming data"
        started = False
        b = b""
        while True:
            with anyio.move_on_after(timeout):
                res = await self.serial.receive(200)
                if not started:
                    logger.debug("Flushing…")
                    started = True
                b = (b + res)[-200:]
                continue
            break
        if b:
            logger.debug("Flush: IN %r", b)
        self.srbuf._buffer = bytearray()  # noqa:SLF001 pylint: disable=protected-access

    def _parse_error(self, text):
        """Read the error message and convert exceptions"""
        lines = text.splitlines()
        if lines[0].startswith("Traceback"):
            m = re_oserror.match(lines[-1])
            if m:
                err_num = int(m.group(2))
                if err_num == 2:
                    raise FileNotFoundError(2, "File not found")
                if err_num == 13:
                    raise PermissionError(13, "Permission Error")
                if err_num == 17:
                    raise FileExistsError(17, "File Already Exists Error")
                if err_num == 19:
                    raise OSError(err_num, "No Such Device Error")
                if err_num:
                    raise OSError(err_num, os_error_mapping.get(err_num, (None, "OSError"))[1])
            m = re_exceptions.match(lines[-1])
            if m:
                raise __builtins__[m.group(1)](m.group(2))

    async def exec_raw(self, cmd, timeout=5, quiet=False):
        """Exec code, returning (stdout, stderr)"""
        if not quiet:
            logger.debug("Exec: %r", cmd)
        await self.serial.send(cmd.encode("utf-8"))
        await self.serial.send(b"\x04")

        if not timeout:
            logger.debug("does not return")
            return "", ""  # dummy output if timeout=0 was specified

        try:
            with anyio.fail_after(timeout):
                data = await self.srbuf.receive_until(b"\x04>", max_bytes=10000)
        except TimeoutError:
            # interrupt, read output again to get the expected traceback message
            logger.debug("Timeout. Buffer:\n%s\n", self.srbuf.buffer)
            await self.serial.send(b"\x03")  # CTRL+C
            with anyio.fail_after(3):
                data = await self.srbuf.receive_until(b"\x04>", max_bytes=10000)

        try:
            out, err = data.split(b"\x04")
        except ValueError:
            raise OSError(f"CTRL-D missing in response: {data!r}") from None

        if b"\nStart MoaT:" in out:
            i = out.find(b"\nOK")
            if i > 0:
                out = out[i + 1 :]
        if not out.startswith(b"OK"):
            raise OSError(f"data was not accepted: {out}: {err}")
        out = out[2:].decode("utf-8")
        err = err.decode("utf-8")
        if not quiet:
            if out:
                logger.debug("OUT %r", out)
            if err:
                logger.debug("ERR %r", err)
        return out, err

    async def exec(self, cmd, timeout=3, quiet=False):
        """run a command"""
        if not cmd.endswith("\n"):
            cmd += "\n"
        out, err = await self.exec_raw(cmd, timeout, quiet=quiet)
        if err:
            self._parse_error(err)
            raise OSError(f"execution failed: {out}: {err}")
        return out

    async def evaluate(self, cmd, quiet=False):
        """
        :param str code: code to execute
        :returns: Python object

        Execute the string (using :meth:`eval`) and return the output
        parsed using ``ast.literal_eval`` so that numbers, strings, lists etc.
        can be handled as Python objects.
        """
        return ast.literal_eval(await self.exec(cmd, quiet=quiet))

    async def reset(self):
        """
        Send a hard reset command
        """
        await self.exec_raw("import machine; machine.reset()", timeout=0, quiet=False)

    async def soft_reset(self, run_main=True):
        """
        :param bool run_main: select if program should be started

        Perform a soft reset of the target. ``main.py`` will not be
        executed if ``run_main`` is True (the default).
        """
        if run_main:
            # exit raw REPL for a reset that runs main.py
            await self.serial.send(b"\x03\x03\x02\x04\x01")
        else:
            # if raw REPL is active, then MicroPython will not execute main.py
            await self.serial.send(b"\x03\x03\x04\x01")
            # execute empty line to get a new prompt
            # and consume all the outputs form the soft reset
            try:
                await anyio.sleep(0.1)
                await self.exec("4")
            except OSError:
                try:
                    await anyio.sleep(0.2)
                    await self.exec("5")
                except OSError:
                    await anyio.sleep(0.2)
                    await self.exec("6")

    async def statvfs(self, path):
        """
        :param str path: Absolute path on target.
        :rtype: os.statvfs_result

        Return statvfs information (disk size, free space etc.) about remote
        filesystem.
        """
        st = await self.evaluate(f"import os; print(os.statvfs({str(path)!r}))")
        return os.statvfs_result(st)
        # ~ f_bsize, f_frsize, f_blocks, f_bfree, f_bavail,
        #   f_files, f_ffree, f_favail, f_flag, f_namemax

    async def truncate(self, path, length):
        """
        Truncate a file.

        MicroPython has no file.truncate(), but open(...,"ab"); write(b"") seems to work.
        """
        return await self.evaluate(
            f'_f = open({str(path)!r}, "ab")\n'
            f"print(_f.seek({int(length)}))\n"
            '_f.write(b"")\n'
            "_f.close(); del _f",
        )
