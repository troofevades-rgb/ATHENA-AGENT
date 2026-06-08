#!/usr/bin/env bash
# One-shot setup for athena on Linux/macOS. Mirrors scripts/setup.ps1.
#
# Handles the common setup footguns:
#   - athena not on PATH        -> notes the venv/pip --user bin dir; `python -m
#                                  athena` always works.
#   - Python too old / too new  -> needs 3.10+; warns on 3.14+ (optional-extra
#                                  wheels may be missing). 3.11/3.12 recommended.
#   - PEP 668 externally-managed -> uses a venv by default (system pip is blocked
#                                  on modern Debian/Ubuntu/Homebrew).
#   - Ollama not installed/running -> detects the daemon on :11434, guides.
#   - Model too big for the GPU  -> default qwen2.5-coder:7b (~4.7GB) fits 8GB
#                                  and does tool calling. Override with --model.
#
# Installs EVERY optional feature by default (best-effort per group: a dep that
# can't build on this machine is reported and skipped, never aborting the rest).
# The GPU training stack installs only when a CUDA GPU is detected.
#
# Usage:
#   scripts/setup.sh [--model TAG] [--no-venv] [--skip-model]
#                    [--minimal] [--extras "vision,gateway"] [--train]
#     --minimal          base install only (skip all feature extras)
#     --extras "a,b"     install ONLY these groups (overrides the full default)
#     --train            force the GPU [train] stack even without a detected GPU
set -euo pipefail

MODEL="qwen2.5-coder:7b"
USE_VENV=1
SKIP_MODEL=0
EXTRAS=""
MINIMAL=0
FORCE_TRAIN=0

while [ $# -gt 0 ]; do
  case "$1" in
    --model) MODEL="$2"; shift 2;;
    --no-venv) USE_VENV=0; shift;;
    --skip-model) SKIP_MODEL=1; shift;;
    --extras) EXTRAS="$2"; shift 2;;
    --minimal) MINIMAL=1; shift;;
    --train) FORCE_TRAIN=1; shift;;
    *) echo "unknown arg: $1"; exit 1;;
  esac
done

cyan() { printf '\033[36m  %s\033[0m\n' "$1"; }
ok()   { printf '\033[32m  [ok] %s\033[0m\n' "$1"; }
warn() { printf '\033[33m  [warn] %s\033[0m\n' "$1"; }
fail() { printf '\033[31m  [FAIL] %s\033[0m\n' "$1"; }
step() { printf '\n\033[1m== %s ==\033[0m\n' "$1"; }

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"
step "athena setup ($REPO_ROOT)"

# --- Python -----------------------------------------------------------------
step "Python"
PY="$(command -v python3 || command -v python || true)"
if [ -z "$PY" ]; then
  fail "Python not found. Install Python 3.11 or 3.12 (apt install python3 / brew install python)."
  exit 1
fi
VER="$("$PY" -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
cyan "found Python $VER at $PY"
MAJ="${VER%%.*}"; MIN="${VER##*.}"
if [ "$MAJ" -lt 3 ] || { [ "$MAJ" -eq 3 ] && [ "$MIN" -lt 10 ]; }; then
  fail "Python $VER is too old; athena needs 3.10+."
  exit 1
fi
if [ "$MAJ" -eq 3 ] && [ "$MIN" -ge 14 ]; then
  warn "Python $VER is very new; optional extras may lack wheels. 3.11/3.12 is safest."
fi

# --- venv (default; sidesteps PEP 668 externally-managed) -------------------
if [ "$USE_VENV" -eq 1 ]; then
  step "Virtual environment"
  [ -d "$REPO_ROOT/.venv" ] || "$PY" -m venv "$REPO_ROOT/.venv"
  PY="$REPO_ROOT/.venv/bin/python"
  ok "using venv at $REPO_ROOT/.venv (activate: source .venv/bin/activate)"
fi

# --- pip --------------------------------------------------------------------
if ! "$PY" -m pip --version >/dev/null 2>&1; then
  warn "pip missing; bootstrapping via ensurepip"
  "$PY" -m ensurepip --upgrade
fi

# --- install ----------------------------------------------------------------
step "Installing athena (editable)"

# Base install must succeed; every feature group layers on top of it.
if ! "$PY" -m pip install -e "."; then
  fail "base pip install failed. On Debian/Ubuntu without --no-venv you may hit PEP 668; re-run with a venv (default) or use pipx."
  exit 1
fi
ok "installed athena (base)"

# Best-effort per-group install. pip is atomic per command, so bundling all
# extras would let one un-buildable dep (e.g. libolm) sink the whole set;
# installing each group on its own keeps the rest, and we report what landed.
INSTALLED_EXTRAS=()
FAILED_EXTRAS=()
install_extra() {
  local name="$1"
  cyan "installing extra: $name"
  if "$PY" -m pip install -e ".[$name]"; then
    ok "extra '$name' installed"; INSTALLED_EXTRAS+=("$name")
  else
    warn "extra '$name' failed -- continuing (see pip error above)"; FAILED_EXTRAS+=("$name")
  fi
}

if [ "$MINIMAL" -eq 1 ]; then
  cyan "minimal install -- skipping all optional feature extras"
elif [ -n "$EXTRAS" ]; then
  cyan "installing only the requested extras: $EXTRAS"
  IFS=',' read -ra _reqd <<< "$EXTRAS"
  for e in "${_reqd[@]}"; do
    e="$(echo "$e" | tr -d '[:space:]')"
    [ -n "$e" ] && install_extra "$e"
  done
else
  # Full feature set, cheapest/safest first. 'matrix-e2e' needs libolm (no
  # Windows wheel; needs a compiler elsewhere) and is best-effort. 'train' is
  # GPU-only and gated on CUDA below.
  for e in dev vision proxy observability browser tts gateway gateway-voice matrix-e2e; do
    install_extra "$e"
  done
  if [ "$FORCE_TRAIN" -eq 1 ] || command -v nvidia-smi >/dev/null 2>&1; then
    if ! command -v nvidia-smi >/dev/null 2>&1; then
      warn "--train set but no nvidia-smi found; [train] needs CUDA and may fail."
    fi
    install_extra train
  else
    cyan "skipping [train] (no CUDA GPU detected). Add it later: $PY -m pip install -e \".[train]\""
  fi
fi

# Post-install steps for extras that need a second action to actually work.
case " ${INSTALLED_EXTRAS[*]-} " in
  *" browser "*)
    step "Browser engine (Playwright)"
    cyan "downloading Chromium for the browser tools (one-time, ~150 MB)..."
    "$PY" -m playwright install chromium && ok "Playwright Chromium ready" \
      || warn "playwright download failed; run '$PY -m playwright install chromium' later" ;;
esac
case " ${INSTALLED_EXTRAS[*]-} " in
  *" gateway-voice "*)
    command -v ffmpeg >/dev/null 2>&1 || {
      warn "voice features (faster-whisper) need ffmpeg on PATH, which wasn't found."
      cyan "Install it: apt install ffmpeg / brew install ffmpeg." ; } ;;
esac
case " ${FAILED_EXTRAS[*]-} " in
  *" matrix-e2e "*)
    cyan "matrix-e2e (E2E encryption) needs libolm -- optional; the Matrix gateway still works for unencrypted rooms." ;;
esac

# --- verify (the import that used to crash on a base install) ---------------
step "Verifying athena imports"
"$PY" -c "import athena.tools, athena; print('athena', athena.__version__)" \
  || { fail "athena failed to import. Did you 'git pull' the latest?"; exit 1; }
ok "athena imports cleanly"

# --- Ollama -----------------------------------------------------------------
step "Ollama (local model engine)"
if ! command -v ollama >/dev/null 2>&1; then
  warn "Ollama not installed. Get it: curl -fsSL https://ollama.com/install.sh | sh"
else
  ok "ollama found"
  if curl -fsS --max-time 3 http://127.0.0.1:11434/api/tags >/dev/null 2>&1; then
    ok "Ollama daemon is up"
    if [ "$SKIP_MODEL" -eq 0 ]; then
      cyan "pulling model '$MODEL' (tool-capable; several GB)..."
      ollama pull "$MODEL" && ok "model '$MODEL' ready" || warn "pull failed; try another --model"
    fi
  else
    warn "Ollama daemon not responding on :11434 — start it with 'ollama serve', then re-run."
  fi
fi

# --- install summary ---------------------------------------------------------
if [ "$MINIMAL" -ne 1 ]; then
  step "Feature install summary"
  [ "${#INSTALLED_EXTRAS[@]}" -gt 0 ] && ok "installed: ${INSTALLED_EXTRAS[*]}"
  if [ "${#FAILED_EXTRAS[@]}" -gt 0 ]; then
    warn "skipped/failed: ${FAILED_EXTRAS[*]}"
    cyan "Re-attempt one later:  $PY -m pip install -e \".[<name>]\""
  fi
fi

# --- health check -----------------------------------------------------------
step "Health check"
"$PY" -m athena doctor || true
step "Done"
cyan "Run athena:  python -m athena"
[ "$USE_VENV" -eq 1 ] && cyan "venv: activate first with  source .venv/bin/activate"
