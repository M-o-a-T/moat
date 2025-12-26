(moat-lib-proxy)=
# Proxy Helpers

```{include} ../../packaging/moat-lib-proxy/README.md
:start-after: % start main
:end-before: % end main
```

## Manual

The `moat.lib.proxy` module provides infrastructure for serializing and
deserializing objects across process boundaries or network connections.

### Overview

This module includes:

- **Transparent proxies** - Reference objects without copying them
- **Data-carrying proxies** - Include object state in the proxy
- **Name registration** - Map objects to/from proxy names
- **Serialization integration** - Works with CBOR, msgpack, YAML
- **Object reconstruction** - Rebuild objects on the receiving end

## Key Components

### Proxy Registration

Register classes and objects for proxy serialization:

```python
from moat.lib.proxy import name2obj, obj2name

# Register a class
class RemoteService:
    def process(self, data):
        return data.upper()

name2obj("myapp.RemoteService", RemoteService)

# Get the proxy name for an object
service = RemoteService()
proxy_name = obj2name(service)
print(proxy_name)  # "myapp.RemoteService"
```

### Creating Proxies

Create proxy references to objects:

```python
from moat.lib.proxy import as_proxy, get_proxy

# Create a proxy
obj = RemoteService()
proxy = as_proxy(obj)

# The proxy can be serialized and sent elsewhere
# Later, retrieve the original object
original = get_proxy(proxy)
```

### Data-Carrying Proxies

Use `DProxy` for objects that should carry their state:

```python
from moat.lib.proxy import DProxy

class ConfigData(DProxy):
    """Configuration that travels with its data"""

    def __init__(self, host, port):
        self.host = host
        self.port = port

    def __reduce__(self):
        # Define serialization
        return (self.__class__, (self.host, self.port))

# Register the class
name2obj("myapp.ConfigData", ConfigData)

# Create and serialize
config = ConfigData("localhost", 8080)
# When serialized, both the class reference and data are included
```

### Object Serialization

Wrap and unwrap objects for transmission:

```python
from moat.lib.proxy import wrap_obj, unwrap_obj

# Prepare an object for serialization
class MyData:
    def __init__(self, value):
        self.value = value

    def __reduce__(self):
        return (self.__class__, (self.value,))

name2obj("myapp.MyData", MyData)
data = MyData(42)

# Serialize
wrapped = wrap_obj(data)
# ... send wrapped data over network ...

# Deserialize
reconstructed = unwrap_obj(wrapped)
print(reconstructed.value)  # 42
```

## Integration with Serialization

The proxy system integrates with MoaT's serialization formats:

### CBOR Integration

```python
from moat.util import yload, yprint

# Proxied objects are automatically handled in CBOR
data = {"service": as_proxy(RemoteService())}
serialized = cbor.dumps(data)
deserialized = cbor.loads(serialized)
```

### Msgpack Integration

```python
from moat.util._msgpack import StdMsgpack

packer = StdMsgpack()
packed = packer.pack({"obj": proxy})
unpacked = packer.unpack(packed)
```

### YAML Integration

```yaml
# Proxies can be referenced in YAML
service: !Proxy myapp.RemoteService
```

## Common Patterns

### Remote Method Calls

```python
# Server side
class Calculator:
    def add(self, a, b):
        return a + b

name2obj("app.Calculator", Calculator)

# Client side gets a proxy and can call methods
calc_proxy = get_proxy(received_proxy)
result = calc_proxy.add(5, 3)
```

### Configuration Distribution

```python
# Use DProxy to send configuration with structure
class DatabaseConfig(DProxy):
    def __init__(self, host, port, name):
        self.host = host
        self.port = port
        self.name = name

    def __reduce__(self):
        return (self.__class__, (self.host, self.port, self.name))

# Configuration can be serialized and distributed
config = DatabaseConfig("db.example.com", 5432, "myapp")
```

## Error Handling

```python
from moat.lib.proxy import NoProxyError

try:
    obj = get_proxy(some_proxy)
except NoProxyError:
    # Proxy reference is invalid
    print("Cannot resolve proxy")
```

```{toctree}
:maxdepth: 2
:hidden:

api
```
