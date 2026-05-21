# Video generation

Athena ships two model-callable tools for native video
generation:

| Tool | Input | Output |
|---|---|---|
| `video_generate` | text prompt + duration + aspect + seed | a video file on disk |
| `animate_image` | source image + motion prompt + duration | a video file on disk |

Both go through the **T5-05 media broker** — the backend is
pluggable via the `video_generation` capability, with local
preferred where a local model exists. The same `MediaRegistry`
that picks vision and embedding backends picks the video one.

## Off by default

`video_generation_enabled = False`. Calling either tool with
the flag off returns:

```json
{"status": "not_enabled", "reason": "..."}
```

No backend contact, no submit, no cost. Opt in per machine.

## The cost / latency guard — never silently spend

Generation is slow (minutes) and can cost real money. Two
thresholds in config decide when athena confirms before
submitting:

```toml
video_confirm_over_seconds = 60.0   # wall-clock estimate
video_confirm_over_cost    = 1.0    # backend-reported $ estimate
```

The guard uses **OR semantics**:

| Estimate | Result |
|---|---|
| `5s, $0.10` | under both → no confirm |
| `120s, $0.10` | over seconds → **confirm** |
| `5s, $5.00` | over cost → **confirm** |
| `5s, cost unknown` | seconds under threshold; cost unknown skips the cost dim → no confirm |
| `120s, $5.00` | over both → confirm |

Setting either threshold to `0` disables that dimension.

When the threshold trips, the orchestrator calls a `confirm`
callback. **Default behaviour with no UI plumbed is to deny**
— the job comes back with `status=declined` and the user sees
the estimate. A buggy callback (raised exception) is also
treated as denial. There is no path where an expensive job
runs silently.

## The pipeline

```text
estimate                       ← cost guard reads this
   ↓
needs_confirm?                 → yes → confirm callback
                                       (default: deny)
   ↓ (no, or approved)
submit                         → JobHandle
   ↓
poll loop                      ← rate-limited via
                                  video_poll_interval_s
   ↓ (status=done)
fetch                          → file on disk
   ↓
SHA-256 + media_log.jsonl row
   ↓
optional vision frame check    → result.frame_check
```

Each step that fails maps to a status the caller can surface
(`error`, `timeout`, `cancelled`), not an exception propagated
into the agent loop. Submit is **never** called when the
estimate-or-confirm gate refuses — the load-bearing
"never silently spend" invariant is a unit test.

## Backend resolution (T5-05)

```python
from athena.videogen import resolve_backend
backend = resolve_backend(cfg)
```

Resolution flow:

1. `cfg.video_backend_prefer` (default `"local"`) overrides
   `cfg.media_backend_prefer` for this capability lookup.
2. `MediaRegistry.backend_for("video_generation")` queries the
   T5-01 manifest — class-level capability, no credentials
   needed.
3. The chosen class is instantiated. A hosted backend without
   credentials raises during construction → resolver returns
   `None` (the tool then surfaces `status=not_configured`).
4. The instance is duck-checked for the four protocol methods
   (`estimate`, `submit`, `poll`, `fetch`). A provider
   declaring the capability but missing one of them → `None`
   (warning logged).

When nothing declares `video_generation`, the tool returns:

```json
{"status": "not_configured", "reason": "no video-generation backend resolved — ..."}
```

## The output

A successful job writes the file under `video_output_dir`
(default `<profile_dir>/videos`) and appends a row to
`media_log.jsonl` in that same directory:

```json
{
  "ts": "2026-05-20T13:42:00.123Z",
  "kind": "video_generation",
  "mode": "text_to_video",
  "backend": "stub_video_local",
  "path": "/path/to/job-abc123.mp4",
  "sha256": "...",
  "duration_s": 5.0,
  "seconds_taken": 4.8,
  "cost_est": null,
  "prompt": "a paper boat drifting down a rain gutter"
}
```

The log is provenance, not credential-grade audit — it's the
"what did athena generate, when, with what prompt" trail. The
file itself is the artifact; the SHA in the log lets you verify
nothing reshuffled it on disk.

## Optional frame check (T4-01)

Pass a `vision_check` callable into `run_generation` (or wire
the T4-01 frame-sanity adapter when it lands) to get a
post-generation sanity report:

```python
result.frame_check  # "frame OK: looks like a paper boat"
```

The check is **advisory** — a vision-check exception is
silently captured (logged at debug) and the generation still
succeeds. The check is for "did the output match the prompt"
diagnostics, not a gate.

## Tool surface

### `video_generate`

```python
video_generate(
    prompt: str,
    duration_s: float = 5.0,
    aspect: str = "16:9",
    seed: int | None = None,
) -> str  # JSON payload
```

### `animate_image`

```python
animate_image(
    image_path: str,
    motion_prompt: str,
    duration_s: float = 4.0,
) -> str  # JSON payload
```

Both return identical JSON shape across all status branches:

```json
{
  "status": "done | declined | error | timeout | cancelled | rejected | not_enabled | not_configured",
  "path": "<file path>",        // when status=="done"
  "sha256": "<64 hex chars>",   // when status=="done"
  "duration_s": <number>,
  "seconds_taken": <number>,
  "cost_est": <number|null>,
  "estimate": {"seconds_est": <number>, "cost_est": <number|null>},
  "backend": "<provider name>",
  "frame_check": "<string|null>",
  "reason": "...",               // when rejected/not_enabled/not_configured
  "error":  "..."                // when error/timeout
}
```

## Configuration

```toml
video_generation_enabled    = false   # opt-in per machine
video_backend_prefer        = "local" # local-preferred resolution
video_confirm_over_seconds  = 60.0    # 0 to disable
video_confirm_over_cost     = 1.0     # 0 to disable
video_output_dir            = "/path/to/videos"  # default <profile_dir>/videos
video_poll_interval_s       = 5.0
```

## Backend adapters

In-tree:

| Adapter | Notes |
|---|---|
| `athena/videogen/backends/stub_local.py` | Synthetic placeholder backend. Writes a tiny file with the `ATHENA-STUB-VIDEO` header + the request payload (so distinct runs have distinct hashes). **Not a real generator** — exists so the broker can resolve and CI can exercise the pipeline end-to-end. Declares `video_generation=True, is_local=True`. |

Real vendor adapters land alongside as `runwayml.py` /
`pika.py` / `ollama_video.py` etc. — each owns its own vendor
specifics + registers via `@register_provider`. **Vendor
specifics are deferred to build time**; the rest of athena
doesn't see them.

To write a new adapter:

1. Implement the `VideoGenerationBackend` Protocol: `estimate`,
   `submit`, `poll`, `fetch`.
2. Inherit from `Provider`, declare `static_capabilities()
   → Capabilities(video_generation=True, ...)`.
3. Register with `@register_provider`.
4. Add an import line in `athena/providers/__init__.py` (the
   side-effect import that runs the decorator on package
   load).

The orchestrator code doesn't change.

## What this does not do

- **No streaming preview.** The result is the finished file.
  Backends that expose progress can populate `JobHandle.progress`;
  the loop logs it but doesn't surface it to the agent.
- **No retries.** A failed job is failed — the caller decides
  whether to re-submit.
- **No content safety.** Backends' own safety filters apply;
  refusals surface as-is in `result.error`.
- **No cross-job sharing.** Each tool call is one
  request → one file. There's no implicit reuse across calls.

## Smoke

```bash
# Enable + run with the stub backend (works out of the box).
# ~/.athena/config.toml:
#   video_generation_enabled = true

athena
> generate a 3-second clip of a paper boat drifting
  # → video_generate prompt="..." duration_s=3
  # → status=done, path=<profile>/videos/stub-XXX.mp4

athena
> generate a 2-minute clip of <prompt>
  # → over seconds threshold → confirm prompt
  # → without a UI plumbed, default-deny → status=declined
  # → no file written
```

## Related

- [Capability broker](capability-broker.md) — the manifest
  routing that picks the backend
- [Provider capabilities](provider-capabilities.md) —
  `video_generation` field declaration
- [Recall](recall.md) — the `media_log.jsonl` format pattern
  this reuses
