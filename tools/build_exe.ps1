# Builds dist\OnTopGaming\ with a single OnTopGaming.exe (Windows, Python 3.12).
#
#   powershell -ExecutionPolicy Bypass -File tools\build_exe.ps1
#
# The .exe contains the app and every Python package it needs. It does NOT contain your data
# (data\), your settings, or sync_config.json (which holds the sync token): those are created or
# copied next to the .exe on the computer that uses it.

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $root

py -3.12 -m pip install --quiet -r requirements.txt pyinstaller
if ($LASTEXITCODE -ne 0) { throw "Could not install the build requirements." }

$out = Join-Path $root "dist\OnTopGaming"
if (Test-Path -LiteralPath $out) { Remove-Item -LiteralPath $out -Recurse }

py -3.12 -m PyInstaller main.py `
    --name OnTopGaming `
    --onefile --windowed --noconfirm --clean `
    --distpath (Join-Path $root "dist\_build") `
    --workpath (Join-Path $root "build") `
    --specpath (Join-Path $root "build") `
    --exclude-module PyQt5 --exclude-module PyQt6 --exclude-module PySide2 --exclude-module PySide6 `
    --exclude-module wx --exclude-module IPython --exclude-module pytest --exclude-module scipy `
    --exclude-module pandas
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed." }

New-Item -ItemType Directory -Path $out | Out-Null
Move-Item -LiteralPath (Join-Path $root "dist\_build\OnTopGaming.exe") -Destination $out
Remove-Item -LiteralPath (Join-Path $root "dist\_build")
Copy-Item -LiteralPath (Join-Path $root "sync_config.example.json") -Destination $out

Write-Host ""
Write-Host "Built: $out\OnTopGaming.exe"
Write-Host "Copy the whole OnTopGaming folder to the other computer."
