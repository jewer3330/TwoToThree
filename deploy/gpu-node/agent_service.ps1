# Selfreg GPU Agent: windowless background service launcher (Windows)
#
# Usage (powershell):
#   powershell -ExecutionPolicy Bypass -File agent_service.ps1 `
#       -EnvName prod -ControlUrl http://8.153.36.240:8000 `
#       -AgentId gpu-4060-prod -AgentName RTX4060 -Token <TOKEN> `
#       -ExternalRoot D:\print3d
#
# Features:
#   - Launches agent main process with pythonw.exe -> no console window
#   - All child processes (nvidia-smi/blender/runner) run with
#     CREATE_NO_WINDOW (server/agent.py `_no_window`) -> no flashing boxes
#   - stdout/stderr redirected to <ExternalRoot>\agent-<EnvName>.{out,err}.log
#   - Idempotent: kills same-env agent first; safe under schtasks self-heal
param(
    [Parameter(Mandatory=$true)][string]$EnvName,
    [Parameter(Mandatory=$true)][string]$ControlUrl,
    [Parameter(Mandatory=$true)][string]$AgentId,
    [Parameter(Mandatory=$true)][string]$AgentName,
    [string]$Token = '',
    [string]$ExternalRoot = 'D:\print3d',
    [string]$PythonBase = ''
)
$ErrorActionPreference = 'SilentlyContinue'
if (-not $PythonBase) {
    $cand = @(
        "$env:LOCALAPPDATA\Programs\Python",
        "C:\Users\$env:USERNAME\AppData\Local\Programs\Python"
    )
    foreach ($base in $cand) {
        if (Test-Path $base) {
            $v = Get-ChildItem $base -Directory -Filter 'Python*' |
                 Sort-Object Name -Descending | Select-Object -First 1
            if ($v) { $PythonBase = Join-Path $base $v.Name; break }
        }
    }
}
if (-not $PythonBase -or -not (Test-Path $PythonBase)) {
    Write-Output "python dir not found: $PythonBase"
    exit 2
}
$pyw = Join-Path $PythonBase 'pythonw.exe'
if (-not (Test-Path $pyw)) {
    Write-Output "pythonw.exe missing (need full Python install): $pyw"
    exit 2
}
# Idempotent: stop same-env agent first
Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
    Where-Object { $_.CommandLine -match ('server\.agent ' + [regex]::Escape($EnvName)) } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
Start-Sleep -Seconds 2
$logBase = Join-Path $ExternalRoot "agent-$EnvName"
$outLog = "$logBase.out.log"
$errLog = "$logBase.err.log"
$env:STUDIO_EXTERNAL_ROOT = $ExternalRoot
$env:CONTROL_URL = $ControlUrl
$env:AGENT_ID = $AgentId
$env:AGENT_NAME = $AgentName
if ($Token) { $env:WORKER_TOKEN = $Token }
$p = Start-Process -FilePath $pyw -ArgumentList '-u','-m','server.agent',$EnvName `
    -WorkingDirectory (Join-Path $ExternalRoot 'TwoToThree') `
    -WindowStyle Hidden `
    -RedirectStandardOutput $outLog -RedirectStandardError $errLog -PassThru
Start-Sleep -Seconds 6
if ($p.HasExited) {
    Write-Output ("agent start failed exit=" + $p.ExitCode)
    Get-Content $outLog -Tail 5 -ErrorAction SilentlyContinue
    Get-Content $errLog -Tail 5 -ErrorAction SilentlyContinue
    exit 1
}
Write-Output "agent($EnvName) running in background pid=$($p.Id) pythonw=$pyw"
