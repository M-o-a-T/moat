(moat-link-ow)=
# The Link: 1-Wire (OWFS) Connector

```{include} ../../packaging/moat-link-ow/README.md
:start-after: % start main
:end-before: % end main
```

## Configuration

The configuration is stored in MoaT-Link below the configured prefix
(default: `1wire`). 1-Wire device IDs are globally unique, so it is keyed
by device, not by bus: a device that is moved to another bus (or another
owserver) keeps its settings.

```yaml
0x10:                         # family: settings for all its devices
  _: {interval: 60}
  0x0bac6b010800:             # device: settings for its attributes
    _: {}
    temperature:              # attribute mapping
      _:
        dest: !P home.ass.dyn.sensor.temp.garten.state
        interval: 30
server:
  pi-e:
    _:
      server: {host: e.pi.example.com}
```

Family and device codes are stored as integers, but shown and entered as
two and twelve hex digits (`10.0bac6b010800`).

An owserver entry (`server.NAME`) contains:

- **server.host**: owserver host name or IP.
- **server.port**: owserver port (default ``4304``).
- **server.scan**: re-scan the buses every N seconds (default ``60``,
  at least 1), to notice devices that appear, vanish, or move.

An attribute mapping contains:

- **dest**: destination MoaT-Link path (read direction: device→Link).
- **src**: source MoaT-Link path (write direction: Link→device).
- **interval**: polling interval in seconds (read direction).
- **dest_attr**: sub-attribute path merged into ``dest``'s value.
- **src_attr**: sub-attribute path extracted from ``src``'s value.
- **idem**: idempotency flag (default ``True``).

Its effective settings are its own, merged over its device's, merged over
its family's; e.g. set ``interval`` on the family to poll all its
devices' mappings at that rate. One of ``dest`` (read) or ``src`` (write)
must be set.

A write mapping writes the source's current value when its device is
found, then every change.

## CLI reference

```
moat link ow server -                              # list servers
moat link ow server NAME                           # show a server
moat link ow server NAME add -h HOST [-p PORT]
moat link ow server NAME set [-h HOST] [-p PORT]
moat link ow server NAME delete
moat link ow server NAME monitor [-f]              # run the connector for one server

moat link ow at -                                  # list families
moat link ow at FAMILY                             # list its devices
moat link ow at FAMILY get [ATTR…]                 # show family settings
moat link ow at FAMILY set -s KEY VALUE …          # change them
moat link ow at FAMILY.CODE                        # list its mappings
moat link ow at FAMILY.CODE get|set|delete …       # device settings
moat link ow at FAMILY.CODE.ATTR                   # show a mapping
moat link ow at FAMILY.CODE.ATTR add [-w] [-i SEC] [-a SUBATTR] [-s KEY VALUE …]
moat link ow at FAMILY.CODE.ATTR get|set|delete …
moat link ow at SPEC dump                          # subtree as YAML
moat link ow dump                                  # everything as YAML

moat link ow monitor [-f] [NAME…]                  # run the connector (all servers)
```

`ATTR` is the device attribute path, e.g. `temperature` or `foo.bar`;
`get ATTR…` takes lookup paths into the settings.

## Running

`moat link ow monitor` talks to all owservers, or to those named on the
command line. Each server is announced like a gate (see `moat link gate
… run`): a server that another live connector has announced is skipped
until that connector goes away (unless `-f` is used), so several hosts
can run connectors for the same configuration.

Errors are reported to MoaT-Link's error subsystem:

- connection problems, at `server.NAME`; these are always retried with
  backoff;
- problems with a mapping or its device (read errors, failed writes,
  bad attributes), at the mapping's path;
- anything else, at `server.NAME`. `moat link ow monitor` logs and
  retries these. `moat link ow server NAME monitor` exits instead, so
  that e.g. systemd restarts it.

When something works again, its error is cleared.

```shell
systemctl enable --now moat-link-ow.service        # all servers
systemctl enable --now moat-link-ow@mybus.service  # only server "mybus"
```

```{toctree}
:maxdepth: 2
:hidden:

api
```
