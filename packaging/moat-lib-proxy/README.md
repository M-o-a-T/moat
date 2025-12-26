# Proxy helpers

% start main
% start synopsis

This module provides proxy helpers for serializing and deserializing objects
across process boundaries or network connections. It includes:

- Transparent proxy objects that can be serialized and reconstructed
- Object registration and name mapping for proxied objects
- Data-carrying proxies (DProxy) for including object state
- Integration with CBOR, msgpack, and other serialization formats

% end synopsis

## Usage

### Basic proxy registration

```python
from moat.lib.proxy import name2obj, obj2name, Proxy

# Register a class for proxying
class MyService:
    def do_something(self):
        return "result"

# Register the class with a name
name2obj("myapp.MyService", MyService)

# Get the proxy name for an object
service = MyService()
proxy_name = obj2name(service)  # Returns "myapp.MyService"
```

### Using proxies

```python
from moat.lib.proxy import as_proxy, get_proxy

# Create a proxy reference to an object
obj = MyService()
proxy = as_proxy(obj)  # Returns a Proxy object

# Later, retrieve the original object
original = get_proxy(proxy)  # Returns the MyService instance
```

### Data-carrying proxies (DProxy)

```python
from moat.lib.proxy import DProxy

class MyData(DProxy):
    """A proxy that includes object state"""

    def __init__(self, value):
        self.value = value

    def __reduce__(self):
        # Define how to serialize the object
        return (self.__class__, (self.value,))

# The object can be serialized with its state
data = MyData(42)
# When serialized and deserialized, the value is preserved
```

### Working with serialization

```python
from moat.lib.proxy import wrap_obj, unwrap_obj

# Serialize an object for transmission
class MyObject:
    pass

name2obj("myapp.MyObject", MyObject)
obj = MyObject()

# Wrap for serialization
wrapped = wrap_obj(obj)  # Creates a serializable representation

# Later, unwrap to reconstruct
reconstructed = unwrap_obj(wrapped)  # Returns a MyObject instance
```

## Integration with Serialization Formats

This module integrates with MoaT's serialization libraries:

- **CBOR**: `moat.lib.codec.cbor`
- **Msgpack**: `moat.lib.codec.msgpack`
- **YAML**: Supports proxy references in configuration files

% end main
