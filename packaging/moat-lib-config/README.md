# Configuration management

% start main
% start synopsis

This module provides infrastructure for loading, merging, and managing
configuration data from multiple sources. It includes:

- Multi-source configuration loading (files, environment, programmatic)
- Hierarchical configuration with automatic merging
- Context-aware configuration access
- Configuration inheritance with `$base` references
- Lazy loading of module-specific configurations

% end synopsis

## Usage

### Basic configuration setup

```python
from moat.lib.config import CfgStore

# Create a configuration store
cfg = CfgStore(name="myapp")

# Access configuration values
print(cfg.database.host)
print(cfg["database"]["port"])
```

### Using the global configuration object

```python
from moat.lib.config import CFG

# Access configuration through the global CFG object
print(CFG.database.host)

# Set configuration context
from moat.lib.config import CfgStore

cfg = CfgStore(name="myapp", preload={"debug": True})
CFG.set_real_cfg(cfg)
```

### Configuration file format

Configuration files use YAML with special directives:

```yaml
# Basic configuration
database:
  host: localhost
  port: 5432
  cache_dir: "/var/cache/moat/db"

# Inherit from another file
$base: "/etc/myapp/base.cfg"

# Reference other config values
cache:
  path: !P :@.database.cache_dir
```

### Loading module configurations

```python
from moat.lib.config import CfgStore

# Add defaults from a module's _cfg.yaml file
CfgStore.with_("myapp.submodule")
```

## Configuration Sources

The `CfgStore` class combines configuration from multiple sources (in order of precedence):

1. Command-line arguments (via `mod` method)
2. Preloaded configuration (passed to constructor)
3. Environment variables (in `CfgStore.env`)
4. Explicitly added config files (via `add` method)
5. Default config files (from standard paths)
6. Static module configurations (loaded via `with_`)

## Key Classes and Functions

- `CfgStore`: Main configuration storage and management class
- `CFG`: Global configuration accessor object
- `current_cfg`: Context variable for current configuration
- `default_cfg()`: Load configuration from default file paths
- `deref()`: Resolve `$base` and path references in configuration

% end main
