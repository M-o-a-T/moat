(moat-lib-broadcast)=
# Configuration Management

```{include} ../../packaging/moat-lib-broadcast/README.md
:start-after: % start main
:end-before: % end main
```

## Manual

The `moat.lib.broadcast` module provides infrastructure for loading, merging, and
managing configuration data for MoaT applications.

### Overview

This module includes:

- **Multi-source configuration** - Load from files, environment variables, and programmatic sources
- **Hierarchical merging** - Automatically combine configurations with proper precedence
- **Context-aware access** - Configuration available through context variables
- **Lazy module loading** - Module-specific configs loaded on demand
- **Configuration references** - Use `$base` and path references to share values

## Key Components

### Configuration Store

The `CfgStore` class manages configuration from multiple sources:

```python
from moat.lib.broadcast import CfgStore

# Create a configuration store
cfg = CfgStore(
    name="myapp",
    preload={"debug": True},
    load_all=False  # Load only first found config file
)

# Access values
database_host = cfg.database.host
cache_size = cfg["cache"]["size"]

# Modify configuration
cfg.mod(["database", "port"], 5433)
cfg.add("/etc/myapp/custom.cfg")
```

### Global Configuration Object

The `CFG` object provides global access to configuration:

```python
from moat.lib.broadcast import CFG, CfgStore

# Set up configuration
cfg = CfgStore(name="myapp")
CFG.set_real_cfg(cfg)

# Access anywhere in your code
print(CFG.database.host)
```

### Configuration Context

Use context managers for temporary configuration changes:

```python
from moat.lib.broadcast import CFG, CfgStore

cfg = CfgStore(name="myapp", preload={"mode": "production"})

with CFG.with_config(cfg):
    # This code sees the production config
    process_data()
```

## Configuration Files

Configuration files use YAML format with special directives:

### Basic Configuration

```yaml
database:
  host: localhost
  port: 5432
  name: myapp

cache:
  enabled: true
  size: 1000
```

### Inheritance with $base

```yaml
# Load base configuration
$base: "/etc/myapp/base.cfg"

# Override specific values
database:
  host: db.example.com
```

### Multiple Base Files

```yaml
# Merge from multiple sources
$base:
  - "/etc/myapp/base.cfg"
  - "/etc/myapp/production.cfg"
```

### Path References

Use `!P` to reference other configuration values:

```yaml
database:
  data_dir: /var/lib/myapp
  backup_dir: !P :@.database.data_dir/backup  # References data_dir
```

## Configuration Sources

The `CfgStore` combines configuration from these sources (in precedence order):

1. **Runtime modifications** - Via `mod()` method
2. **Preloaded config** - Passed to constructor
3. **Environment** - Via `CfgStore.env`
4. **Added files** - Via `add()` method
5. **Default files** - Standard locations
6. **Module configs** - From `_cfg.yaml` files

### Default File Locations

When `name="myapp"`, configuration is loaded from:

- `~/.config/myapp.cfg`
- `~/.myapp.cfg`
- `/etc/myapp/myapp.cfg`
- `/etc/myapp.cfg`

The first found file is used (unless `load_all=True`).

## Module Configuration

Load default configuration for submodules:

```python
from moat.lib.broadcast import CfgStore

# Loads _cfg.yaml from myapp.database package
CfgStore.with_("myapp.database")

# Configuration now available in all CfgStore instances
```

```{toctree}
:maxdepth: 2
:hidden:

api
```
