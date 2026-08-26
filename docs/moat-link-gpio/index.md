(moat-link-gpio)=
# The Link: GPIO Connector

```{include} ../../packaging/moat-link-gpio/README.md
:start-after: % start main
:end-before: % end main
```

## Configuration

GPIO line configurations are stored in MoaT-Link under the configured
prefix (default: `gpio`).  The tree is organised as
`prefix / host / chip / line`, where `host` is the host name, `chip` is
the GPIO chip name, and `line` is the integer line number.

Each line entry contains:

- **type**: `"input"` or `"output"`.
- **mode**: input mode (`read`, `count`, `button`) or output mode
  (`write`, `oneshot`, `pulse`).
- **dest**: destination MoaT-Link path (for input modes).
- **src**: source MoaT-Link path (for output modes).
- **state**: optional state path (for output modes).
- **low**: active-low flag (default `False`).
- Additional timing parameters (`t_bounce`, `t_idle`, `t_on`, `t_off`,
  `t_clear`, `interval`, `count`, `skip`, `flow`).

## CLI reference

```
moat link gpio dump PATH                    # dump a subtree
moat link gpio list PATH                    # list the next stage
moat link gpio attr PATH [-s key value …]   # set/get/delete attributes
moat link gpio delete PATH                  # delete a port
moat link gpio port PATH -t TYPE -m MODE [-a NAME VALUE …]  # add/modify
moat link gpio monitor HOST CHIP             # run the connector
```

```{toctree}
:maxdepth: 2
:hidden:

api
```
