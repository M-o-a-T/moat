# Hierarchical Paths

% start main
% start synopsis

MoaT Paths are immutable sequences that can be represented as dot-separated or
slash-separated strings, with special encoding for various data types.

MoaT paths are typically entered and displayed as simple strings with dots
as separators and colon as "special" markers. For example, `ext:1.set` is a
three-element path consisting of two strings with an integer in between.

There's also a secondary representation that uses slashes (`ext/:1/set`)
for interfacing with the file system or MQTT.

See `pydoc moat.util.path.Path` for details.
Features:

- Immutable path objects with efficient operations
- Dot/colon-notation and slash-notation representations
- Rich type support (strings, numbers, booleans, bytes, and tuples)
- No forbidden characters (e.g. slashes, null bytes) in path elements
- Path shortening/lengthening for efficient transmission
- Context-aware root path substitution
- Integration with YAML, CBOR, and msgpack serialization

MoaT uses `Path` objects mainly as hierarchical object and data accessors.

% end synopsis

## Usage

### Creating paths

```python
from moat.lib.path import Path, P

# Create paths from elements
path = Path("foo", "bar", "baz")
path = P("foo.bar.baz")  # Equivalent dot notation
path = Path.build(("foo", "bar", "baz"))  # from tuples, lists etc.

# Create from various types
path = Path("config", 42, True)  # Mixed types
path = P("config:x2a:t")  # Encoded: config, 0x2a (42), True
```

### Path representation

Paths can be represented in two forms:

**Dot notation**: Elements separated by dots
```python
path = P("foo.bar.baz")
str(path)  # "foo.bar.baz"
```

**Slash notation**: Elements separated by slashes
```python
path = P("foo.bar.baz")
path.slash  # "foo/bar/baz"
```

### Special encodings

MoaT paths support special encoding for non-string values. The most common
are:

```python
# Inline escapes (within an element):
#   ::  escapes : colon
#   :.  escapes . dot
#   :_  escapes   space
#   :|  escapes / slash

# Type prefixes (start a new element):
#   :t   True
#   :f   False
#   :e   empty string
#   :n   None
#   :42  Simple integer
#   :xAB Hex integer (0xAB)
#   :b01 Binary integer (0b01)
#   :yAB Bytestring, hex encoding
#   :sAB Bytestring, base64 encoding

path = P("config:x2a:t")  # Represents ("config", 42, True)
```

### Path operations

```python
from moat.lib.path import Path

path1 = Path("foo", "bar")
path2 = Path("baz", "qux")

# Concatenation
combined = path1 + path2  # Path("foo", "bar", "baz", "qux")

# Element access
path1[0]  # "foo"
path1[-1]  # "bar"

# Slicing
path = Path("a", "b", "c", "d")
path[1:3]  # Path("b", "c")

# Length
len(path)  # 4

# Iteration
for elem in path:
    print(elem)

# Appending single element
path = path / "new"  # a.b.c.d.new
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

% end main

## Integration with Serialization

MoaT paths integrate with serialization formats:

- **YAML**: Uses `!P` prefix for path objects
- **CBOR**: List marked with tag 39 ("Identifier")
- **Msgpack**: extension 3 encapsulates path elements (no list marker)


% end main
