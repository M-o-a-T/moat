# moat-lib-broadcast

Broadcasting support for MoaT applications.

## Overview

This module provides broadcasting support with weak references, allowing multiple readers to receive messages from a single source with backpressure handling and data loss detection.

## Features

- **Broadcaster**: A message broadcaster that sends messages to multiple readers
- **BroadcastReader**: A reader that receives messages from a broadcaster
- **LostData**: Exception indicating data loss with dropped message count
- Weak reference support to prevent memory leaks
- Backpressure handling for slow readers
- Queue-based buffering

## Installation

```bash
pip install moat-lib-broadcast
```

## Usage

```python
from moat.lib.broadcast import Broadcaster, BroadcastReader

# Create a broadcaster
broadcaster = Broadcaster()

# Create readers
reader1 = broadcaster.new_reader()
reader2 = broadcaster.new_reader()

# Send messages
await broadcaster.send("Hello")
await broadcaster.send("World")

# Receive messages
msg1 = await reader1.get()
msg2 = await reader2.get()
```

## License

This project is part of the MoaT ecosystem and is licensed under the same terms.
