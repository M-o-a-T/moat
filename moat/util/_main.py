#!/usr/bin/env python3
"""
Basic tool support

"""
import sys
import logging  # pylint: disable=wrong-import-position
from datetime import datetime
from time import time

import anyio
import asyncclick as click

from .main import load_subgroup
from .times import humandelta, time_until
from .yaml import yload,yprint
from .msgpack import packer,stream_unpacker

log = logging.getLogger()


@load_subgroup(prefix="moat.util")
async def cli():
    """Various utilities"""
    pass


@cli.command(name="to")
@click.option("--sleep", "-s", is_flag=True, help="Sleep until that date/time")
@click.option("--human", "-h", is_flag=True, help="Print in numan-readable terms")
@click.option("--now", "-n", is_flag=True, help="Don't advance on match")
@click.option("--inv", "-i", is_flag=True, help="Time until no match")
@click.argument("args", nargs=-1)
async def to_(args, sleep, human, now, inv):
    """\
Calculate the time until the start of the next given interval according to
the wall clock.

For instance, "moat util to 9 h": shows in how many seconds it's 9 o'clock
(possibly on the next day). Arbitrarily many units can be combined.

Negative numbers count from the end, i.e. "-2 hr" == 10 pm. Don't
forget to use the "--" option-to-argument separator if the time
specification starts with a negative number.

"--human" prints a human-understandable version of the given interval;
"--sleep" waits until the specified moment arrives. If neither of these
options is used, the number of seconds is printed.

By default, if the given interval matches the current time, the
duration to the *next* moment the interval matches is calculated. Use
"--now" to print 0 / "now" / not sleep instead.

"--inv" inverts the given interval, i.e. "9 h" prints the time until
the next moment it is not / no longer 9:** o'clock, depending on
whether "--now" is used / not used.

Limitations:

This tool does not understand relative time. It may or may not get confused
when the interval crosses a DST boundary. If your computer is suspended
during "--sleep", the delay will be too long.

\b
Known units:
s, sec (0…59)
m, min (0…59)
h, hr  (0…23)
d, dy  (1…7)
w, wk  (0…53)
m, mo  Month (1…12)
y, yr  Year (2023–)
    """
    if not args:
        raise click.UsageError("Up to when please?")

    t = datetime.now()
    if not now:
        t = time_until(args, t, invert=not inv)
    t = time_until(args, t, invert=inv)

    t = t.timestamp()
    t = int(t - time() + 0.9)
    if human:
        print(humandelta(t))
    if sleep:
        await anyio.sleep(t)
    elif not human:
        print(t)

@cli.command
@click.option("-d","--decode",is_flag=True,help="decode (default: encode)")
@click.argument("path",type=click.Path(file_okay=True,dir_okay=False))
async def msgpack(decode,path):
    """encode/decode msgpack from/to YAML

    moat util msgpack data.yaml > data.mp    # encode
    moat util msgpack -d data.mp > data.yaml # decode
    """
    if decode:
        with (sys.stdin.buffer if path == "-" else open(path,"rb")) as f:
            n = 0
            for obj in stream_unpacker(f):
                if n:
                    print("---")
                n += 1
                yprint(obj)
    else:
        with (sys.stdin if path == "-" else open(path,"r")) as f:
            for obj in yload(f, multi=True):
                sys.stdout.buffer.write(packer(obj))



