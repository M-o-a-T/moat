# implements the direct connection to a micropython board
# so we can sync the initial files, and get things running

import anyio
from anyio.streams.buffered import BufferedByteReceiveStream

class DirectREPL:
    def __init__(self, serial):
        self.serial = serial
        self.srbuf = BufferedByteReceiveStream(serial)

    async def __aenter__(self):
        await self.serial.write(b'\x02\x03')  # exit raw repl, CTRL+C
        await self.flush_in(0.2)
        await self.serial.write(b'\x03\x01')  # CTRL+C, enter raw repl
        await self.flush_in(0.2)

    async def __aexit__(self, *tb):
        await self.serial.write(b'\x02\x03\x03')

    async def flush_in(self, timeout=0.1):
        while True:
            with anyio.move_on_after(timeout):
                await self.serial.read(200)
                break
        self.srbuf._buffer = bytearray()


    async def exec_raw(self, cmd, timeout=5):
        """Exec code, returning (stdout, stderr)"""
        await self.serial.write(cmd.encode('utf-8'))
        await self.serial.write(b'\x04')

        if not timeout:
            return '', ''  # dummy output if timeout=0 was specified

        try:
            with anyio.fail_after(timeout):
                data = await self.srbuf.receive_until(b'\x04>')
        except TimeoutError:
            # interrupt, read output again to get the expected traceback message
            await self.serial.write(b'\x03')  # CTRL+C
            data = await self.srbuf.receive_until(b'\x04>')

        try:
            out, err = data.split(b'\x04')
        except ValueError:
            raise IOError(f'CTRL-D missing in response: {data!r}')

        if not out.startswith(b'OK'):
            raise IOError(f'data was not accepted: {out}: {err}')
        return out[2:].decode('utf-8'), err.decode('utf-8')


    async def exec(self, cmd, timeout=3):
        if not cmd.endswith('\n'):
            cmd += '\n'
        out, err = self.exec_raw(cmd, timeout)
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

        Execute a soft reset of the target. if ``run_main`` is False, then
        the REPL connection will be maintained and ``main.py`` will not be
        executed. Otherwise a regular soft reset is made and ``main.py``
        is executed.
        """
        if run_main:
            # exit raw REPL for a reset that runs main.py
            self.serial.write(b'\x03\x03\x02\x04\x01')
        else:
            # if raw REPL is active, then MicroPython will not execute main.py
            self.serial.write(b'\x03\x03\x04')
            # execute empty line to get a new prompt and consume all the outputs form the soft reset
            await self.exec(' ')
        # XXX read startup message


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




