(moat-lib-config)=
# Configuration Management

```{include} ../../packaging/moat-lib-config/README.md
:start-after: % start main
:end-before: % end main
```

## Manual

### Global Configuration Object

The `CFG` object provides context-based, global access to configuration.

```python
from moat.lib.config import CFG

# Initial setup
CFG(name="myapp")  # # autoloads /etc/myapp.cfg

# the environment works in any context
assert CFG.env.foo.bar == "baz"
```

### Configuration Store

For more fine-grained control, you can instantiate configuration objects
explicitly.

```python
from moat.lib.config import CfgStore

# Create a configuration store
cfg = CfgStore(
    name="myotherapp",
    preload={"debug": True},
    load_all=False  # Stop after the first config file found
)

# Access values
database_host = cfg.database.host
cache_size = cfg["cache"]["size"]

```

You can use them to replace the `CFG` object's context, e.g. to run two
programs in one Python interpreter:

```python
with CFG.with_config(cfg):
    ...
    if CFG.database.host == "localhost":
        ...

    # globally update the environment subsection
    CFG.set_env(P("foo.bar"), "baz")

# Access myotherapp's config data
assert CFG.env.foo.bar == "baz"
print(CFG.database.host)  # fails if 'myapp.cfg' doesn't contain that

```


## Modifying the configuration

```python
cfg.mod(P("database.port"), 5433)
cfg.add("/etc/myapp/custom.cfg")
```


## Configuration File syntax

Configuration files use YAML format with special directives.

```yaml
# Basic configuration
database:
  host: localhost
  port: 5432
  cache_dir: "/var/cache/moat/db"

# Reference other config values
cache:
  path: !P :@.database.cache_dir
```

### Inheritance with $base

```yaml
# Load basic configuration
$base: "/etc/myapp/base.cfg"

# Override specific values
database:
  host: db.example.com
```

#### Multiple Base Files

Our loader can fetch other config files and optionally select and/or
assemble individual sections.

```yaml
# Merge from multiple sources
$base:
  - !P prod.secrets  # initial path: masks part of the result
  - "/etc/myapp/production.cfg"
  - prod:  # Add prod.* from base.cfg
    - "/etc/myapp/base.cfg"
    - !P prod  # picks this subpath from what we've got so far
prod:
  foo:
    baz  # might override prod.foo.bar in …/production.cfg
  secrets: !R _  # same effect as above
some:
  more: data
```

As another example, MoaT switched from `moat.cfg` (implied "moat" prefix)
to `moat.yaml` (explicit prefix) with its 26.0 release.

To read the old configuration as-is, you can do this:

```yaml
$base:
  - - !P logging
    - moat: "/etc/moat/moat.cfg"
  - logging:
    - "/etc/moat/moat.cfg"
    - !P logging
```

Thus `foo.bar` in the old `moat.cfg` file is now accessible as
`moat.foo.bar`, while the `logging` part stays at the top level.


### Path References

Use `!P` with a relative path to reference other configuration values:

```yaml
database:
  data_dir:
    main: "/var/lib/myapp"
    backup: "/srv/backup/myapp/data"
backup:
  dest: !P :@.database.data_dir.backup
```

Conceptually, relative paths work like symbolic links in a file system.
They are resolved *after* the otherwise-complete configuration is assembled.


## Configuration Sources

`CfgStore` combines configuration from these sources (in precedence order):

1. **Runtime modifications** - Via `mod()` method
2. **Preloaded config** - Passed to constructor
3. **Environment** - Via `CFG.set_env`
4. **Added files** - Via `add()` method
5. **Default files** - Standard locations or NAME\_CFG envvar
6. **Module configs** - From `_cfg.yaml` files


### Default File Locations

When `name="myapp"`, configuration is read from:

- `~/.config/myapp/config.yaml`
- `~/.config/myapp/config.yaml`
- `~/.config/myapp.yaml`
- `~/.myapp.yaml`
- `/etc/myapp/myapp.yaml`
- `/etc/myapp.yaml`

The `.config` part can be overridden via the `XDG_CONFIG_HOME` envvar (must
be set to an absolute path).

`/etc` can be overridden by setting `MOAT_CONFIG_DIRS`; the XDG equivalent
defaults to `/etc/xdg`, which won't work for us.

The first file that exists is used. You can tell the config system whether
to continue loading by setting `env.load_all`. The default is `False`.


## Module Configuration

MoaT supports preloading default configuration for submodules.

In …/myapp/database/_cfg.yaml:

```yaml
server:
  host: localhost
  port: 23456

# Restrict logging by default
$root:
  logging:
    loggers:
      myapp.database:
        level: ERROR
```

```python
from moat.lib.config import CFG

# Load the _cfg.yaml file from the myapp.database package
CFG.with_("myapp.database")

# The database configuration is now available in all CfgStore instances.
print(CFG.myapp.database.server.host)
```

As in this example, the `$root` directive can be used to modify entries
that are not below the submodule's name. This feature can cause surprises
and thus should be used sparingly.

## Dynamic Configuration

The configuration is updated in-place. You can set a (sub)config's
{meth}`~moat.util.dict.attrdict.updated_` attribute to a notification
function or method.

Alternately, use {class}`~moat.lib.config.monitor`.

```{toctree}
:maxdepth: 2
:hidden:

api
```
