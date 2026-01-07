(moat-lib-path)=
# Hierarchical Paths

```{include} ../../packaging/moat-lib-path/README.md
:start-after: % start main
:end-before: % end main
```

## Manual

The `moat.lib.path` module provides hierarchical path objects for MoaT systems.
Paths are immutable sequences that can represent hierarchical structures with
efficient serialization and manipulation.

### Overview

This module includes:

- **Path objects** - Immutable sequences representing hierarchical paths
- **Multiple representations** - Dot notation and slash notation
- **Type encoding** - Support for strings, numbers, booleans, bytes, and more
- **Path operations** - Concatenation, slicing, element access
- **Efficient transmission** - Path shortening for related sequences
- **Serialization integration** - Works with YAML, CBOR, msgpack
- **Context-aware roots** - Portable paths with root substitution

## Key Components

### Creating Paths

```python
from moat.lib.path import Path, P, PS

# Create from elements
path = Path("config", "database", "host")

# Create from dot notation
path = P("config.database.host")

# Create from slash notation
path = PS("config/database/host")

# All three create the same path
```

### Path Representations

```python
from moat.lib.path import Path

path = Path("foo", "bar", "baz")

# Dot notation (default string representation)
str(path)  # "foo.bar.baz"

# Slash notation
path.slash  # "foo/bar/baz"

# Tuple representation
tuple(path)  # ("foo", "bar", "baz")
```

### Type Encoding

Paths support various data types with special encoding:

```python
from moat.lib.path import P

# Boolean values
p = P("config:t")  # Represents ("config", True)
p = P("config:f")  # Represents ("config", False)

# None and empty string
p = P("config:n")  # Represents ("config", None)
p = P("config:e")  # Represents ("config", "")

# Integers (hex encoding)
p = P("config:x2a")  # Represents ("config", 42)
p = P("config:xff")  # Represents ("config", 255)

# Binary integers
p = P("config:b1010")  # Represents ("config", 10)

# Byte strings (hex encoding)
p = P("data:y48656c6c6f")  # Represents ("data", b"Hello")

# Byte strings (base64 encoding)
p = P("data:sSGVsbG8=")  # Represents ("data", b"Hello")

# Mixed types
p = P("app:x1:t")  # Represents ("app", 1, True)
```

### Escape Sequences

Special characters can be escaped within path elements:

```python
from moat.lib.path import P

# Escape colon
p = P("server::port")  # Represents ("server:port",)

# Escape dot
p = P("file:.txt")  # Represents ("file.txt",)

# Escape space
p = P("hello:_world")  # Represents ("hello world",)

# Escape slash (in slash notation)
p = PS("path:|to:|file")  # Represents ("path/to/file",)
```

### Path Operations

```python
from moat.lib.path import Path

# Concatenation
path1 = Path("foo", "bar")
path2 = Path("baz", "qux")
combined = path1 + path2  # Path("foo", "bar", "baz", "qux")

# Element access
path = Path("a", "b", "c")
path[0]   # "a"
path[-1]  # "c"

# Slicing
path[1:3]  # Path("b", "c")

# Length
len(path)  # 3

# Iteration
for elem in path:
    print(elem)  # prints "a", "b", "c"

# Appending elements
path = path / "d"  # Path("a", "b", "c", "d")

# Removing elements from end
path = path % 1  # Path("a", "b", "c")
```

### Pattern Matching

Paths support Python's structural pattern matching:

```python
from moat.lib.path import Path

path = Path("config", "database", "host")

match path:
    case Path(("config", "database", host)):
        print(f"Database host: {host}")
    case Path(("config", *rest)):
        print(f"Other config: {rest}")
    case _:
        print("Unknown path")
```

### Path Shortening and Lengthening

For efficient transmission of sequences of related paths:

```python
from moat.lib.path import PathShortener, PathLongener, P

# Create a shortener
shortener = PathShortener()

# Shorten a sequence of related paths
depth1, short1 = shortener.short(P("a.b.c.d"))  # (4, ("a","b","c","d"))
depth2, short2 = shortener.short(P("a.b.c.e"))  # (3, ("e",))
depth3, short3 = shortener.short(P("a.b.f"))    # (2, ("f",))

# The shortener removes common prefixes
# Only the differing parts are transmitted

# Create a longener to reconstruct
longener = PathLongener()

# Reconstruct full paths
path1 = longener.long(depth1, short1)  # Path("a","b","c","d")
path2 = longener.long(depth2, short2)  # Path("a","b","c","e")
path3 = longener.long(depth3, short3)  # Path("a","b","f")
```

### Root Path Substitution

Paths can use context-aware root substitution for portability:

```python
from moat.lib.path import Root, Path, P

# Set a root path for the current context
Root.set(Path("my", "app", "config"))

# Paths are automatically normalized
path = Path("my", "app", "config", "database", "host")

# When serialized, the root prefix is replaced with :R
# Making the path portable across different deployments

# The slash representation shows the substitution
path.slash  # ":R/database/host"

# But the original path is preserved
tuple(path)  # ("my", "app", "config", "database", "host")
```

### Logging Integration

```python
from moat.lib.path import logger_for, Path

# Get a logger for a specific path
path = Path("myapp", "module", "component")
logger = logger_for(path)

# Logger name is "myapp.module.component"
logger.info("Component started")
```

## Common Patterns

### Configuration Paths

```python
from moat.lib.path import P

# Hierarchical configuration
db_config = P("config.database")
db_host = db_config / "host"
db_port = db_config / "port"

# Access configuration
config = {
    P("config.database.host"): "localhost",
    P("config.database.port"): 5432,
}
```

### Message Routing

```python
from moat.lib.path import Path

# Route messages by path
def handle_message(path, data):
    match path:
        case Path(("sensors", sensor_id, "temperature")):
            update_temperature(sensor_id, data)
        case Path(("sensors", sensor_id, "humidity")):
            update_humidity(sensor_id, data)
        case Path(("actuators", *rest)):
            control_actuator(rest, data)
```

### Tree Structures

```python
from moat.lib.path import Path

# Represent file system or organizational trees
file_path = Path("home", "user", "documents", "report.pdf")
org_path = Path("company", "engineering", "backend", "team-a")

# Navigate trees
parent = file_path % 1  # Path("home", "user", "documents")
grandparent = file_path % 2  # Path("home", "user")
```

## Integration with Serialization

### YAML Integration

```yaml
# Paths use !P prefix in YAML
database_path: !P config.database
sensor_path: !P sensors:x1:temperature
```

```python
from moat.util import yload, yprint

data = yload("""
  paths:
    - !P config.database
    - !P sensors:x1:temperature
""")

# Paths are automatically deserialized
print(data["paths"][0])  # Path("config", "database")
print(data["paths"][1])  # Path("sensors", 1, "temperature")
```

### CBOR/Msgpack Integration

```python
from moat.util import StdMsgpack

# Paths are automatically encoded
packer = StdMsgpack()
packed = packer.pack(Path("foo", "bar"))
unpacked = packer.unpack(packed)
# unpacked is Path("foo", "bar")
```

```{toctree}
:maxdepth: 2
:hidden:

api
```
