(moat-link-metrics-backend-akumuli)=
# Akumuli Backend

```{include} ../../packaging/moat-link-metrics-backend-akumuli/README.md
:start-after: % start main
:end-before: % end main
```

## Akumuli-Specific Configuration

When using the Akumuli backend, series entries can use the following
Akumuli-specific fields:

- **mode**: Data-series mode (default: `gauge`). Options:
  - `gauge`: regular time-series values
  - `counter`: monotonically increasing counter
  - `derive`: rate of change

- **tags**: Dictionary of Akumuli tags for the series. At least one tag is required.

- **series**: Akumuli series name.

## Data Types

The Akumuli backend converts numeric Python values (int, float) into
Akumuli data points, applying the configured factor and offset:

```
output = input * factor + offset
```

## Example Configuration

```python
{
    "source": ["sensor", "temperature", "living_room"],
    "series": "temperature",
    "tags": {"room": "living_room", "sensor": "dht22"},
    "mode": "gauge",
    "factor": 1.0,
    "offset": 0.0,
    "t_min": 60.0  # minimum 60 seconds between writes
}
```

## CLI Usage

```bash
# Add a series with Akumuli backend (default)
moat link metrics add myserver room.temp sensor.temp.room temperature room=living_room

# Show configuration
moat link metrics show myserver room.temp
```

```{toctree}
:maxdepth: 2
:hidden:

api
```
