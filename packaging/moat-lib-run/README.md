# moat-lib-run

% start main
% start synopsis

Main command entry point infrastructure for MoaT applications.

% end synopsis

This module provides the infrastructure for building command-line interfaces
for MoaT applications. It includes:

- Command-line argument parsing with Click integration
- Subcommand loading from internal modules and extensions
- Configuration file handling
- Logging setup
- Main entry point wrappers for testing

## Usage

### Basic command setup

```python
from moat.lib.run import main_, wrap_main

@main_.command()
async def my_command(ctx):
    """A simple command"""
    print("Hello from my command!")
```

### Loading subcommands

Use `load_subgroup` to create command groups that automatically load subcommands:

```python
from moat.lib.run import load_subgroup
import asyncclick as click

@load_subgroup(prefix="myapp.commands")
@click.pass_context
async def cli(ctx):
    """Main command group"""
    pass
```

### Processing command-line arguments

The `attr_args` decorator and `process_args` function provide flexible
argument handling:

```python
from moat.lib.run import attr_args, process_args

@main_.command()
@attr_args(with_path=True)
async def configure(**kw):
    """Configure the application"""
    config = process_args({}, **kw)
    # config now contains parsed arguments
```

## Key Functions

- `main_`: The default main command handler
- `wrap_main`: Wrapper for the main command, useful for testing
- `load_subgroup`: Decorator to create command groups with automatic subcommand loading
- `attr_args`: Decorator for adding flexible argument handling to commands
- `process_args`: Function to process command-line arguments into configuration
- `Loader`: Click group class that loads commands from submodules and extensions

% end main
