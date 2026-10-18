# Device Polling and Server

The `moat modbus dev poll` command implements a bidirectional Modbus gateway that:

1. Periodically polls Modbus devices (clients connecting to remote devices)
2. Serves the polled data via a Modbus TCP server
3. Optionally forwards data to/from MQTT via MoaT-Link/KV

## Architecture

The system uses a client/server model:

- **Client side**: Connects to remote Modbus devices and periodically reads registers
- **Server side**: Exposes a Modbus TCP server that serves the cached register values
- **MQTT integration**: Optionally forwards values to MQTT topics and accepts writes from MQTT

## Configuration Structure

### Basic Example

```yaml
slots:
  1sec:
    read_delay: 1

server:
  - host: 0.0.0.0
    port: 33502

hostports:
  foo.example.com:
    20502:
      1:
        server: 2
        forward: true
        regs:
          power:
            slot: 1sec
            dest: !P grid.s.heat.l1
            register: 84
            type: float
            offset: 42
            server: 99
```

This configuration:

1. Opens a Modbus-TCP connection to `foo.example.com:20502`
2. Every second (via `1sec` slot), requests register 84 from unit 1
3. Applies offset of +42 to the value
4. Sends the result to MQTT topic `grid/s/heat/l1`
5. Creates a TCP Modbus server on port 33502
   - Exposes unit 2 (transparently forwarding to the remote unit 1)
   - The `power` register appears at register 99 (remapped from 84)
   - The served value includes the offset transformation (+42)
6. Unmentioned registers are forwarded transparently (due to `forward: true`)

## Configuration Keys

### Top Level

- **`slots`**: Named time slots for grouping register reads
- **`server`**: List of Modbus TCP servers to create
- **`hostports`**: TCP client connections (host → port → unit → config)
- **`hosts`**: TCP client connections without explicit ports (host → unit → config)
- **`ports`**: Serial client connections (port → unit → config)

### Connections

Next to the units, a `hosts` or `hostports` entry may contain
`timeout`: how long to wait for a reply, in seconds (default 10). A
`ports` entry needs a `serial` section (`baudrate`, `parity`, …), which
also accepts `timeout` (default 0.5).

```yaml
hostports:
  solvis.example:
    502:
      timeout: 3
      1:
        regs:
          ...
```

A request that isn't answered in time fails. Failures are reported to
MoaT-Link's error subsystem, if a link is configured:

- `error.app.modbus.tcp.<host>.<port>`: the TCP connection can't be
  established;
- `….<unit>.<slot>` below that (or below
  `error.app.modbus.serial.<port>`): reading a slot failed, e.g.
  because the device didn't answer within `timeout`.

The entries are removed when the problem goes away.

### Slots

Slots group registers that should be read together in a single Modbus transaction.

```yaml
slots:
  10sec:
    read_delay: 10       # Poll interval in seconds
    write_delay: 1       # Write coalescing delay
    read_align: false    # Align reads to wall clock
    age: 5               # Maximum age before forcing re-read (seconds)
```

- **`read_delay`**: Time in seconds between periodic reads
- **`write_delay`**: Time in seconds to coalesce writes
- **`read_align`**:
  - `true`: Align reads to multiples of read_delay
  - `false`: Read immediately, then wait read_delay
  - `null`: Read immediately, then wait read_delay (no alignment)
- **`age`**: Maximum data age (seconds) before forcing a re-read when accessed via server

### Server Configuration

```yaml
server:
  - host: 0.0.0.0      # Listen address
    port: 33502         # Listen port
    units:              # Unit definitions (optional, auto-populated)
      2:
        regs:
          ...
        bypass:         # optional, see "Bypass"
          ...
    ignored:            # Units to silently ignore
      - 99
    repeat: 2           # see below
```

Some broken clients re-send a request on the same TCP connection, with
the same transaction ID, when they think it has timed out. Such a
retransmission is ignored if it arrives while the original is being
processed, or less than `repeat` seconds (default: 2) after the reply
has been sent.

### Unit Configuration

Each unit (under `hostports`, `hosts`, or `ports`) contains:

- **`server`**: Where this unit appears in the server
  - Integer: Server index × 1000 + unit number
  - Array `[server_index, unit_number]`
  - `none`: Don't serve this unit
- **`forward`**: Control transparent forwarding (default: `true`)
  - `true`: Forward unmentioned registers transparently (**Note**: Full transparent
    forwarding not yet implemented. Currently behaves like `false`)
  - `false`: Only serve explicitly configured registers (returns zeros/errors for
    unconfigured registers)
- **`bypass`**: Switchable bypass of the server unit (see below)
- **`regs`**: Register definitions (see below)

### Bypass

A served unit can be switched, at runtime, to forward *every* request
unchanged instead of answering it from its registers. This allows a
transparent Modbus gateway, e.g. so that a device's original controller,
which talks to a unit we serve, can control the real device.

```yaml
bypass:
  when: !P path.to.flag
  dest:                 # only on a unit in the "server" section
    host: name
    port: 502           # default
    unit: 3
  timeout: 1.5          # per request, seconds (default)
```

- **`when`**: The MoaT-Link item that switches the bypass on (`true`)
  and off (anything else, or missing). It can also be a list
  `[path, attr]`: the flag is the `attr` element of the value at `path`,
  e.g. `[!P app.heat.passthru.state, !P bypass]`.
- **`dest`**: Where requests are sent, via Modbus-TCP. A unit in the
  `server` section needs it.
- Without `dest`, `bypass` belongs to a client unit (next to its
  `server` key). While active, requests to the served unit are executed
  on the client unit directly, i.e. the cached register values are
  ignored, and the client unit's own writes (`src` registers) pause; the
  values that changed meanwhile are written when the bypass ends. Polling
  continues.

The device's exception responses are passed back unchanged. If the
target can't be reached within `timeout`, the reply is
`GATEWAY_TARGET_NO_RESPONSE`.

### Register Configuration

Each register entry supports:

#### Basic Properties

- **`register`**: Modbus register number (0-based)
- **`reg_type`**: Register type (`h`=holding, `i`=input, `c`=coil, `d`=discrete)
- **`type`**: Data type (`uint`, `int`, `float`, `bit`, `invbit`)
- **`len`**: Number of Modbus registers (auto-detected for most types)

#### Slot and Polling

- **`slot`**: Slot name for grouping reads (required for client-side registers)

#### Value Transformation

- **`offset`**: Value offset (applied as `value + offset`)
- **`factor`**: Value multiplier (applied after scale)
- **`scale`**: Power of 10 multiplier (applied as `value * 10^scale`)

Transformations are applied in order: `(raw_value * 10^scale * factor) + offset`

The transformations apply:
- When reading from the Modbus device
- When serving via the Modbus server
- Before forwarding to MQTT

#### MQTT Integration (requires MoaT-Link)

- **`dest`**: MQTT topic(s) to send values to (Path or list of Paths)
  - Written whenever the slot reads new data
- **`src`**: MQTT topic to read values from (Path)
  - Values written to this topic are sent to the Modbus device
- **`mirror`**: If true, echo writes from MQTT back to MQTT on `dest`
- **`idle`**: Value to ignore (don't forward if value equals this)
- **`retain`**: MQTT retain flag (default: true)

#### Server-Side Features

- **`server`**: Register remapping for server
  - Integer: Register number where this value appears in the server
  - `none`: Don't serve this register
  - Omitted: Use original register number
- **`const`**: Constant value or MQTT subscription
  - Scalar: Serve this constant value
  - Path: Subscribe to MQTT topic and serve current value

## Data Flow

### Client → MQTT (Reading)

1. Slot timer triggers
2. Modbus read transaction fetches register(s)
3. Value transformation applied (scale, factor, offset)
4. Value sent to MQTT `dest` topic

### MQTT → Client (Writing)

1. MQTT message received on `src` topic
2. Value transformation reversed
3. Value written to Modbus device

### Client → Server (Transparent)

1. Server receives Modbus request
2. If register is configured:
   - Use cached value from client polling
   - Apply transformations
   - Serve at remapped register number (if specified)
3. If register not configured:
   - Forward transparently to client (if `forward: true`)
   - Return error (if `forward: false`)

### Age-Based Re-reading

When a Modbus client reads from the server:

1. Check age of cached data for requested registers
2. If any register is older than its slot's `age` setting:
   - Trigger an immediate slot read
   - Wait for read to complete
   - Serve the fresh data
   - **Does not** forward to MQTT (to avoid flooding MQTT with messages)
3. If data is fresh enough:
   - Serve cached values immediately

This ensures Modbus clients always get reasonably fresh data while minimizing network traffic.

## Examples

### Simple Read-Only Gateway

```yaml
slots:
  fast:
    read_delay: 1

hostports:
  192.168.1.100:
    502:
      1:
        regs:
          temperature:
            slot: fast
            register: 0
            type: float
```

Reads temperature every second, no server, no MQTT.

### Bidirectional MQTT Gateway

```yaml
slots:
  normal:
    read_delay: 5
    age: 10

server:
  - host: 0.0.0.0
    port: 5502

hostports:
  192.168.1.100:
    502:
      1:
        server: 1
        forward: true
        regs:
          setpoint:
            slot: normal
            register: 10
            type: float
            dest: !P hvac.setpoint.actual
            src: !P hvac.setpoint.command
```

- Reads register 10 every 5 seconds, sends to MQTT
- Accepts setpoint commands from MQTT, writes to register 10
- Serves unit 1 transparently on port 5502
- Forces re-read if data is older than 10 seconds when accessed

### Register Remapping and Transformation

```yaml
server:
  - port: 5502

hostports:
  192.168.1.100:
    502:
      1:
        server: 2
        forward: false
        regs:
          power:
            register: 84
            type: uint
            offset: 1000
            factor: 0.1
            server: 100
```

- Remote device unit 1 appears as unit 2 in server
- Register 84 appears as register 100
- Value transformation: `(raw * 0.1) + 1000`
- Only configured registers are served (forward: false)

### Constant and MQTT-Sourced Values

```yaml
server:
  - port: 5502
    units:
      1:
        regs:
          firmware_version:
            register: 0
            type: uint
            const: 42
          dynamic_value:
            register: 1
            type: float
            const: !P sensors.external.value
```

- Register 0 always returns constant value 42
- Register 1 returns the current value from MQTT topic `sensors/external/value`
- These are server-only registers (no client polling)

## Command Line

```bash
moat modbus dev poll CONFIG.yaml
```

Starts the gateway with the given configuration.
