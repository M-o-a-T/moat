(moat-lib-path)=
# Hierarchical Paths

```{include} ../../packaging/moat-lib-path/README.md
:start-after: % start main
:end-before: % end main
```

### Pattern Matching

Paths support Python's structural pattern matching:

```python
from moat.lib.path import Path, P

path = P("config.database.host")

match path:
    case Path(("config", "database", host)):
        print(f"Database host: {host}")
    case Path(("config", *rest)):
        print(f"Other config: {rest}")
    case _:
        print("Unknown path")
```

### Path shortening/lengthening

For efficient transmission of sequences of related paths:

```python
from moat.lib.path import PathShortener, PathLongener

# Shortener removes common prefixes
shortener = PathShortener()
depth1, short1 = shortener.short(P("a.b.c.d"))  # (4, ("a","b","c","d"))
depth2, short2 = shortener.short(P("a.b.c.e"))  # (3, ("e",))
depth3, short3 = shortener.short(P("a.b.f"))    # (2, ("f",))

# Longener reconstructs full paths
longener = PathLongener()
path1 = longener.long(depth1, short1)  # Path("a","b","c","d")
path2 = longener.long(depth2, short2)  # Path("a","b","c","e")
path3 = longener.long(depth3, short3)  # Path("a","b","f")
```

### Root path substitution

Paths can use context-aware root placeholders:

```python
from moat.lib.path import Root, Path

# Set a root path
Root.set(Path("my", "app", "config"))

# Paths starting with the root get special encoding
path = Path("my", "app", "config", "database", "url")
# When serialized, "my.app.config" is replaced with :R placeholder
path.str == ":R.database.url"
# This makes paths portable across different root configurations
```

The `Root` object (`:R`) is used by MoaT as its MQTT prefix. Three other
prefixes (`P`, `Q` and `S`; `P_Root` etc.) are available for application use.

### Integration with Serialization

MoaT paths integrate with serialization formats:

- **YAML**: Uses `!P` prefix for path objects
- **CBOR**: List marked with tag 39 ("Identifier")
- **Msgpack**: extension 3 encapsulates path elements (no list marker)


### Logging Integration

```python
from moat.lib.path import logger_for, P

# Get a logger for a specific path
path = P("myapp.module.component")
logger = logger_for(path)

# Logger name is "myapp.module.component"
logger.info("Component started")
```

## Common Patterns

### Configuration

```python
from moat.lib.path import P

# Config paths
db_config = P("config.database")
db_host = db_config / "host"
db_port = db_config / "port"

# Config data
data = attrdict(config=attrdict(database=attrdict(host="loclhost",port="5432")))

# Accessing the data
assert data.get_(db_port) == 5432
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

```python
from moat.util import yload, yprint

data = yload("""
config:
  paths:
    db: !P config.database:0
  database:
    - host: test.example
      port: 33221
    - host: more.test.example
      port: 33222
""")

db = data.get_(data.paths.db)
assert db.host == "test.example"
```

### CBOR/Msgpack Integration

For CBOR, we use tag 39 with a list.

With MsgPack we use extension 3. The contents are the concatenated
encodings of the path's elements, in order.

Both codecs encode roots as leading proxies: "R" for the `R` root, and
`_PS` etc. for the S, P and Q roots. See {py:class}`moat.lib.proxy.Proxy`
for details.

Serializing relative paths is not supported.

```python
from moat.lib.codec.moat_cbor import Codec as StdCBOR

# Paths are automatically encoded
packer = StdCBOR()
path = Path.build(("foo", "bar"))
packed = packer.pack(path)
unpacked = packer.unpack(packed)
assert unpacked == path
```

```{toctree}
:maxdepth: 2
:hidden:

api
```
