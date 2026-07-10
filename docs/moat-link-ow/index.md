(moat-link-ow)=
# The Link: 1-Wire (OWFS) Connector

```{include} ../../packaging/moat-link-ow/README.md
:start-after: % start main
:end-before: % end main
```

## Configuration

OWFS server entries are stored in MoaT-Link under the configured prefix
(default: `ow`).  Each server has its own subtree; attribute mappings
live below it, keyed by the device's family code, hardware code, and the
attribute path.

A server entry contains:

- **server.host**: owserver host name or IP.
- **server.port**: owserver port (default ``4304``).

An attribute mapping contains:

- **dest**: destination MoaT-Link path (read direction: device→Link).
- **src**: source MoaT-Link path (write direction: Link→device).
- **interval**: polling interval in seconds (read direction).
- **dest_attr**: sub-attribute path merged into ``dest``'s value.
- **src_attr**: sub-attribute path extracted from ``src``'s value.
- **idem**: idempotency flag (default ``True``).

Exactly one of ``dest`` (read) or ``src`` (write) must be set.

## CLI reference

```
moat link ow -                                  # list servers
moat link ow NAME                               # show server config
moat link ow NAME add -h HOST [-p PORT]          # add a server
moat link ow NAME set -h HOST [-p PORT]          # modify a server
moat link ow NAME delete [-r]                    # delete a server
moat link ow NAME dump                           # dump configuration
moat link ow NAME at DEVICE ATTR                 # show one attribute mapping
moat link ow NAME at DEVICE ATTR add [-w] [-i SEC] [-a SUBATTR] [-s key value …]
moat link ow NAME at DEVICE ATTR set [-s key value …]
moat link ow NAME at DEVICE ATTR delete
moat link ow NAME monitor                        # run the connector
```

`DEVICE` is a 1-Wire device id `FF.CODE.CHK` (the checksum is ignored);
`ATTR` is the device attribute path, e.g. `temperature` or `foo.bar`.

## systemd

Enable the connector for a server named ``mybus``:

```shell
systemctl enable --now moat-link-ow@mybus.service
```

```{toctree}
:maxdepth: 2
:hidden:

api
```
