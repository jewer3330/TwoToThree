$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
if (-not (Test-Path '.venv')) { python -m venv .venv }
& '.venv\Scripts\python.exe' -m pip install -r requirements.txt
cmd /c npm install
Write-Host '安装完成。运行 powershell -ExecutionPolicy Bypass -File scripts/start.ps1'
