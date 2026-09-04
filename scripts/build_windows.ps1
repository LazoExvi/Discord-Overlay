<#
.SYNOPSIS
  Build a self-contained Windows folder (dist\DiscordOverlay), and optionally an installer.

.PARAMETER Variant
  Which ONNX Runtime to bundle. "directml" (default) accelerates on any DirectX 12 GPU
  (NVIDIA, AMD, Intel) and falls back to CPU, so one build suits everyone. "nvidia"
  bundles CUDA (fastest on NVIDIA, several GB). "cpu" is the smallest.

.PARAMETER Installer
  Also compile packaging\DiscordOverlay.iss with Inno Setup into packaging\output.

.PARAMETER SkipTests
  Skip the unit tests before building.

.EXAMPLE
  .\scripts\build_windows.ps1 -Installer
#>
param(
    [ValidateSet("directml", "nvidia", "cpu")]
    [string]$Variant = "directml",
    [switch]$Installer,
    [switch]$SkipTests
)

# Native tools (pip, RapidOCR) write progress to stderr, which "Stop" would treat as
# fatal under Windows PowerShell 5.1. Check exit codes explicitly instead.
$ErrorActionPreference = "Continue"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Python = Join-Path $Root ".build-venv\Scripts\python.exe"

function Invoke-Native {
    param([string]$Description, [scriptblock]$Command)
    & $Command 2>&1 | ForEach-Object { "$_" }
    if ($LASTEXITCODE -ne 0) { throw "$Description failed (exit code $LASTEXITCODE)" }
}
$VersionMatch = Select-String -LiteralPath (Join-Path $Root "discord_overlay\__init__.py") -Pattern '__version__ = "([0-9]+\.[0-9]+\.[0-9]+)"'
if (-not $VersionMatch) { throw "Unable to read the application version" }
$Version = $VersionMatch.Matches[0].Groups[1].Value

if (-not (Test-Path -LiteralPath $Python)) {
    Invoke-Native "Creating build venv" { py -3.12 -m venv (Join-Path $Root ".build-venv") }
}
Invoke-Native "Upgrading pip" { & $Python -m pip install --upgrade pip }
Invoke-Native "Installing requirements" {
    & $Python -m pip install -r (Join-Path $Root "requirements.txt") -r (Join-Path $Root "requirements-dev.txt")
}
$Installed = (& $Python -m pip list --format=json 2>$null | ConvertFrom-Json).name
$Runtimes = @("onnxruntime", "onnxruntime-gpu", "onnxruntime-directml") | Where-Object { $Installed -contains $_ }
if ($Runtimes) { Invoke-Native "Removing other ONNX runtimes" { & $Python -m pip uninstall -y $Runtimes } }
Invoke-Native "Installing $Variant runtime" { & $Python -m pip install -r (Join-Path $Root "requirements-$Variant.txt") }
if (-not $SkipTests) { Invoke-Native "Tests" { & $Python -m pytest (Join-Path $Root "tests") } }

# RapidOCR downloads its models on first use; fetch them now so PyInstaller bundles them.
Invoke-Native "Fetching OCR models" { & $Python -c "from rapidocr import RapidOCR; RapidOCR()" }

Push-Location $Root
try {
    Invoke-Native "PyInstaller" { & $Python -m PyInstaller --clean --noconfirm (Join-Path $Root "packaging\DiscordOverlay.spec") }
    $Payload = Join-Path $Root "dist\DiscordOverlay"
    if (-not (Test-Path (Join-Path $Payload "DiscordOverlay.exe"))) { throw "Build produced no executable" }
    $Size = [math]::Round((Get-ChildItem $Payload -Recurse -File | Measure-Object Length -Sum).Sum / 1MB)
    Write-Host "Built dist\DiscordOverlay ($Variant, $Size MB)."

    if ($Installer) {
        $Iscc = Get-Command iscc.exe -ErrorAction SilentlyContinue
        $IsccPath = if ($Iscc) { $Iscc.Source } else { "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe" }
        if (-not (Test-Path -LiteralPath $IsccPath)) { throw "Inno Setup 6 (ISCC.exe) was not found" }
        Invoke-Native "Inno Setup" { & $IsccPath "/DAppVersion=$Version" (Join-Path $Root "packaging\DiscordOverlay.iss") }
        Write-Host "Installer: packaging\output\DiscordOverlay-Setup-$Version.exe"
    }
} finally {
    Pop-Location
}
