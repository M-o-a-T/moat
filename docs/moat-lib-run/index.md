(moat-lib-run)=
# Main Command Infrastructure

```{toctree}
:hidden:

api
```

The `moat.lib.run` module provides the infrastructure for building command-line
interfaces for MoaT applications.

## Overview

This module includes:

- **Command-line argument parsing** - Integration with asyncclick for async command handling
- **Subcommand loading** - Automatic loading from internal modules and extensions
- **Configuration management** - File loading and command-line configuration
- **Logging setup** - Flexible logging configuration
- **Testing support** - Main entry point wrappers for testing

## Key Components

### Main Command Handler

The `main_` command is the default entry point for MoaT applications:

```python
from moat.lib.run import main_

@main_.command()
async def my_command(ctx):
    """A custom command"""
    print("Hello!")
```

### Subcommand Groups

Use `load_subgroup` to create command groups that automatically discover and load subcommands:

```python
from moat.lib.run import load_subgroup
import asyncclick as click

@load_subgroup(prefix="myapp.commands")
@click.pass_context
async def cli(ctx):
    """Main command group"""
    pass
```

This will automatically load commands from:
- `myapp.commands.*.cli` (internal subcommands)
- Extensions if configured

### Argument Processing

The `attr_args` decorator provides flexible argument handling:

```python
from moat.lib.run import attr_args, process_args

@main_.command()
@attr_args(with_path=True, with_eval=True)
async def configure(**kw):
    """Configure application"""
    config = process_args({}, **kw)
```

Supports various value types:
- `~str` - String values
- `=expr` - Evaluated expressions
- `.path` or `:path` - Path values
- `^proxy` - Remote proxies

### Extension Loading

The `Loader` class provides automatic command loading from both internal modules and extensions:

```python
from moat.lib.run import Loader
from functools import partial
import asyncclick as click

@click.command(cls=partial(Loader,
    _util_sub_pre='myapp.commands',
    _util_sub_post='cli'))
async def main():
    """Main command"""
    pass
```

## API Reference

See the [API documentation](api) for detailed information on all functions and classes.
