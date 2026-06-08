<#
.SYNOPSIS
  Dump everything relevant for diagnosing an athena setup on Windows
  (OS, VM detection, GPU/VRAM, Python/venv, athena + deps, JS runtime,
  Ollama, terminal/encoding). Paste the output when asking for help.

.EXAMPLE
  .\scripts\diagnose.ps1
#>
function H($t) { Write-Host "`n-- $t --" -ForegroundColor Cyan }
Write-Host "===== ATHENA DIAGNOSTIC =====" -ForegroundColor Green

H "OS / VM"
$cs = Get-CimInstance Win32_ComputerSystem
$os = Get-CimInstance Win32_OperatingSystem
$bios = Get-CimInstance Win32_BIOS
"$($os.Caption)  build $($os.BuildNumber)"
"Manufacturer: $($cs.Manufacturer)   Model: $($cs.Model)   BIOS: $($bios.Manufacturer)"
$vm = "$($cs.Manufacturer) $($cs.Model) $($bios.Manufacturer) $($bios.SerialNumber)"
if ($vm -match 'VMware|VirtualBox|innotek|Virtual Machine|Hyper-V|QEMU|KVM|Xen|Parallels|Bochs|Red Hat') {
    "VM: YES  ($($Matches[0]))"
} else {
    "VM: likely physical hardware"
}
"RAM: $([math]::Round($cs.TotalPhysicalMemory/1GB,1)) GB   logical CPUs: $($cs.NumberOfLogicalProcessors)"

H "GPU (VRAM caps the model size)"
Get-CimInstance Win32_VideoController | ForEach-Object { "$($_.Name)   driver $($_.DriverVersion)" }
if (Get-Command nvidia-smi -ErrorAction SilentlyContinue) {
    nvidia-smi --query-gpu=name,memory.total --format=csv,noheader
} else {
    "nvidia-smi: not found (no NVIDIA driver, or not on PATH)"
}

H "Python / venv"
"python -> $((Get-Command python -ErrorAction SilentlyContinue).Source)"
python --version 2>&1
"pip    -> $((Get-Command pip -ErrorAction SilentlyContinue).Source)"
"VIRTUAL_ENV: $($env:VIRTUAL_ENV)"
python -c "import sys; print('sys.executable:', sys.executable)" 2>&1

H "athena + core deps"
python -c "import athena, rich, httpx, prompt_toolkit, yaml, sqlalchemy; print('athena', athena.__version__, '@', athena.__file__); print('core deps: OK')" 2>&1

H "JS runtime (TUI interface)"
"node -> $((Get-Command node -ErrorAction SilentlyContinue).Source)"
if (Get-Command node -ErrorAction SilentlyContinue) { node --version }
"bun  -> $((Get-Command bun -ErrorAction SilentlyContinue).Source)"
if (Get-Command bun -ErrorAction SilentlyContinue) { bun --version }
"ATHENA_NODE_BIN: $($env:ATHENA_NODE_BIN)"

H "Ollama"
"ollama -> $((Get-Command ollama -ErrorAction SilentlyContinue).Source)"
try {
    "models: " + (((Invoke-RestMethod http://127.0.0.1:11434/api/tags -TimeoutSec 3).models | ForEach-Object name) -join ', ')
} catch {
    "daemon NOT responding on 127.0.0.1:11434"
}

H "Terminal / encoding (owl rendering)"
"Windows Terminal: $([bool]$env:WT_SESSION)"
chcp
"OutputEncoding: $([Console]::OutputEncoding.WebName)"
# Braille built from code points (no literal non-ASCII in this .ps1, so
# PowerShell 5.1 -- which reads scripts as ANSI -- parses it cleanly).
python -c "print('braille glyph test ->', ''.join(chr(c) for c in (0x2840,0x2880,0x28ff,0x28b7)))" 2>&1
Write-Host "(if the braille shows as '?'/boxes in YOUR terminal but pastes correctly elsewhere, it's a font/encoding issue -> use Windows Terminal + Cascadia Mono)" -ForegroundColor DarkGray

Write-Host "`n===== END =====" -ForegroundColor Green
