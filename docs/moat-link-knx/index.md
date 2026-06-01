(moat-link-knx)=
# The Link: KNX Connector

```{include} ../../packaging/moat-link-knx/README.md
:start-after: % start main
:end-before: % end main
```

## Configuration

KNX gateway entries are stored in MoaT-Link under the configured prefix
(default: `knx`).  Each gateway has its own subtree; group-address
entries live below it, keyed by the three integer components of the
``a/b/c`` group address.

A gateway entry contains:

- **server.host**: gateway host name or IP.
- **server.port**: gateway port (default ``3671``).

A group-address entry contains:

- **type**: ``in`` (KNX → Link) or ``out`` (Link → KNX).
- **mode**: XKNX data-point type, e.g. ``binary`` or ``Bool``.
- **dest**: destination MoaT-Link path (for ``type=in``).
- **src**: source MoaT-Link path (for ``type=out``).
- **idem**: optional, suppress repeated identical writes (default ``True``).

## CLI reference

```
moat link knx -                               # list gateways
moat link knx NAME                            # show gateway config
moat link knx NAME add -h HOST [-p PORT]      # add a gateway
moat link knx NAME set -h HOST [-p PORT]      # modify a gateway
moat link knx NAME delete [-r]                # delete a gateway
moat link knx NAME dump                       # dump configuration
moat link knx NAME at A/B/C                   # show one entry
moat link knx NAME at A/B/C add -t TYPE -m MODE [-s key value …]
moat link knx NAME at A/B/C set [-s key value …]
moat link knx NAME at A/B/C delete
moat link knx NAME monitor                    # run the connector
```

## systemd

Enable the connector for a gateway named ``myhouse``:

```shell
systemctl enable --now moat-link-knx@myhouse.service
```

```{toctree}
:maxdepth: 2
:hidden:

api
```
