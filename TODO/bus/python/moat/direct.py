# implements the direct connection to a micropython board
# so we can sync the initial files, and get things running

from contextlib import asynccontextmanager
import ast

import anyio
from anyio.streams.buffered import BufferedByteReceiveStream

import re
re_oserror = re.compile(r'OSError: (\[Errno )?(\d+)(\] )?')
re_exceptions = re.compile(r'(ValueError|KeyError|ImportError): (.*)')

from .os_error_list import os_error_mapping

import logging
logger = logging.getLogger(__name__)


async def _noop_hook(ser):
    pass

@asynccontextmanager
async def direct_repl(port, baudrate=115200, hook=_noop_hook):
    from anyio_serial import Serial
    ser = Serial(port=port, baudrate=baudrate)
    async with ser:
        await hook(ser)
        repl = DirectREPL(ser)
        async with repl:
            yield repl


class DirectREPL:
    def __init__(self, serial):
        self.serial = serial
        self.srbuf = BufferedByteReceiveStream(serial)

    async def __aenter__(self):
        await self.serial.send(b'\x02\x03')  # exit raw repl, CTRL+C
        await self.flush_in(0.2)
        await self.serial.send(b'\x03\x01')  # CTRL+C, enter raw repl
        
        # Rather than wait for a timeout we try sending a command.
        # Most likely the first time will go splat because the response
        # doesn't start with "OK", but that's fine, just try again.
        try:
            await anyio.sleep(0.1)
            await self.exec_raw("1")
        except IOError:
            try:
                await anyio.sleep(0.2)
                await self.exec_raw("1")
            except IOError:
                await anyio.sleep(0.2)
                await self.exec_raw("1")
        return self

    async def __aexit__(self, *tb):
        await self.serial.send(b'\x02\x03\x03')

    async def flush_in(self, timeout=0.1):
        while True:
            with anyio.move_on_after(timeout):
                await self.serial.receive(200)
                break
        self.srbuf._buffer = bytearray()


    def _parse_error(self, text):
        """Read the error message and convert exceptions"""
        lines = text.splitlines()
        if lines[0].startswith('Traceback'):
            m = re_oserror.match(lines[-1])
            if m:
                err_num = int(m.group(2))
                if err_num == 2:
                    raise FileNotFoundError(2, 'File not found')
                elif err_num == 13:
                    raise PermissionError(13, 'Permission Error')
                elif err_num == 17:
                    raise FileExistsError(17, 'File Already Exists Error')
                elif err_num == 19:
                    raise OSError(err_num, 'No Such Device Error')
                elif err_num:
                    raise OSError(
                        err_num,
                        os_error_mapping.get(err_num, (None, 'OSError'))[1])
            m = re_exceptions.match(lines[-1])
            if m:
                raise getattr(builtins, m.group(1))(m.group(2))

    async def exec_raw(self, cmd, timeout=5):
        """Exec code, returning (stdout, stderr)"""
        logger.debug("Exec: %r",cmd)
        await self.serial.send(cmd.encode('utf-8'))
        await self.serial.send(b'\x04')

        if not timeout:
            logger.debug("does not return")
            return '', ''  # dummy output if timeout=0 was specified

        try:
            with anyio.fail_after(timeout):
                data = await self.srbuf.receive_until(b'\x04>', max_bytes=10000)
        except TimeoutError:
            # interrupt, read output again to get the expected traceback message
            await self.serial.send(b'\x03')  # CTRL+C
            data = await self.srbuf.receive_until(b'\x04>', max_bytes=10000)

        try:
            out, err = data.split(b'\x04')
        except ValueError:
            raise IOError(f'CTRL-D missing in response: {data!r}')

        if not out.startswith(b'OK'):
            raise IOError(f'data was not accepted: {out}: {err}')
        out = out[2:].decode('utf-8')
        err = err.decode('utf-8')
        if out:
            logger.debug("OUT %r",out)
        if err:
            logger.debug("ERR %r",err)
        return out,err


    async def exec(self, cmd, timeout=3):
        if not cmd.endswith('\n'):
            cmd += '\n'
        out, err = await self.exec_raw(cmd, timeout)
        if err:
            self._parse_error(err)
            raise IOError(f'execution failed: {out}: {err}')
        return out


    async def evaluate(self, cmd):
        """
        :param str code: code to execute
        :returns: Python object

        Execute the string (using :meth:`eval`) and return the output
        parsed using ``ast.literal_eval`` so that numbers, strings, lists etc.
        can be handled as Python objects.
        """
        return ast.literal_eval(await self.exec(cmd))


    async def soft_reset(self, run_main=True):
        """
        :param bool run_main: select if program should be started

        Perform a soft reset of the target. ``main.py`` will not be
        executed if ``run_main`` is True (the default).
        """
        if run_main:
            # exit raw REPL for a reset that runs main.py
            await self.serial.send(b'\x03\x03\x02\x04\x01')
        else:
            # if raw REPL is active, then MicroPython will not execute main.py
            await self.serial.send(b'\x03\x03\x04\x01')
            # execute empty line to get a new prompt and consume all the outputs form the soft reset
            try:
                await anyio.sleep(0.1)
                await self.exec("1")
            except IOError:
                try:
                    await anyio.sleep(0.2)
                    await self.exec("1")
                except IOError:
                    await anyio.sleep(0.2)
                    await self.exec("1")


    async def statvfs(self, path):
        """
        :param str path: Absolute path on target.
        :rtype: os.statvfs_result

        Return statvfs information (disk size, free space etc.) about remote
        filesystem.
        """
        st = await self.evaluate(f'import os; print(os.statvfs({str(path)!r}))')
        return os.statvfs_result(st)
        #~ f_bsize, f_frsize, f_blocks, f_bfree, f_bavail, f_files, f_ffree, f_favail, f_flag, f_namemax


    async def truncate(self, path, length):
        # MicroPython 1.9.3 has no file.truncate(), but open(...,"ab"); write(b"") seems to work.
        return await self.evaluate(
            f'_f = open({str(path)!r}, "ab")\n'
            f'print(_f.seek({int(length)}))\n'
            '_f.write(b"")\n'
            '_f.close(); del _f')




