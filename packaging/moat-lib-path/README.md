# Hierarchical Paths

% start main
% start synopsis

MoaT Paths are immutable sequences that can be represented as dot-separated or
slash-separated strings, with special encoding for various data types.

MoaT paths are typically entered and displayed with dots as separators and
colon as "special" markers. For example, `ext:1.set` is a three-element
path consisting of two strings with an integer in between.

There's a secondary representation that uses slashes (`ext/:1/set`)
for interfacing with the file system or MQTT.

See `pydoc moat.lib.path.Path` for details.

The MoaT ecosystem uses `Path` objects as hierarchical accessors for objects and data.

% end synopsis

## Usage

### Creating paths

```python
from moat.lib.path import Path, P

# Create paths from elements
path = Path()  # empty path

path = P("foo.bar.baz")  # dot notation
assert path == Path.build(("foo", "bar", "baz"))  # assemble from tuples, lists etc.

# Create from various types
path = Path.build(("config", 42, True))  # Mixed types
assert path == P("config:x2a:t")  # config, 0x2a (42), True
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

### Special codes

MoaT paths support non-string path elements. The most common are:

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

path1 = P("foo.bar")
path2 = P("baz.qux")

# Concatenation
combined = path1 + path2  # Path("foo", "bar", "baz", "qux")

# Element access
path1[0]  # "foo"
path1[-1]  # "bar"

# Slicing
path = Path("a.b.c.d")
path[1:3]  # ("b", "c")

# Length
len(path)  # 4

# Iteration
for elem in path:
    print(elem)

# Appending single element
path = path / "new"  # a.b.c.d.new
```

% end main

## Serialization

MoaT paths integrate with serialization formats:

- **YAML**: Use a `!P` prefix for Path objects (dot notation)
- **CBOR**: List marked with tag 39 ("Identifier")
- **Msgpack**: extension 3 encapsulates path elements
