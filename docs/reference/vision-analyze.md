# `vision_analyze` — image reasoning + forensics

One tool, seven modes. Every read is hash-logged.

## Modes

| Mode        | What it does                                                   | Local? | Reasoning vs. forensic |
|-------------|----------------------------------------------------------------|--------|-------------------------|
| `describe`  | Provider passthrough: caption / answer about the image content | provider | reasoning |
| `exif`      | Read EXIF tags (Make, Model, DateTime, Software, Lens, GPS …)  | yes    | forensic |
| `ela`       | Error Level Analysis — heuristic for spliced JPEG regions       | yes    | forensic |
| `crop`      | Write a sub-region to disk as PNG; useful before a follow-up describe | yes  | reasoning |
| `histogram` | Per-channel intensity histogram for exposure / clipping / cast | yes    | reasoning |
| `phash`     | Perceptual hash (phash / dhash / ahash / whash) — fingerprint  | yes    | forensic |
| `compare`   | Two-image compare: metadata-strip + pHash distance              | yes    | forensic |

"Local" means no network and no provider dispatch. "Provider"
means the call goes through whatever provider class declares
`vision=True` in its T5-01 capability manifest — typically a
multimodal Ollama model in a local-only deployment.

## Hash-log (provenance trail)

Every call writes a JSONL row to `<profile_dir>/vision_audit.jsonl`:

```json
{"ts":"2026-05-20T13:42:00.123456Z","mode":"describe",
 "path":"/abs/path","sha256":"abcd…","bytes":30447,
 "extra":{"quality":80,"patches":3}}
```

The bytes themselves are **not** stored — a SHA-256 fingerprint is
enough for "is this the same file someone else has a copy of"
without the log growing unboundedly.

## `describe` mode — passthrough + tiling

The image goes through to the model as a content block in the
right shape for the active provider:

- **Anthropic**: `{"type":"image","source":{"type":"base64","media_type":...,"data":...}}`
- **OpenAI / OpenAI-compatible**: `{"type":"image_url","image_url":{"url":"data:image/...;base64,...","detail":"<tile-label>"}}`
- **Ollama**: a sentinel dict the `ollama` provider unwraps onto the message's top-level `images=` list (see T4-01.7)

When the long edge exceeds the provider's recommended cap, the
input is **tiled, not downsampled**. Caps:

| Provider   | Long-edge cap |
|------------|--------------:|
| Anthropic  | 1568 px        |
| OpenAI     | 2048 px        |
| Ollama     | 1344 px        |

Tiling preserves every pixel — a 2400×1200 image over Ollama's
1344 cap becomes a 2×2 grid of ~1200-px tiles, each carrying a
distinct `tile_R_C` label so multi-turn discussion has a stable
handle. Downsampling would irreversibly destroy fine detail (the
exact kind of detail forensic reads care about).

## `exif` mode

```json
{"mode":"exif",
 "path":"/abs/photo.jpg",
 "sha256":"…",
 "exif":{"Make":"Canon","Model":"EOS R5","DateTime":"2026:05:20 12:34:56",
         "Software":"Adobe Photoshop 24.7","GPSInfo":{...}}}
```

Keys are friendly names (e.g. `"Make"`, `"DateTime"`) when
known; unknown tags appear as `"0x<hex>"`. All values are
JSON-safe.

**Limitations.** Pillow's `Image.Exif()` reader sees what it sees
— GPS sub-IFDs, MakerNote blocks, and some legacy formats need
`piexif` or `exiftool` for full visibility. Document this when
the absence of an expected key matters; we keep those external
tools optional rather than hard dependencies.

## `ela` mode — Error Level Analysis

```json
{"mode":"ela",
 "path":"/abs/photo.jpg",
 "sha256":"…",
 "quality":80,
 "threshold":15,
 "max_diff":42,
 "mean_diff":3.21,
 "patches":[{"box":[200,200,300,300],"max_diff":42,"mean_diff":18.7},
            ...]}
```

The recipe: decode → re-encode at the configured quality → diff
the two decodes → tile the diff into a 16×16 grid and report
tiles whose max-pixel diff exceeds `threshold`.

### ELA is a SIGNAL, NOT A VERDICT

Bright patches mean "this region's JPEG compression-level differs
from its neighbours." Most splices show up that way. So do:

- a region that was lightly edited but at a quality matching
  the host (won't show)
- a flat region (won't show: nothing to compare against)
- a PNG converted to JPEG once (whole frame "shows" — noise, not
  signal)
- double-compressed forgeries that match the host's quality
  curve (the classic ELA evasion)

Pair with `exif` + `phash` + `compare` for triangulation. Never
report a verdict from ELA alone — `vision_analyze` returns the
signals, the analyst weighs them.

## `phash` + `compare` modes

```json
{"mode":"phash",
 "algorithm":"phash",
 "hash_size":8,
 "hex":"e6b1c39e1cf83cf9"}
```

Distance reading (`compare` returns this as
`phash_distance_reading`):

| Distance | Reading                              |
|---------:|--------------------------------------|
|        0 | identical                            |
|    1..8  | strong-match (mild transform)        |
|   8..16  | similar (larger transform)           |
|     >16  | probably-different-scenes            |

`compare` mode also returns `metadata_strip_check`:

```json
{"verdict":"stripped" | "intact" | "different" | "indeterminate",
 "missing_keys":["Make","Model","Software"],
 "present_keys":["Orientation","DateTime"],
 "original_keys":["Make","Model","Software","Orientation","DateTime"]}
```

`"stripped"` = suspect has zero EXIF and the original had some.
`"intact"` = suspect carries every key the original did.
`"different"` = suspect has EXIF but is missing keys from the
original (partial strip / re-export). `"indeterminate"` = the
original itself has no EXIF — can't draw a conclusion.

## `crop` + `histogram` modes

Both are utilities. `crop` writes the sub-region to
`<profile_dir>/vision/crops/<srcname>_crop_<x0>_<y0>_<x1>_<y1>.png`
and returns the new path + sha256. `histogram` returns per-
channel bucket counts (bins must divide 256).

## Configuration

```toml
# ~/.athena/config.toml — defaults shown
vision_enabled = true                  # off → tool refuses all modes
vision_max_input_pixels = 80_000_000   # bomb guard (~80 Mpx)
vision_ela_quality = 80
vision_ela_threshold = 15
vision_phash_algorithm = "phash"       # phash | dhash | ahash | whash
vision_phash_size = 8
vision_long_edge_cap = 0               # 0/None = per-provider default
vision_crop_dir = ""                   # "" = <profile>/vision/crops
```

## Dependencies

`Pillow>=10` (already in athena's runtime), `imagehash>=4.3`.
Install via `pip install -e ".[vision]"`. `piexif` and the
external `exiftool` binary are optional and documented as gaps
in the EXIF section above.

## Non-goals

- **OCR.** Not in T4-01. The describe mode can read visible text
  via the multimodal model when one is configured, but there's
  no dedicated text-extraction backend.
- **C2PA / Content Credentials.** Not in T4-01. A separate phase
  would add C2PA verification on top of the existing EXIF +
  pHash + strip-check signal set.
- **GPS extraction.** Pillow surfaces `GPSInfo` as a nested dict
  in `exif` mode; we don't decode lat/lon — `exiftool` is the
  right tool when GPS coordinates matter.
- **Verdicts.** The tool returns signals; the analyst (or the
  model reasoning over the signals) weighs them.

## Reference

- Tile policy + per-provider caps: `athena/vision/passthrough.py`
- Hash-log shape: `athena/vision/hashlog.py`
- ELA / pHash / EXIF / strip-check: `athena/vision/imageops.py`
- Tool dispatch + mode handlers: `athena/vision/analyze.py`
