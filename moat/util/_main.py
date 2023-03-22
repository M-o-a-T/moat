#!/usr/bin/env python3
"""
Basic tool support

"""
import logging  # pylint: disable=wrong-import-position
import sys
from datetime import datetime
from time import time

import anyio
import asyncclick as click

from .main import load_subgroup
from .msgpack import packer, stream_unpacker
from .times import humandelta, time_until
from .yaml import yload, yprint

log = logging.getLogger()


@load_subgroup(prefix="moat.util")
async def cli():
    """Various utilities"""
    pass  # pylint:disable=unnecessary-pass


@cli.command(name="to")
@click.option("--sleep", "-s", is_flag=True, help="Sleep until that date/time")
@click.option("--human", "-h", is_flag=True, help="Print in numan-readable terms")
@click.option("--now", "-n", is_flag=True, help="Don't advance on match")
@click.option("--inv", "-i", is_flag=True, help="Time until no match")
@click.option("--back", "-b", is_flag=True, help="Time since the last (non)-match")
@click.argument("args", nargs=-1)
async def to_(args, sleep, human, now, inv, back):
    """\
Calculate the time until the start of the next given partial time
specification.

For instance, "moat util to 9 h": shows in how many seconds it's 9 o'clock
(possibly on the next day). Arbitrarily many units can be combined.

Negative numbers count from the end, i.e. "-2 hr" == 10 pm. Don't
forget to use the "--" option-to-argument separator if the time
specification starts with a negative number.

Days are numbered 1…7, Monday…Sunday. "3 dy" is synonymous to "wed",
while "3 wed" means "the third wednesday in a month".

"--human" prints a human-understandable version of the given
time. "--sleep" then delays until the specified moment arrives. If none
of these options is given, the number of seconds is printed.

By default, if the given time spec matches the current time, the
duration to the *next* moment the spec matches is calculated. Use
"--now" to print 0 / "now" / not sleep instead.

"--inv" inverts the time specification, i.e. "9 h" prints the time
until the next moment it is not / again no longer 9:** o'clock,
depending on whether "--now" is used / not used.

"--back" calculates the time *since the end* of the last match /
non-match instead. (If you want the start, use "--inv" and add a
second.)

\b
Known units:
s, sec  Second (0…59)
m, min  Minute (0…59)
h, hr   Hour (0…23)
d, dy   Day-of-week (1…7)
mon…sun Day-in-month (1…5)
w, wk   Week-of-year (0…53)
m, mo   Month (1…12)
y, yr   Year (2023–)
"""
    if not args:
        raise click.UsageError("Up to when please?")
    if back and sleep:
        raise click.UsageError("We don't have time machines.")

    t = datetime.now()
    if not now:
        t = time_until(args, t, invert=not inv, back=back)
    t = time_until(args, t, invert=inv, back=back)

    t = t.timestamp()
    tt = int(t - time() + 0.9)
    if back:
        tt = -tt
    if human:
        print(humandelta(tt))
    if sleep:
        await anyio.sleep(tt)
    elif not human:
        print(tt)


@cli.command
@click.option("-d", "--decode", is_flag=True, help="decode (default: encode)")
@click.argument("path", type=click.Path(file_okay=True, dir_okay=False))
async def msgpack(decode, path):
    """encode/decode msgpack from/to YAML

    moat util msgpack data.yaml > data.mp    # encode
    moat util msgpack -d data.mp > data.yaml # decode
    """
    if decode:
        with sys.stdin.buffer if path == "-" else open(path, "rb") as f:
            n = 0
            for obj in stream_unpacker(f):
                if n:
                    print("---")
                n += 1
                yprint(obj)
    else:
        with sys.stdin if path == "-" else open(path, "r") as f:
            for obj in yload(f, multi=True):
                sys.stdout.buffer.write(packer(obj))
