---
description: Clean patterns for stitching together external APIs and services
name: api-integration-glue
created_at: '2026-05-26T00:00:00Z'
last_activity_at: '2026-05-26T00:00:00Z'
pinned: false
state: active
use_count: 0
write_origin: foreground
---
# API Integration Glue

The boring, high-leverage patterns for stitching external APIs into a
codebase without creating a fragile rats-nest. The premise:
integration code rots faster than any other code because the external
surface keeps moving. Write it so it rots gracefully.

## When to use this skill

Use when adding a call to an external API, MCP server, webhook
target, or third-party SDK. Skip for purely internal function calls
or in-process imports.

## The five integration rules

### 1. Boundary objects, not raw responses

External payloads enter the codebase exactly once and become typed
internal objects. Nothing downstream sees raw JSON.

```python
@dataclass
class WeatherReading:
    temp_c: float
    humidity: float
    timestamp: datetime

def fetch_weather(city: str) -> WeatherReading:
    raw = httpx.get(f"https://api.example.com/weather/{city}").json()
    return WeatherReading(
        temp_c=raw["main"]["temp"],
        humidity=raw["main"]["humidity"],
        timestamp=datetime.fromtimestamp(raw["dt"]),
    )
```

When the external API renames a field, you fix ONE function. Without
boundary objects, you grep across 40 files.

### 2. Errors are typed too

Don't propagate ``HTTPError`` deep into the codebase. Wrap external
failures in domain-specific exceptions at the boundary:

```python
class WeatherUnavailable(Exception):
    """The weather service didn't return usable data."""

try:
    raw = httpx.get(url, timeout=5.0)
    raw.raise_for_status()
except (httpx.HTTPError, httpx.TimeoutException) as e:
    raise WeatherUnavailable(f"weather lookup failed for {city}") from e
```

The caller now handles one exception type, regardless of whether the
failure was a 503, a timeout, or a DNS failure.

### 3. Retry with bounds

For any idempotent external call, retry with exponential backoff and
a HARD CAP:

```python
for attempt in range(3):
    try:
        return _call()
    except WeatherUnavailable:
        if attempt == 2:
            raise
        time.sleep(2 ** attempt)
```

Caps matter. Unbounded retries turn one outage into a cascading
incident.

### 4. Auth in one place

Bearer tokens, API keys, OAuth flows — they live in ONE module per
integration. Every other file imports the configured client; nobody
else reads env vars directly.

```python
# providers/weather/client.py — the only file that touches the key
def _build_client():
    key = os.environ["WEATHER_API_KEY"]
    return httpx.Client(headers={"Authorization": f"Bearer {key}"})

CLIENT = _build_client()
```

When you rotate the key or move to OAuth, you fix one module.

### 5. Mock at the boundary

Tests mock ``fetch_weather`` (your boundary function), NEVER ``httpx``
or the response JSON shape directly. The boundary function is your
seam — mocking inside it couples tests to the external API's shape.

```python
# good — boundary mock
monkeypatch.setattr("myapp.weather.fetch_weather",
                    lambda city: WeatherReading(20.0, 0.5, now()))

# bad — coupled to external shape
monkeypatch.setattr("httpx.get",
                    lambda url: Mock(json=lambda: {"main": {...}}))
```

## Anti-patterns to refuse

- **Untyped dict propagation**: passing the raw API response dict
  multiple function calls deep. Always convert at the boundary.
- **Try/except: pass**: swallowing external errors silently. Wrap and
  raise.
- **Auth scattered**: every file reads ``os.environ["FOO_KEY"]``.
  Centralize.
- **Retry without cap**: ``while True: try: ... except: continue``.
  Always cap.
