(moat-link-cal)=
# The Link: Calendar Connector

```{include} ../../packaging/moat-link-cal/README.md
:start-after: % start main
:end-before: % end main
```

## Configuration

Calendar configuration is stored in MoaT-Link under the configured prefix
(default: `calendar`).  Each calendar entry is keyed by its name and
contains:

- **url**: CalDAV server URL.
- **user**: CalDAV username.
- **pass**: CalDAV password.
- **zone**: timezone (optional, default UTC).
- **interval**: scan interval in seconds (default 1800).
- **dst**: destination MoaT-Link path for alarm messages.
- **calendar**: calendar name on the CalDAV server (optional).

## CLI reference

```
moat link cal run NAME    # process calendar alarms
moat link cal list        # list stored calendar data
```

```{toctree}
:maxdepth: 2
:hidden:

api
```
