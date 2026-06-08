<#
.SYNOPSIS
  One-shot setup for athena on Windows. Installs the package, wires PATH,
  checks Ollama, pulls a tool-capable model sized to your GPU, and runs the
  health check.

.DESCRIPTION
  Automates the setup steps (and guards the footguns) that bite a fresh
  install:

    1. athena command not on PATH        -> adds the Scripts dir to your User
                                            PATH (or use -Venv for isolation);
                                            `python -m athena` always works too.
    2. Cloned into C:\Windows\System32     -> refuses to run from a system dir
       (elevated shells default there).
    3. Python 3.14+ is too new            -> warns; optional extras (Pillow,
                                            imagehash, faster-whisper) lack
                                            wheels there. 3.11 / 3.12 recommended.
    4. Base install crashed on imagehash  -> fixed in current master; this
                                            script installs from your checkout.
    5. Ollama not installed / not running -> detects the daemon on :11434 and
                                            guides you.
    6. Model too big for the GPU          -> default qwen2.5-coder:7b fits 8 GB
                                            (e.g. RTX 3060 Ti) and does tool
                                            calling. Override with -Model.
    7. pip missing                        -> bootstraps via ensurepip.

.PARAMETER Model
  Ollama model to pull (tool-capable). Default qwen2.5-coder:7b (~4.7 GB, fits
  8 GB VRAM). Use qwen2.5-coder:14b for 12-16 GB, qwen3:32b for 24 GB+.

.PARAMETER Venv
  Install into a local .venv instead of the active Python. Avoids all PATH
  editing; activate with .\.venv\Scripts\Activate.ps1.

.PARAMETER SkipModel
  Don't pull a model (you'll set one up yourself).

.PARAMETER Extras
  pip extras to install, e.g. "dev" or "vision,gateway". Default: none (base).

.EXAMPLE
  .\scripts\setup.ps1
.EXAMPLE
  .\scripts\setup.ps1 -Venv -Model qwen2.5-coder:14b -Extras dev
#>
[CmdletBinding()]
param(
    [string]$Model = "qwen2.5-coder:7b",
    [switch]$Venv,
    [switch]$SkipModel,
    [string]$Extras = ""
)

$ErrorActionPreference = "Stop"

function Info($m)  { Write-Host "  $m" -ForegroundColor Cyan }
function Ok($m)    { Write-Host "  [ok] $m" -ForegroundColor Green }
function Warn($m)  { Write-Host "  [warn] $m" -ForegroundColor Yellow }
function Fail($m)  { Write-Host "  [FAIL] $m" -ForegroundColor Red }
function Step($m)  { Write-Host "`n== $m ==" -ForegroundColor White }

# Repo root = parent of this script's directory.
$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

Step "athena setup ($RepoRoot)"

# --- Guard: don't run from a Windows system directory -----------------------
$lower = $RepoRoot.ToLower()
if ($lower -like "*\windows\system32*" -or $lower -like "$($env:WINDIR.ToLower())*") {
    Fail "This repo is inside a Windows system directory: $RepoRoot"
    Info "That usually happens when you 'git clone' from an elevated prompt (cwd defaults to System32)."
    Info "Move it somewhere normal, e.g.:"
    Info "  git clone https://github.com/troofevades-rgb/ATHENA-AGENT.git C:\projects\ATHENA-AGENT"
    exit 1
}

# --- Python ------------------------------------------------------------------
Step "Python"
$py = (Get-Command python -ErrorAction SilentlyContinue)
if (-not $py) { $py = (Get-Command python3 -ErrorAction SilentlyContinue) }
if (-not $py) {
    Fail "Python not found on PATH. Install Python 3.11 or 3.12 from https://python.org (check 'Add to PATH')."
    exit 1
}
$pyExe = $py.Source
$ver = & $pyExe -c "import sys; print('%d.%d' % sys.version_info[:2])"
Info "found Python $ver at $pyExe"
$maj, $min = $ver.Split('.')
if ([int]$maj -lt 3 -or ([int]$maj -eq 3 -and [int]$min -lt 10)) {
    Fail "Python $ver is too old; athena needs 3.10+. Install 3.11 or 3.12."
    exit 1
}
if ([int]$maj -eq 3 -and [int]$min -ge 14) {
    Warn "Python $ver is very new. The base install works, but optional extras"
    Warn "(vision/browser/tts) may fail to build wheels. 3.11 or 3.12 is the safe choice."
}

# --- pip (bootstrap if missing) ---------------------------------------------
& $pyExe -m pip --version *> $null
if ($LASTEXITCODE -ne 0) {
    Warn "pip not found; bootstrapping with ensurepip"
    & $pyExe -m ensurepip --upgrade
}
Ok "pip available"

# --- venv (optional) ---------------------------------------------------------
if ($Venv) {
    Step "Virtual environment"
    if (-not (Test-Path "$RepoRoot\.venv")) { & $pyExe -m venv "$RepoRoot\.venv" }
    $pyExe = "$RepoRoot\.venv\Scripts\python.exe"
    Ok "using venv at $RepoRoot\.venv"
}

# --- install athena ----------------------------------------------------------
Step "Installing athena (editable)"
$target = if ($Extras) { ".[$Extras]" } else { "." }
& $pyExe -m pip install -e $target
if ($LASTEXITCODE -ne 0) { Fail "pip install failed (see above)."; exit 1 }
Ok "installed athena ($target)"

# --- PATH: make the `athena` command available ------------------------------
if (-not $Venv) {
    Step "PATH"
    $scripts = & $pyExe -c "import sysconfig; print(sysconfig.get_path('scripts'))"
    $userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
    if ($userPath -notlike "*$scripts*") {
        [Environment]::SetEnvironmentVariable('Path', "$userPath;$scripts", 'User')
        Ok "added $scripts to your User PATH (open a NEW terminal for 'athena' to resolve)"
    } else {
        Ok "$scripts already on PATH"
    }
    Info "Until a new terminal: use 'python -m athena' (works regardless of PATH)."
}

# --- verify import (this is the line that used to crash on imagehash) -------
Step "Verifying athena imports"
& $pyExe -c "import athena.tools; import athena; print('athena', athena.__version__)"
if ($LASTEXITCODE -ne 0) { Fail "athena failed to import (see above). Did you 'git pull' the latest?"; exit 1 }
Ok "athena imports cleanly"

# --- Ollama ------------------------------------------------------------------
Step "Ollama (local model engine)"
$ollama = (Get-Command ollama -ErrorAction SilentlyContinue)
if (-not $ollama) {
    Warn "Ollama is not installed. athena needs it for local models."
    Info "Install from https://ollama.com/download, then re-run this script."
} else {
    Ok "ollama found"
    # Is the daemon listening on 11434?
    $up = $false
    try {
        $c = New-Object Net.Sockets.TcpClient
        $c.Connect("127.0.0.1", 11434); $up = $c.Connected; $c.Close()
    } catch { $up = $false }
    if (-not $up) {
        Warn "Ollama daemon isn't responding on 127.0.0.1:11434."
        Info "Start it (run 'ollama serve', or just launch the Ollama app), then re-run."
    } else {
        Ok "Ollama daemon is up"
        if (-not $SkipModel) {
            Info "Pulling model '$Model' (tool-capable). This can be several GB..."
            & ollama pull $Model
            if ($LASTEXITCODE -eq 0) { Ok "model '$Model' ready" } else { Warn "model pull failed; pick another with -Model" }
        }
    }
}

# --- JS runtime for the TUI --------------------------------------------------
Step "JS runtime (TUI interface)"
$node = (Get-Command node -ErrorAction SilentlyContinue)
$bun = (Get-Command bun -ErrorAction SilentlyContinue)
if ($node) {
    Ok "node found ($($node.Source)) — the TUI will use it"
} elseif ($bun) {
    Ok "bun found ($($bun.Source)) — athena auto-uses it when node is absent"
} else {
    Warn "No JS runtime found. The interactive TUI needs Node.js or Bun."
    Info "Install Node LTS from https://nodejs.org (simplest), or Bun from https://bun.sh."
    Info "Headless mode (athena -p '...') works without one."
}

# --- health check ------------------------------------------------------------
Step "Health check"
& $pyExe -m athena doctor
Step "Done"
Info "Run athena with:  python -m athena    (or just 'athena' in a new terminal)"
if ($Venv) { Info "venv install: activate first with  .\.venv\Scripts\Activate.ps1" }
