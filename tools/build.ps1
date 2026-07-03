# Build the Daily Digest Windows installer end-to-end.
#
# One-time prerequisites (run once in PowerShell):
#   winget install Python.Python.3.12
#   winget install JRSoftware.InnoSetup
#   py -m pip install --upgrade pyinstaller
#
# Then just run:  powershell -ExecutionPolicy Bypass -File tools\build.ps1
# Output: Output\DailyDigest-Setup-<version>.exe

$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
Set-Location $root

Write-Host "==> Cleaning previous build..."
Remove-Item -Recurse -Force build, dist -ErrorAction SilentlyContinue

Write-Host "==> Freezing app with PyInstaller..."
py -m PyInstaller --noconfirm DailyDigest.spec
if (-not (Test-Path "dist\DailyDigest\DailyDigest.exe")) {
    Write-Error "PyInstaller did not produce dist\DailyDigest\DailyDigest.exe"; exit 1
}

# Locate the Inno Setup compiler.
$iscc = @(
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
    "${env:ProgramFiles}\Inno Setup 6\ISCC.exe"
) | Where-Object { Test-Path $_ } | Select-Object -First 1

if (-not $iscc) {
    Write-Warning "Inno Setup (ISCC.exe) not found. The frozen app is in dist\DailyDigest\."
    Write-Warning "Install it (winget install JRSoftware.InnoSetup) and re-run to build the installer."
    exit 0
}

Write-Host "==> Building installer with Inno Setup..."
& $iscc "installer.iss"
Write-Host "==> Done. Installer is in the Output\ folder."
