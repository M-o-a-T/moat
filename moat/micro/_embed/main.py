def go_moat(no_exit=False):
    from moat import spawn

    async def setup(evt):
        import sys
        import micropython
        import uasyncio
        from uasyncio.stream import Stream
        from moat.cmd import CmdHandler

        micropython.kbd_intr(-1)
        spawn(evt, CmdHandler(Stream(sys.stdin.buffer), None if no_exit else evt).run)

    from moat import moat_run
    moat_run(setup)
