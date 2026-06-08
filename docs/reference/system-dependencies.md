# System dependencies & post-install steps

`pip install` (or `scripts/setup.ps1` / `scripts/setup.sh`) installs athena's
**Python** packages. It does **not** install the external tools, background
services, model files, and credentials that some features need. This page is the
complete map of those — what each is for, how to install it per OS, and exactly
what stops working without it.

Unless a row is marked **Required**, everything here **degrades gracefully**:
athena starts, unaffected features keep working, and the feature that needs the
missing piece reports itself unavailable instead of crashing.

> **TL;DR — to start athena you need two things:** the **Ollama** daemon running
> with a **tool-capable model** pulled, plus **Node.js** (or Bun) if you want the
> interactive TUI (headless `athena -p '...'` works without it). Everything else
> is per-feature and optional.

---

## 1. Required to run

| Need | What for | Install | Without it |
|------|----------|---------|------------|
| **Ollama daemon** | The local model engine athena talks to (`http://127.0.0.1:11434`). | Linux: `curl -fsSL https://ollama.com/install.sh \| sh` · macOS: `brew install ollama` (or the app) · Windows: `winget install Ollama.Ollama` (or installer from [ollama.com/download](https://ollama.com/download)) | **Fatal.** Startup exits with `cannot reach Ollama at ...`. |
| **A tool-capable model** | Model weights, pulled into Ollama's registry. athena needs tool/function calling. | `ollama pull qwen2.5-coder:7b` (size to your GPU — see the VRAM table in the README) | Startup warns `model not pulled`; chat fails when the model is invoked. |
| **Node.js or Bun** | Runs the Ink/React **TUI** bundle as a subprocess. Headless mode doesn't use it. | Linux: `apt install nodejs` · macOS: `brew install node` · Windows: `winget install OpenJS.NodeJS` | Interactive TUI can't start (`doctor` reports it). `athena -p '...'` still works. |

> **⚠️ Default model tag.** The packaged config default (`config.py`) is
> `troofevades-q35:athena` — a **custom** model produced by the training loop's
> export step, **not on the public Ollama registry**. On a fresh machine, either
> set `model` in `~/.athena/config.toml` to a public tool-capable tag (e.g.
> `qwen2.5-coder:7b`), or copy/`ollama push`+`pull` your custom model over. The
> setup scripts pull `qwen2.5-coder:7b` by default to sidestep this.

The daemon must be **running** (`ollama serve`, or just launch the Ollama app).
`ATHENA_NODE_BIN` overrides the JS runtime path if `node`/`bun` aren't on `PATH`.

---

## 2. Per-OS package managers (quick reference)

Every external **binary** athena can use, by platform. Install only what the
features you want require (sections 3–4 map each one).

| Tool | Windows (`winget`) | macOS (`brew`) | Linux (`apt`) |
|------|--------------------|----------------|---------------|
| Ollama | `Ollama.Ollama` | `ollama` | `curl -fsSL https://ollama.com/install.sh \| sh` |
| Node.js | `OpenJS.NodeJS` | `node` | `nodejs` |
| ffmpeg (+ffprobe) | `Gyan.FFmpeg` | `ffmpeg` | `ffmpeg` |
| Tesseract OCR | `UB-Mannheim.TesseractOCR` | `tesseract` | `tesseract-ocr` |
| git | `Git.Git` | `git` (preinstalled) | `git` |
| ripgrep | `BurntSushi.ripgrep.MSVC` | `ripgrep` | `ripgrep` |
| libolm (Matrix E2E) | *(build from source)* | `libolm` | `libolm-dev` |
| libopus (Discord voice) | *(bundled with discord.py[voice])* | `opus` | `libopus0` |
| bubblewrap (shell sandbox) | *(Linux only)* | *(Linux only)* | `bubblewrap` |

---

## 3. Feature → what it needs

| Feature | pip extra | External / post-install requirement | Degrades to |
|---------|-----------|--------------------------------------|-------------|
| Core chat | (base) | Ollama daemon + a model | — (required) |
| Interactive TUI | (base) | Node.js or Bun | headless `-p` mode |
| Web browser tools | `[browser]` | **`python -m playwright install chromium`** (downloads the browser) | tools report unavailable |
| Image analysis (EXIF/ELA/pHash) | `[vision]` | — (pure pip) | "vision deps not installed" |
| OCR (text from images) | — | `pip install pytesseract` **+** Tesseract binary | OCR backend unavailable |
| PDF / DOCX extraction | — | `pip install PyMuPDF` / `pip install python-docx` | format unsupported |
| Video analysis | `[vision]` | **ffmpeg + ffprobe** binary | no frames / no probe metadata |
| Speech-to-text (voice) | `[gateway-voice]` | Whisper model (auto-downloads) + ffmpeg | STT unavailable |
| Text-to-speech (Piper) | `[tts]` / `[gateway-voice]` | a Piper `.onnx` voice (manual download) | TTS unavailable |
| Text-to-speech (Kokoro) | — | `pip install kokoro-onnx` + 2 model files | falls back to Piper/none |
| Discord voice | `[gateway-voice]` | libopus (bundled on Win) + ffmpeg | silent / no playback |
| Matrix E2E encryption | `[matrix-e2e]` | **libolm** (no Windows wheel) | encrypted rooms unreadable |
| Chat gateways | `[gateway]` | per-platform **credentials** (tokens) | that platform off |
| Model training | `[train]` | **NVIDIA CUDA** + torch + unsloth + llama.cpp | (GPU-only; no CPU path) |
| Hosted providers | (base) | **API keys** (`~/.athena/.env`) | Ollama-only |
| Faster search | (base) | `ripgrep` | Python search (slower) |
| Shell sandbox | (base) | `bubblewrap` (Linux) | runs unsandboxed |
| Self-update (git method) | (base) | `git` | other update methods |

---

## 4. Details by area

### Web browser tools — `[browser]`

The `[browser]` extra installs the Playwright **Python package**, but the actual
**Chromium binary is a separate download**:

```bash
pip install -e ".[browser]"
python -m playwright install chromium          # the post-install step
```

Without the Chromium download, `browser_navigate` and friends raise
`BrowserUnavailable`. The setup scripts run `playwright install chromium`
automatically after the `[browser]` extra installs.

### Vision, OCR & documents

- **Image analysis** (`[vision]`: Pillow + imagehash) is pure-pip — no system deps.
- **OCR** needs *both* the `pytesseract` Python wrapper **and** the Tesseract
  engine binary, and **neither is in any extra** — install both manually:
  ```bash
  pip install pytesseract
  # binary: winget install UB-Mannheim.TesseractOCR | brew install tesseract | apt install tesseract-ocr
  ```
- **Documents**: `PyMuPDF` (PDF) and `python-docx` (DOCX) are optional, undeclared
  pip packages loaded lazily — `pip install PyMuPDF python-docx` to enable.
- **Video analysis** shells out to **ffmpeg/ffprobe** for frame extraction and
  codec probing. Install the ffmpeg binary (table in §2).

### Voice & text-to-speech — `[gateway-voice]`, `[tts]`

- **Speech-to-text** (faster-whisper): the Whisper model **auto-downloads** from
  Hugging Face to `~/.cache/huggingface` on first transcription (sized by
  `cfg.audio_whisper_model`: `tiny` ~39 MB → `large-v3` ~1.5 GB; default `base`
  ~74 MB). Needs **ffmpeg** on `PATH`. GPU is optional — CPU works (slower); on
  Windows, GPU acceleration also wants `pip install nvidia-cublas-cu12 nvidia-cudnn-cu12`.
- **Text-to-speech (Piper)**: install `[tts]`, then **manually download a voice**
  (`.onnx` + its `.onnx.json` sidecar) from
  [rhasspy/piper-voices](https://huggingface.co/rhasspy/piper-voices) and set
  `cfg.tts_voice` to the `.onnx` path. Not auto-fetched.
- **Text-to-speech (Kokoro)** — higher quality, **not in any extra**:
  ```bash
  pip install kokoro-onnx
  # download to ~/.athena/voices/ :
  #   kokoro-v1.0.onnx + voices-v1.0.bin
  #   from github.com/thewh1teagle/kokoro-onnx/releases (model-files-v1.0)
  ```
- **Discord voice**: `discord.py[voice]` (in `[gateway-voice]`) bundles `libopus`
  and PyNaCl on Windows; on Linux/macOS install `libopus0` / `opus`. ffmpeg is
  used to play synthesized audio back into the channel.

### Chat gateways & their credentials — `[gateway]`

The `[gateway]` extra installs the transport libraries; **each platform still
needs credentials** you provide (no binary install). Store them via the gateway
config (`<key>_path` files preferred over cleartext):

| Platform | Credential / service you provide |
|----------|----------------------------------|
| Discord | Bot token (Discord developer portal) |
| Slack | Bot token `xoxb-…` + app token `xapp-…` (Socket Mode app) |
| Telegram | Bot token from @BotFather |
| Matrix | Homeserver URL + user ID + access token + device ID |
| Email | IMAP + SMTP host/user/password + from-address (app password for Gmail) |
| Signal | A **Docker bridge** — `bbernhard/signal-cli-rest-api` — + a registered number |
| iMessage | A **BlueBubbles Server** running on a macOS host signed into iMessage |

See [gateway-credentials.md](gateway-credentials.md) for the full credential model.

### Model training loop — `[train]` (GPU only)

The `[train]` extra installs `textual`, `trl`, `peft`, `transformers`, `datasets`,
`accelerate`, and `bitsandbytes`. Several heavyweight pieces are **deliberately
not in the extra** and must be set up by hand on a CUDA workstation:

- **NVIDIA driver + CUDA** — required; the setup scripts only auto-install
  `[train]` when `nvidia-smi` is present. Drivers/toolkit:
  <https://developer.nvidia.com/cuda-downloads>.
- **PyTorch (CUDA build)** — install with a CUDA-matched index, e.g.
  `pip install torch --index-url https://download.pytorch.org/whl/cu121`.
- **unsloth** — QLoRA loader, installed from git (CUDA-only), e.g.
  `pip install "unsloth[cu121-ampere-torch240] @ git+https://github.com/unslothai/unsloth.git"`.
- **bitsandbytes** — the 8-bit optimizer; *is* in `[train]`, but on Windows a
  from-source build needs MSVC (the usual install snag).
- **llama.cpp** — a separate git checkout + cmake build, used by the GGUF export
  step (`convert_hf_to_gguf.py` + `llama-quantize`). **Hard failure** during export
  if absent: `git clone https://github.com/ggerganov/llama.cpp` then build it and
  pass `--llama-cpp` / set `$LLAMA_CPP`.

### Hosted providers & credentials

Ollama needs no key. For hosted providers (Anthropic, OpenAI, OpenRouter, Google,
xAI, Nous), add keys via `athena providers add-key <provider> --key <key>` or by
editing `~/.athena/.env` (copy from `.env.example`). HTTP/SSE **MCP servers**
authenticate via OAuth 2.1 PKCE; tokens are stored automatically per server at
`~/.athena/mcp_tokens/<server_id>.json` on first use.

### Optional accelerators & integrations

All opt-in via config; all degrade gracefully.

| Tool | Enables | Install | Config gate |
|------|---------|---------|-------------|
| **ripgrep** (`rg`) | faster file search | §2 table | auto (used if on PATH) |
| **bubblewrap** (`bwrap`) | sandboxed shell (Linux only) | `apt install bubblewrap` | auto on Linux |
| **git** | `athena update` git method | §2 table | auto |
| **tirith** | pre-Bash command security scan (Linux/macOS) | [NousResearch/tirith releases](https://github.com/NousResearch/tirith/releases) | `bash_tirith_precheck=true` |
| **Codex CLI** (or Aider, etc.) | `delegate_to_cli` to an external coding agent | `npm install -g @openai/codex` | `cli_delegate_enabled=true` |
| **pyright-langserver** / **pylsp** | LSP diagnostics before commit | `pip install pyright-langserver` (or `python-lsp-server[all]`) | `lsp_enabled=true` |

---

## 5. How the setup scripts help

`scripts/setup.ps1` / `scripts/setup.sh` do as much of the above as they can:

- install athena + **every feature extra** (best-effort, per group);
- run **`playwright install chromium`** after the `[browser]` extra;
- gate the GPU `[train]` extra on **CUDA detection**;
- **flag** a missing `ffmpeg` (voice) and note when `[matrix-e2e]` can't build;
- check for **Node/Bun**, the **Ollama daemon**, and console UTF-8;
- pull a tool-capable model and seed `~/.athena/.env`.

What they can't do for you: install system binaries (ffmpeg, tesseract, libolm),
download Piper/Kokoro voice files, provide gateway credentials, or set up the
CUDA/torch/unsloth/llama.cpp training stack. Use this page for those.

Run `athena doctor` any time for a live check of the prerequisites it can probe
(Ollama daemon, configured model pulled, Node on PATH, console encoding, …).
