(moat-link-metrics)=
# The Link: Metrics Connector

```{include} ../../packaging/moat-link-metrics/README.md
:start-after: % start main
:end-before: % end main
```

## Configuration

Series entries are stored in MoaT-Link under the configured prefix
(default: `metrics`).  Each server has its own subtree;
series entries are children of the server node.

A series entry contains:

- **source**: MoaT-Link path of the value to watch.
- **series**: Backend-specific series name.
- **tags**: dict of backend-specific tag key/value pairs.
- **mode**: Backend-specific data-series mode.
- **attr**: optional attribute path to extract from nested values.
- **factor** / **offset**: optional linear scaling (default: 1 / 0).
- **t_min**: optional minimum interval between writes, in seconds.

The server configuration must specify a **backend** (default: ``akumuli``).

## Backends

Different backends support different time-series databases:

- {ref}`moat-link-metrics-backend-akumuli`: Akumuli time-series database (default)
- {ref}`moat-link-metrics-backend-victoria`: VictoriaMetrics time-series database

See the backend-specific documentation for configuration details and supported features.

## CLI reference

```
moat link metrics list SERVER
moat link metrics show SERVER NAME
moat link metrics add SERVER NAME SOURCE SERIES TAG [TAG …]
moat link metrics delete SERVER NAME
moat link metrics monitor SERVER
```

## systemd

Enable the connector for a server named ``myserver``:

```shell
systemctl enable --now moat-link-metrics@myserver.service
```

```{toctree}
:maxdepth: 2
:hidden:

../moat-link-metrics-backend-akumuli/index
../moat-link-metrics-backend-victoria/index
api
```
