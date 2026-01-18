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

% end main

## Usage

```python
from moat.lib.config import CFG

# Initial setup (once, at program startup)
CFG(name="myapp")
# loads `/etc/myapp.yaml` (and others)

# Access configuration data
print(CFG.database.host)
```

## Configuration Sources

The `CfgStore` class combines configuration from multiple sources (in order of precedence):

- Command-line arguments (via `mod` method)
- Preloaded configuration (passed to constructor)
- Environment variables (in `CfgStore.env`)
- Explicitly added config files (via `add` method)
- Default config files (from standard paths)
- Static module configurations (loaded via `with_`)

