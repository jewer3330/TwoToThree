$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
if (-not (Test-Path '.venv\Scripts\python.exe')) { throw '缺少 .venv，请先运行 scripts/install.ps1' }
$logs = Join-Path $root 'logs'
New-Item -ItemType Directory -Force -Path $logs | Out-Null
$vite = Join-Path $root 'node_modules\vite\bin\vite.js'
if (-not (Test-Path $vite)) { throw '缺少 node_modules，请先运行 npm install' }
& npm.cmd run build
if ($LASTEXITCODE -ne 0) { throw '前端构建失败' }
Start-Process -FilePath '.venv\Scripts\python.exe' -ArgumentList '-m','uvicorn','server.main:app','--host','0.0.0.0','--port','8000' -WorkingDirectory $root -RedirectStandardOutput (Join-Path $logs 'api.out.log') -RedirectStandardError (Join-Path $logs 'api.err.log') -WindowStyle Hidden
Start-Process -FilePath 'node.exe' -ArgumentList $vite,'preview','--host','0.0.0.0','--port','5173','--strictPort' -WorkingDirectory $root -RedirectStandardOutput (Join-Path $logs 'web.out.log') -RedirectStandardError (Join-Path $logs 'web.err.log') -WindowStyle Hidden
Write-Host '2D→3D Studio 已启动： http://127.0.0.1:5173'
Write-Host 'API 文档： http://127.0.0.1:8000/api/docs'
