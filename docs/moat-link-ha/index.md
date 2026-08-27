(moat-link-ha)=
# The Link: Home Assistant Connector

```{include} ../../packaging/moat-link-ha/README.md
:start-after: % start main
:end-before: % end main
```

## Configuration

Home-Assistant device definitions are stored in MoaT-Link under the
configured prefix (default: `hass`).  Each device type (`light`,
`switch`, `binary_sensor`, `number`, `sensor`, `lock`) has its own
subtree; device entries are keyed by a 1–2 element path.

## CLI reference

```
moat link ha set TYPE PATH [-s key value…]  # add/modify a device
moat link ha get TYPE PATH                  # show a device
moat link ha get - -                        # list device types
moat link ha delete TYPE PATH               # delete a device
```

```{toctree}
:maxdepth: 2
:hidden:

api
```
