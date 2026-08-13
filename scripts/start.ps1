$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
if (-not (Test-Path '.venv\Scripts\python.exe')) { throw '缺少 .venv，请先运行 scripts/install.ps1' }
Start-Process -FilePath '.venv\Scripts\python.exe' -ArgumentList '-m','uvicorn','server.main:app','--host','0.0.0.0','--port','8000' -WindowStyle Hidden
Start-Process -FilePath 'cmd.exe' -ArgumentList '/c npm run dev' -WorkingDirectory $root -WindowStyle Hidden
Write-Host '2D→3D Studio 已启动： http://127.0.0.1:5173'
Write-Host 'API 文档： http://127.0.0.1:8000/api/docs'
