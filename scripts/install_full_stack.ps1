param(
    [ValidateSet('All','App','Blender','Hunyuan','Backends','ComfyUI')]
    [string]$Component = 'All',
    [switch]$SkipLargeModels,
    [switch]$SkipSmokeTests,
    [switch]$ValidateOnly
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$Root = Split-Path -Parent $PSScriptRoot
$ExternalRoot = if ($env:STUDIO_EXTERNAL_ROOT) { $env:STUDIO_EXTERNAL_ROOT } else { Join-Path $HOME 'AIData\3d' }
$Local = Join-Path $ExternalRoot 'local'
$BlenderRoot = Join-Path $Local 'Blender52'
$BlenderExe = Join-Path $BlenderRoot 'blender.exe'
$BlenderMsi = Join-Path $Local 'blender-5.2.0-windows-x64.msi'
$HunyuanSource = Join-Path $Local 'Hunyuan3D-2.1-space'
$HunyuanModel = Join-Path $Local 'Hunyuan3D-2.1-model'
$HunyuanVenv = Join-Path $Local 'hunyuan-bootstrap'
$HunyuanPython = Join-Path $HunyuanVenv 'Scripts\python.exe'
$Sf3dRoot = Join-Path $Local 'stable-fast-3d'
$Sf3dPython = Join-Path $Sf3dRoot '.venv-runtime\Scripts\python.exe'
$TripoRoot = Join-Path $Local 'TripoSR'
$TripoPython = Join-Path $TripoRoot '.venv-runtime\Scripts\python.exe'
$HunyuanRevision = '82920d643c0dc2f7bfd7255f45f62d386edfe60c'
$Sf3dRevision = 'ff21fc491b4dc5314bf6734c7c0dabd86b5f5bb2'
$TripoRevision = '107cefdc244c39106fa830359024f6a2f1c78871'

function Step([string]$Text) { Write-Host "`n==> $Text" -ForegroundColor Cyan }
function Includes([string]$Name) { return $Component -eq 'All' -or $Component -eq $Name }
function Assert-LastExit([string]$Action) { if ($LASTEXITCODE -ne 0) { throw "$Action failed with exit code $LASTEXITCODE" } }

function Ensure-Command([string]$Command, [string]$WingetId) {
    if (Get-Command $Command -ErrorAction SilentlyContinue) { return }
    $winget = Get-Command winget.exe -ErrorAction SilentlyContinue
    if (-not $winget) { throw "Missing $Command and winget. Install $Command, then rerun this script." }
    & $winget.Source install --id $WingetId --exact --accept-package-agreements --accept-source-agreements --silent
    Assert-LastExit "Installing $WingetId"
    $env:Path = [Environment]::GetEnvironmentVariable('Path','Machine') + ';' + [Environment]::GetEnvironmentVariable('Path','User')
    if (-not (Get-Command $Command -ErrorAction SilentlyContinue)) { throw "$Command was installed but is not visible in PATH; open a new terminal and rerun." }
}

function Ensure-Repo([string]$Url, [string]$Path, [string]$Revision) {
    if (-not (Test-Path (Join-Path $Path '.git'))) {
        if (Test-Path $Path) {
            if ((Get-ChildItem $Path -Force | Measure-Object).Count -gt 0) {
                Write-Host "Using existing non-git source directory: $Path"
                return
            }
        } else { New-Item -ItemType Directory -Force -Path (Split-Path $Path -Parent) | Out-Null }
        git clone $Url $Path
        Assert-LastExit "Cloning $Url"
    }
    $current = (git -C $Path rev-parse HEAD).Trim()
    if ($current -ne $Revision) {
        if (git -C $Path status --porcelain) { throw "Uncommitted changes in $Path; refusing to switch revision." }
        git -C $Path fetch origin $Revision
        Assert-LastExit "Fetching $Revision"
        git -C $Path checkout --detach $Revision
        Assert-LastExit "Checking out $Revision"
    }
}

function Install-Backend([string]$Name, [string]$Path, [string]$PythonPath) {
    if (-not (Test-Path $PythonPath)) { uv venv (Split-Path (Split-Path $PythonPath -Parent) -Parent) --python 3.10 }
    $env:UV_HTTP_TIMEOUT = '600'
    uv pip install --python $PythonPath wheel 'setuptools==69.5.1' scikit-build-core cmake ninja pybind11
    uv pip install --python $PythonPath --index-url https://download.pytorch.org/whl/cu121 'torch==2.5.1+cu121' 'torchvision==0.20.1+cu121'
    Push-Location $Path
    try { uv pip install --python $PythonPath --no-build-isolation -r requirements.txt } finally { Pop-Location }
    & $PythonPath -c "import torch; assert torch.cuda.is_available(); print('$Name CUDA:', torch.__version__, torch.cuda.get_device_name(0))"
    Assert-LastExit "$Name CUDA verification"
}

New-Item -ItemType Directory -Force -Path $Local | Out-Null

Step 'Checking/installing workstation prerequisites'
Ensure-Command 'git.exe' 'Git.Git'
Ensure-Command 'python.exe' 'Python.Python.3.13'
Ensure-Command 'node.exe' 'OpenJS.NodeJS.LTS'
if (-not (Get-Command uv.exe -ErrorAction SilentlyContinue)) {
    python -m pip install --user uv
    Assert-LastExit 'Installing uv'
    $userScripts = python -c "import site,os; print(os.path.join(site.USER_BASE,'Scripts'))"
    $env:Path = "$userScripts;$env:Path"
}

if ($ValidateOnly) {
    Step 'Validating the installed stack'
    & (Join-Path $Root '.venv\Scripts\python.exe') (Join-Path $Root 'scripts\check_environment.py')
    if (Test-Path $BlenderExe) { & $BlenderExe --background --version | Select-Object -First 1 }
    foreach ($pythonPath in @($HunyuanPython,$Sf3dPython,$TripoPython)) {
        if (Test-Path $pythonPath) { & $pythonPath -c "import torch; print(torch.__version__, torch.cuda.is_available())" }
    }
    exit 0
}

if (Includes 'App') {
    Step 'Installing web application and API dependencies'
    if (-not (Test-Path (Join-Path $Root '.venv\Scripts\python.exe'))) { uv venv (Join-Path $Root '.venv') --python 3.13 }
    uv pip install --python (Join-Path $Root '.venv\Scripts\python.exe') -r (Join-Path $Root 'requirements.txt')
    & (Get-Command npm.cmd).Source install --prefix $Root
    Assert-LastExit 'npm install'
}

if (Includes 'Blender') {
    Step 'Installing local Blender 5.2.0'
    if (-not (Test-Path $BlenderExe)) {
        if (-not (Test-Path $BlenderMsi)) {
            Invoke-WebRequest 'https://download.blender.org/release/Blender5.2/blender-5.2.0-windows-x64.msi' -OutFile $BlenderMsi
        }
        $arguments = @('/a', $BlenderMsi, '/qn', "TARGETDIR=$BlenderRoot")
        $process = Start-Process msiexec.exe -ArgumentList $arguments -Wait -PassThru
        if ($process.ExitCode -ne 0) { throw "Blender MSI extraction failed: $($process.ExitCode)" }
    }
    & $BlenderExe --background --version | Select-Object -First 1
}

if (Includes 'Backends') {
    Step 'Installing Stable Fast 3D and TripoSR'
    Ensure-Repo 'https://github.com/Stability-AI/stable-fast-3d.git' $Sf3dRoot $Sf3dRevision
    Ensure-Repo 'https://github.com/VAST-AI-Research/TripoSR.git' $TripoRoot $TripoRevision
    Install-Backend 'Stable Fast 3D' $Sf3dRoot $Sf3dPython
    Install-Backend 'TripoSR' $TripoRoot $TripoPython
    if (-not $SkipLargeModels -and $env:HF_TOKEN) {
        & $Sf3dPython -c "from huggingface_hub import snapshot_download; snapshot_download('stabilityai/stable-fast-3d', token=True)"
    } elseif (-not $SkipLargeModels) {
        Write-Warning 'HF_TOKEN is not set. SF3D code is installed, but gated weights require accepting its Hugging Face license and rerunning with HF_TOKEN.'
    }
}

if (Includes 'Hunyuan') {
    Step 'Installing Hunyuan3D 2.1 shape runtime'
    Ensure-Repo 'https://github.com/Tencent-Hunyuan/Hunyuan3D-2.1.git' $HunyuanSource $HunyuanRevision
    if (-not (Test-Path $HunyuanPython)) { uv venv $HunyuanVenv --python 3.10 }
    $env:UV_HTTP_TIMEOUT = '600'
    uv pip install --python $HunyuanPython --index-url https://download.pytorch.org/whl/cu121 'torch==2.5.1+cu121' 'torchvision==0.20.1+cu121'
    uv pip install --python $HunyuanPython -r (Join-Path $PSScriptRoot 'requirements-hunyuan-shape.txt')
    if (-not $SkipLargeModels) {
        New-Item -ItemType Directory -Force -Path $HunyuanModel | Out-Null
        $download = "from huggingface_hub import snapshot_download; snapshot_download(repo_id='tencent/Hunyuan3D-2.1', local_dir=r'$HunyuanModel', allow_patterns=['hunyuan3d-dit-v2-1/*','hunyuan3d-vae-v2-1/*'])"
        & $HunyuanPython -c $download
        Assert-LastExit 'Downloading Hunyuan3D weights'
    }
    & $HunyuanPython -c "import sys,torch; sys.path.insert(0,r'$HunyuanSource\hy3dshape'); from hy3dshape.pipelines import Hunyuan3DDiTFlowMatchingPipeline; assert torch.cuda.is_available(); print('Hunyuan CUDA:',torch.__version__,torch.cuda.get_device_name(0))"
    Assert-LastExit 'Hunyuan import verification'
}

if (Includes 'ComfyUI') {
    Step 'Installing ComfyUI and SD 1.5 Inpainting'
    $comfyArgs = @('-NoProfile','-ExecutionPolicy','Bypass','-File',(Join-Path $PSScriptRoot 'install_local_image_edit.ps1'))
    if ($SkipLargeModels) { $comfyArgs += '-SkipModelDownload' }
    if ($SkipSmokeTests) { $comfyArgs += '-SkipSmokeTest' }
    $process = Start-Process powershell.exe -ArgumentList $comfyArgs -Wait -PassThru -NoNewWindow
    if ($process.ExitCode -ne 0) { throw "ComfyUI installer failed: $($process.ExitCode)" }
}

if (-not $SkipSmokeTests) {
    Step 'Running final capability checks'
    & (Join-Path $Root '.venv\Scripts\python.exe') (Join-Path $Root 'scripts\check_environment.py')
    & (Get-Command npm.cmd).Source run build --prefix $Root
    Assert-LastExit 'Application build'
}

Write-Host "`nFull local 2D-to-3D stack installation completed." -ForegroundColor Green
Write-Host "Start: powershell -ExecutionPolicy Bypass -File `"$PSScriptRoot\start.ps1`""
