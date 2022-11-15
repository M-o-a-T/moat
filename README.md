# pysignalclijsonrpc - Python API client for signal-cli JSON-RPC

Python client for [signal-cli 0.11.5+](https://github.com/AsamK/signal-cli/blob/master/CHANGELOG.md#0115---2022-11-07) native HTTP endpoint for JSON-RPC methods.

## Installation

```bash
pip install pysignalclijsonrpc
```

## Usage

### Initalization

#### Default

```python
from pysignalclijsonrpc.api import SignalCliJSONRPCApi

signal_cli_rest_api = SignalCliJSONRPCApi(
    endpoint="http://localhost:3000/api/v1/rpc",
    account="+1234567890" # one of your registered signal-cli accounts
)
```

#### Basic authentication

```python
from pysignalclijsonrpc.api import SignalCliJSONRPCApi

signal_cli_rest_api = SignalCliJSONRPCApi(
    endpoint="http://localhost:8080/api/v1/rpc",
    account="+1234567890",
    auth=("user", "password")
)
```

#### HTTPS w/ self-signed certificates

```python
from pysignalclijsonrpc.api import SignalCliJSONRPCApi

signal_cli_rest_api = SignalCliJSONRPCApi(
    endpoint="https://localhost:8443/api/v1/rpc",
    account="+1234567890",
    verify_ssl=False
)
```

### Send message

#### Plain text message

```python
signal_cli_rest_api.send_message("Test")
```

#### Plain text message w/ attachment from file

```python
signal_cli_rest_api.send_message("Test", filenames=["/tmp/some-image.png"])
```

## Support

If you like what i'm doing, you can support me via [Paypal](https://paypal.me/morph027), [Ko-Fi](https://ko-fi.com/morph027) or [Patreon](https://www.patreon.com/morph027).
