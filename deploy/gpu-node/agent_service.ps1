# Selfreg GPU Agent 无窗口后台启动模板（Windows）
#
# 用法（管理员 / 任意用户，需 pythonw 与仓库已就位）：
#   powershell -ExecutionPolicy Bypass -File deploy\gpu-node\agent_service.ps1 `
#       -Env prod -ControlUrl http://8.153.36.240:8000 `
#       -AgentId gpu-4060-prod -AgentName RTX4060 -Token <WORKER_TOKEN> `
#       -ExternalRoot D:\print3d
#
# 特性：
#   - 用 pythonw.exe 启动 agent 主进程 → 无控制台窗口（不闪框）
#   - agent 内部所有子进程(nvidia-smi/blender/runner)均带 CREATE_NO_WINDOW
#     （见 server/agent.py `_no_window`）→ 执行任务时也不弹黑框
#   - stdout/stderr 重定向到 <ExternalRoot>\agent-<Env>.{out,err}.log（日志落盘）
#   - 幂等：先终止同名 agent 再启动（可被 schtasks 每分钟托管做自愈）
param(
    [Parameter(Mandatory=$true)][string]$Env,
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
    Write-Output "python 目录未找到: $PythonBase"
    exit 2
}
$pyw = Join-Path $PythonBase 'pythonw.exe'
if (-not (Test-Path $pyw)) {
    Write-Output "pythonw.exe 不存在（需完整安装版 Python）: $pyw"
    exit 2
}
# 幂等：杀掉同名 agent（防多实例互踢/占卡）
Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
    Where-Object { $_.CommandLine -match ('server\.agent ' + [regex]::Escape($Env)) } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
Start-Sleep -Seconds 2
$logBase = Join-Path $ExternalRoot "agent-$Env"
$outLog = "$logBase.out.log"
$errLog = "$logBase.err.log"
$env:STUDIO_EXTERNAL_ROOT = $ExternalRoot
$env:CONTROL_URL = $ControlUrl
$env:AGENT_ID = $AgentId
$env:AGENT_NAME = $AgentName
if ($Token) { $env:WORKER_TOKEN = $Token }
$p = Start-Process -FilePath $pyw -ArgumentList '-u','-m','server.agent',$Env `
    -WorkingDirectory (Join-Path $ExternalRoot 'TwoToThree') `
    -WindowStyle Hidden `
    -RedirectStandardOutput $outLog -RedirectStandardError $errLog -PassThru
Start-Sleep -Seconds 6
if ($p.HasExited) {
    Write-Output "agent 启动失败 exit=" + $p.ExitCode
    Get-Content $outLog -Tail 5 -ErrorAction SilentlyContinue
    Get-Content $errLog -Tail 5 -ErrorAction SilentlyContinue
    exit 1
}
Write-Output "agent($Env) 后台运行中 pid=$($p.Id) pythonw=$pyw"
