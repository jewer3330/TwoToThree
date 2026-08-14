@echo off
setlocal EnableExtensions
cd /d "%~dp0"

title Restart 2D-to-3D Studio
echo [1/3] Stopping services on ports 5173 and 8000...
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ports = 5173, 8000; $ids = Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue | Where-Object { $ports -contains $_.LocalPort } | Select-Object -ExpandProperty OwningProcess -Unique; foreach ($processId in $ids) { $p = Get-Process -Id $processId -ErrorAction SilentlyContinue; if ($p -and ($p.ProcessName -match '^(node|python|pythonw)$')) { Write-Host ('  stopping ' + $p.ProcessName + ' PID ' + $processId); Stop-Process -Id $processId -Force -ErrorAction SilentlyContinue } }"

timeout /t 2 /nobreak >nul

echo [2/3] Starting API and web UI...
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start.ps1"
if errorlevel 1 goto :failed

echo [3/3] Waiting for API and web UI health checks...
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command ^
  "$api = $false; $web = $false; 1..30 | ForEach-Object { if (-not $api) { try { Invoke-WebRequest 'http://127.0.0.1:8000/api/system/health' -UseBasicParsing -TimeoutSec 1 | Out-Null; $api = $true } catch {} }; if (-not $web) { try { Invoke-WebRequest 'http://127.0.0.1:5173/' -UseBasicParsing -TimeoutSec 1 | Out-Null; $web = $true } catch {} }; if (-not ($api -and $web)) { Start-Sleep -Milliseconds 500 } }; if (-not ($api -and $web)) { Write-Host ('API=' + $api + ' Web=' + $web); exit 1 }"
if errorlevel 1 goto :health_failed

echo.
echo Restart complete.
echo Web UI: http://127.0.0.1:5173
echo API:    http://127.0.0.1:8000/api/docs
echo.
pause
exit /b 0

:health_failed
echo.
echo Services were started, but the API health check timed out.
echo Check logs\api.err.log and logs\web.err.log for details.
pause
exit /b 1

:failed
echo.
echo Restart failed. Check that .venv and Node.js are installed.
pause
exit /b 1
