(moat-link-akumuli)=
# The Link: Akumuli Connector

```{include} ../../packaging/moat-link-akumuli/README.md
:start-after: % start main
:end-before: % end main
```

## Configuration

Series entries are stored in MoaT-Link under the configured prefix
(default: `:.moat.link.akumuli`).  Each server has its own subtree;
series entries are children of the server node.

A series entry contains:

- **source**: MoaT-Link path of the value to watch.
- **series**: Akumuli series name.
- **tags**: dict of Akumuli tag key/value pairs.
- **mode**: Akumuli data-series mode (default: ``gauge``).
- **attr**: optional attribute path to extract from nested values.
- **factor** / **offset**: optional linear scaling (default: 1 / 0).
- **t_min**: optional minimum interval between writes, in seconds.

## CLI reference

```
moat link akumuli list SERVER
moat link akumuli show SERVER NAME
moat link akumuli add SERVER NAME SOURCE SERIES TAG [TAG …]
moat link akumuli delete SERVER NAME
moat link akumuli monitor SERVER
```

## systemd

Enable the connector for a server named ``myserver``:

```shell
systemctl enable --now moat-link-akumuli@myserver.service
```

```{toctree}
:maxdepth: 2
:hidden:

api
```
