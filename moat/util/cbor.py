"""
An overly-simple CBOR packer/unpacker.
"""

# Original Copyright 2014-2015 Brian Olson
# Apache 2.0 license
# http://docs.ros.org/en/noetic/api/rosbridge_library/html/cbor_8py_source.html
# rather heavily modified

from __future__ import annotations

import datetime as dt
import re
from ipaddress import (
    IPv4Address,
    IPv4Interface,
    IPv4Network,
    IPv6Address,
    IPv6Interface,
    IPv6Network,
)

# Typing
from moat.lib.codec.cbor import CBOR_TAG_CBOR_FILEHEADER, CBOR_TAG_CBOR_LEADER, Codec, Tag

from ._cbor import std_ext, StdCBOR
import contextlib

__all__ = ["std_ext", "StdCBOR", "gen_start", "gen_stop"]

CBOR_TAG_MOAT_FILE_ID = 1299145044  # 'MoaT'
CBOR_TAG_MOAT_FILE_END = 1298493254  # 'MeoF'
CBOR_TAG_MOAT_CHANGE = 1298360423  # 'Mchg'

Codec = StdCBOR


def gen_start(text: str, /, **kw) -> Tag:
    """
    Generate a MoaT file start tag
    """
    if len(text) > 255:
        raise ValueError("Description too long")
    # add padding if too short
    text += " " * (24 - len(text))

    return Tag(CBOR_TAG_CBOR_LEADER, Tag(CBOR_TAG_MOAT_FILE_ID, (text, kw)))


def gen_stop(**kw) -> Tag:
    """
    Generate a MoaT file stop tag
    """
    return Tag(CBOR_TAG_MOAT_FILE_END, kw)


def gen_change(**kw) -> Tag:
    """
    Generate a MoaT file stop tag
    """
    return Tag(CBOR_TAG_MOAT_CHANGE, kw)


@std_ext.encoder(1, dt.datetime)
def _enc_datetime_ts(codec, value):
    codec  # noqa:B018
    if not value.tzinfo:
        raise ValueError(f"naive datetime {value!r}")

    return value.timestamp()


# @std_ext.encoder(0, dt.datetime)
def _enc_datetime_str(codec, value):
    codec  # noqa:B018

    if not value.tzinfo:
        raise ValueError(f"naive datetime {value!r}")

    return value.isoformat().replace("+00:00", "Z")


_timestamp_re = re.compile(
    r"^(\d{4})-(\d\d)-(\d\d)T(\d\d):(\d\d):(\d\d)(?:\.(\d{1,6})\d*)?(?:Z|([+-])(\d\d):(\d\d))$",
)


@std_ext.decoder(0)
def _dec_datetime_string(codec, value) -> dt.datetime:
    codec  # noqa:B018

    match = _timestamp_re.match(value)
    if match:
        (
            year,
            month,
            day,
            hour,
            minute,
            second,
            secfrac,
            offset_sign,
            offset_h,
            offset_m,
        ) = match.groups()
        microsecond = 0 if secfrac is None else int(f"{secfrac:<06}")

        if offset_h:
            sign = -1 if offset_sign == "-" else 1
            hours = int(offset_h) * sign
            minutes = int(offset_m) * sign
            tz = dt.timezone(dt.timedelta(hours=hours, minutes=minutes))
        else:
            tz = dt.UTC

        return dt.datetime(
            int(year),
            int(month),
            int(day),
            int(hour),
            int(minute),
            int(second),
            microsecond,
            tz,
        )
    else:
        raise ValueError(f"invalid datetime string: {value!r}")


@std_ext.decoder(1)
def _dec_ts(codec, val):
    codec  # noqa:B018
    return dt.datetime.fromtimestamp(val, dt.UTC)


@std_ext.decoder(2)
def _dec_bigp(codec, val):
    codec  # noqa:B018
    return int.from_bytes(val, "big")


@std_ext.decoder(3)
def _dec_bign(codec, val):
    codec  # noqa:B018
    return -1 - int.from_bytes(val, "big")


def _pad(buf, n):
    buf = bytes(buf)  # SIGH
    if (lb := len(buf)) == n:
        return buf
    return buf + b"\x00" * (n - lb)


@std_ext.decoder(52)
def _dec_ip4address(codec, buf) -> IPv4Address | IPv4Network | IPv4Interface:
    codec  # noqa:B018
    from ipaddress import IPv4Address, IPv4Interface, IPv4Network

    if isinstance(buf, (bytes, bytearray, memoryview)):
        return IPv4Address(_pad(buf, 4))
    elif len(buf) != 2:
        pass
    elif isinstance(buf[1], int):
        return IPv4Interface((_pad(buf[0], 4), buf[1]))
    else:
        return IPv4Network((_pad(buf[1], 4), buf[0]))

    raise ValueError(f"invalid ipaddress value {buf!r}")


@std_ext.decoder(54)
def _dec_ip6address(codec, buf) -> IPv6Address | IPv6Network | IPv6Interface:
    codec  # noqa:B018
    from ipaddress import IPv6Address, IPv6Interface, IPv6Network

    if isinstance(buf, (bytes, bytearray, memoryview)):
        return IPv6Address(_pad(buf, 16))
    elif len(buf) != 2:
        pass
    elif isinstance(buf[1], int):
        return IPv6Interface((_pad(buf[0], 16), buf[1]))
    else:
        return IPv6Network((_pad(buf[1], 16), buf[0]))

    raise ValueError(f"invalid ipaddress value {buf!r}")


@std_ext.encoder(52, IPv4Address)
@std_ext.encoder(54, IPv6Address)
def _pack_ip(codec, adr):
    codec  # noqa:B018
    return adr.packed.rstrip(b"\x00")


@std_ext.encoder(52, IPv4Network)
@std_ext.encoder(54, IPv6Network)
def _pack_ipnet(codec, adr):
    codec  # noqa:B018
    return (adr.prefixlen, _pack_ip(codec, adr.network_address))


@std_ext.encoder(52, IPv4Interface)
@std_ext.encoder(54, IPv6Interface)
def _pack_ipintf(codec, adr):
    codec  # noqa:B018
    return (_pack_ip(codec, adr), adr.network.prefixlen)


@std_ext.decoder(260)
def _dec_old_ipaddress(codec, buf) -> IPv4Address | IPv6Address | Tag:
    codec  # noqa:B018
    if isinstance(buf, (bytes, bytearray, memoryview)) or len(buf) not in (4, 6, 16):
        if len(buf) == 4:
            return IPv4Address(bytes(buf))
        elif len(buf) == 16:
            return IPv6Address(bytes(buf))
        elif len(buf) == 6:
            # MAC address
            return Tag(260, buf)

    raise ValueError(f"invalid ipaddress value {buf!r}")


@std_ext.decoder(261)
def _dec_old_ipnetwork(codec, buf) -> IPv4Network | IPv6Network:
    codec  # noqa:B018
    if isinstance(buf, dict) and len(buf) == 1:
        mask, buf = next(iter(buf.items()))
        if len(buf) == 4:
            return IPv4Network((bytes(buf), mask))
        elif len(buf) == 16:
            return IPv6Network((bytes(buf), mask))

    raise ValueError(f"invalid ipnetwork value {buf!r}")


@std_ext.decoder(CBOR_TAG_CBOR_FILEHEADER)
def _dec_file_cbor(codec, val):
    codec  # noqa:B018
    with contextlib.suppress(AttributeError):
        val._cbor_tag = CBOR_TAG_CBOR_FILEHEADER
    return val


@std_ext.decoder(CBOR_TAG_CBOR_LEADER)
def _dec_file_cbor(codec, val):
    codec  # noqa:B018
    with contextlib.suppress(AttributeError):
        val._cbor_tag = CBOR_TAG_CBOR_LEADER
    return val
