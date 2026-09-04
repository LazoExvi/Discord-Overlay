<#
.SYNOPSIS
  Build a self-contained Windows folder (dist\DiscordOverlay) with PyInstaller.

.PARAMETER Variant
  Which ONNX Runtime to bundle: cpu, nvidia, or directml. Defaults to cpu, which
  runs everywhere; GPU variants only work on machines with that vendor's card.

.EXAMPLE
  .\scripts\build_windows.ps1 -Variant nvidia
#>
param(
    [ValidateSet("cpu", "nvidia", "directml")]
    [string]$Variant = "cpu"
)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Python = Join-Path $Root ".build-venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $Python)) {
    py -3.12 -m venv (Join-Path $Root ".build-venv")
}
& $Python -m pip install --upgrade pip
& $Python -m pip install -r (Join-Path $Root "requirements.txt") -r (Join-Path $Root "requirements-dev.txt")
$Installed = (& $Python -m pip list --format=json | ConvertFrom-Json).name
$Runtimes = @("onnxruntime", "onnxruntime-gpu", "onnxruntime-directml") | Where-Object { $Installed -contains $_ }
if ($Runtimes) { & $Python -m pip uninstall -y $Runtimes }
& $Python -m pip install -r (Join-Path $Root "requirements-$Variant.txt")
& $Python -m pytest (Join-Path $Root "tests")

Push-Location $Root
try {
    & $Python -m PyInstaller --clean --noconfirm (Join-Path $Root "packaging\DiscordOverlay.spec")
} finally {
    Pop-Location
}
Write-Host "Built dist\DiscordOverlay ($Variant). Zip that folder to share it."
