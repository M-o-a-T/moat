(moat-link-wago)=
# The Link: Wago Connector

```{include} ../../packaging/moat-link-wago/README.md
:start-after: % start main
:end-before: % end main
```

## Configuration

Wago controller entries are stored in MoaT-Link under the configured prefix
(default: `wago`).  Each controller has its own subtree; port
entries live below it, keyed by type (`input` or `output`), card number,
and port number.

A controller entry contains:

- **server.host**: controller host name or IP.
- **server.port**: controller port (default ``29995``).

A port entry contains:

- **mode**: ``read``, ``count``, ``write``, ``oneshot``, or ``pulse``.
- **dest**: destination MoaT-Link path (for ``mode=read|count``).
- **src**: source MoaT-Link path (for ``mode=write|oneshot|pulse``).
- **state**: optional path (for output modes) that tracks the last
  observed state.
- **rest**: rest-state flag (default ``False``).
- **interval**: polling interval in seconds (for ``mode=count``).
- **count**: pulse direction (``True``/``False``/``None``).
- **t_on**: on-time in seconds (for ``mode=oneshot|pulse``).
- **t_off**: off-time in seconds (for ``mode=pulse``).

## CLI reference

```
moat link wago -                               # list controllers
moat link wago NAME                            # show controller config
moat link wago NAME add -h HOST [-p PORT]      # add a controller
moat link wago NAME set -h HOST [-p PORT]      # modify a controller
moat link wago NAME delete [-r]                # delete a controller
moat link wago NAME dump                       # dump configuration
moat link wago NAME at TYPE CARD PORT          # show one port entry
moat link wago NAME at TYPE CARD PORT add -m MODE [-s key value …]
moat link wago NAME at TYPE CARD PORT set [-s key value …]
moat link wago NAME at TYPE CARD PORT delete
moat link wago NAME monitor                    # run the connector
```

## systemd

Enable the connector for a controller named ``myctrl``:

```shell
systemctl enable --now moat-link-wago@myctrl.service
```

```{toctree}
:maxdepth: 2
:hidden:

api
```
