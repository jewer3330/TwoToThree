param(
    [switch]$SkipModelDownload,
    [switch]$SkipSmokeTest,
    [switch]$SkipDependencyInstall
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$ExternalRoot = if ($env:STUDIO_EXTERNAL_ROOT) { $env:STUDIO_EXTERNAL_ROOT } else { Join-Path $HOME 'AIData\3d' }
$LocalRoot = Join-Path $ExternalRoot 'local'
$ComfyRoot = Join-Path $LocalRoot 'ComfyUI'
$GpuPython = Join-Path $ComfyRoot '.venv-gpu\Scripts\python.exe'
$ComfyRevision = 'b323a345bbbfb2f3a95b5b73b68eb7919a26515e'
$CheckpointName = 'sd-v1-5-inpainting.ckpt'
$CheckpointSize = 4265437280
$CheckpointSha256 = 'C6BBC15E3224E6973459BA78DE4998B80B50112B0AE5B5C67113D56B4E366B19'
$CheckpointPath = Join-Path $ComfyRoot "models\checkpoints\$CheckpointName"
$Launcher = Join-Path $ProjectRoot 'scripts\run_comfy_gpu.py'

function Write-Step([string]$Message) {
    Write-Host "`n==> $Message" -ForegroundColor Cyan
}

function Test-CudaPython([string]$PythonPath) {
    if (-not (Test-Path -LiteralPath $PythonPath)) { return $false }
    & $PythonPath -c "import torch,sys; sys.exit(0 if torch.cuda.is_available() else 1)" 2>$null
    return $LASTEXITCODE -eq 0
}

function Stop-ComfySmoke {
    $listeners = Get-NetTCPConnection -LocalPort 8188 -State Listen -ErrorAction SilentlyContinue
    foreach ($listener in $listeners) {
        Stop-Process -Id $listener.OwningProcess -ErrorAction SilentlyContinue
    }
}

Write-Step 'Checking prerequisites'
foreach ($command in @('git', 'python')) {
    if (-not (Get-Command $command -ErrorAction SilentlyContinue)) {
        throw "Missing required command: $command"
    }
}
if (-not (Test-Path -LiteralPath $Launcher)) {
    throw "Missing ComfyUI launcher: $Launcher"
}
New-Item -ItemType Directory -Force -Path $LocalRoot | Out-Null

Write-Step 'Installing pinned ComfyUI revision'
if (-not (Test-Path -LiteralPath (Join-Path $ComfyRoot '.git'))) {
    git clone https://github.com/Comfy-Org/ComfyUI.git $ComfyRoot
}
$currentRevision = (git -C $ComfyRoot rev-parse HEAD).Trim()
if ($currentRevision -ne $ComfyRevision) {
    $dirty = git -C $ComfyRoot status --porcelain
    if ($dirty) {
        throw "Uncommitted changes found in $ComfyRoot; refusing to switch revisions."
    }
    git -C $ComfyRoot fetch origin $ComfyRevision
    git -C $ComfyRoot checkout --detach $ComfyRevision
}

Write-Step 'Preparing uv and isolated Python 3.10 environment'
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    python -m pip install --user uv
    $userScripts = python -c "import site,os; print(os.path.join(site.USER_BASE,'Scripts'))"
    $env:Path = "$userScripts;$env:Path"
}
if (-not (Test-Path -LiteralPath $GpuPython)) {
    uv venv (Join-Path $ComfyRoot '.venv-gpu') --python 3.10
}

Write-Step 'Selecting or installing CUDA PyTorch 2.5.1 runtime'
$cudaCandidates = @(
    (Join-Path $LocalRoot 'stable-fast-3d\.venv-runtime\Scripts\python.exe'),
    (Join-Path $LocalRoot 'hunyuan-bootstrap\Scripts\python.exe')
)
$sharedCudaPython = $null
foreach ($candidate in $cudaCandidates) {
    if (Test-CudaPython $candidate) { $sharedCudaPython = $candidate; break }
}

if ($sharedCudaPython) {
    $sharedCudaSite = (& $sharedCudaPython -c "import site; print(next(p for p in site.getsitepackages() if p.lower().endswith('site-packages'))) ").Trim()
    $pthPath = Join-Path $ComfyRoot '.venv-gpu\Lib\site-packages\shared_cuda_torch.pth'
    Set-Content -LiteralPath $pthPath -Value $sharedCudaSite -Encoding ASCII
    Write-Host "Reusing verified CUDA runtime: $sharedCudaSite"
} else {
    $env:UV_HTTP_TIMEOUT = '600'
    uv pip install --python $GpuPython --index-url https://download.pytorch.org/whl/cu121 `
        'torch==2.5.1+cu121' 'torchvision==0.20.1+cu121' 'torchaudio==2.5.1+cu121'
}

if (-not $SkipDependencyInstall) {
    Write-Step 'Installing ComfyUI dependencies without replacing CUDA PyTorch'
    $tempRequirements = Join-Path ([System.IO.Path]::GetTempPath()) "comfy-requirements-$PID.txt"
    Get-Content -LiteralPath (Join-Path $ComfyRoot 'requirements.txt') |
        Where-Object { $_ -notmatch '^\s*(torch|torchvision|torchaudio)(\s|=|<|>|$)' } |
        Set-Content -LiteralPath $tempRequirements -Encoding UTF8
    try {
        $env:UV_HTTP_TIMEOUT = '600'
        uv pip install --python $GpuPython -r $tempRequirements
        uv pip install --python $GpuPython --index-url https://download.pytorch.org/whl/cu121 --no-deps 'torchaudio==2.5.1+cu121'
        uv pip install --python $GpuPython 'huggingface-hub==1.27.0'
    } finally {
        Remove-Item -LiteralPath $tempRequirements -ErrorAction SilentlyContinue
    }
}

# uv cannot account for packages exposed through a .pth file while resolving.
# Remove only duplicate Torch/TorchVision payloads from this venv so imports fall
# through to the verified shared CUDA runtime. Keep local torchaudio installed.
if ($sharedCudaPython) {
    $localSite = Join-Path $ComfyRoot '.venv-gpu\Lib\site-packages'
    Get-ChildItem -LiteralPath $localSite -Force |
        Where-Object { $_.Name -eq 'torch' -or $_.Name -eq 'torchvision' -or $_.Name -like 'torch-*.dist-info' -or $_.Name -like 'torchvision-*.dist-info' } |
        ForEach-Object {
            if ($_.PSIsContainer) {
                [System.IO.Directory]::Delete("\\?\$($_.FullName)", $true)
            } else {
                [System.IO.File]::Delete("\\?\$($_.FullName)")
            }
        }
}

Write-Step 'Applying comfy-kitchen compatibility patch for Torch 2.5.1'
$kitchenFile = Join-Path $ComfyRoot '.venv-gpu\Lib\site-packages\comfy_kitchen\backends\eager\na.py'
if (-not (Test-Path -LiteralPath $kitchenFile)) { throw "Missing comfy-kitchen file: $kitchenFile" }
$kitchen = Get-Content -LiteralPath $kitchenFile -Raw
if ($kitchen -notmatch 'from typing import List, Optional') {
    $kitchen = $kitchen -replace "import torch\r?\n", "import torch`r`nfrom typing import List, Optional`r`n"
}
$kitchen = $kitchen.Replace('kernel_size: list[int]', 'kernel_size: List[int]')
$kitchen = $kitchen.Replace('is_causal: list[bool]', 'is_causal: List[bool]')
$kitchen = $kitchen.Replace('scale: float | None', 'scale: Optional[float]')
Set-Content -LiteralPath $kitchenFile -Value $kitchen -Encoding UTF8

Write-Step 'Verifying CUDA Python environment'
& $GpuPython -c "import torch,torchvision,torchaudio; assert torch.__version__=='2.5.1+cu121'; assert torch.cuda.is_available(); print('torch',torch.__version__,'torchvision',torchvision.__version__,'torchaudio',torchaudio.__version__,'gpu',torch.cuda.get_device_name(0))"

if (-not $SkipModelDownload) {
    $validCheckpoint = $false
    if (Test-Path -LiteralPath $CheckpointPath) {
        $item = Get-Item -LiteralPath $CheckpointPath
        if ($item.Length -eq $CheckpointSize) {
            $hash = (Get-FileHash -LiteralPath $CheckpointPath -Algorithm SHA256).Hash
            $validCheckpoint = $hash -eq $CheckpointSha256
        }
    }
    if (-not $validCheckpoint) {
        Write-Step 'Downloading and verifying SD 1.5 Inpainting checkpoint (3.97 GiB)'
        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $CheckpointPath) | Out-Null
        $modelDir = Split-Path -Parent $CheckpointPath
        & $GpuPython -c "from huggingface_hub import hf_hub_download; hf_hub_download(repo_id='stable-diffusion-v1-5/stable-diffusion-inpainting', filename='$CheckpointName', local_dir=r'$modelDir')"
        $item = Get-Item -LiteralPath $CheckpointPath
        if ($item.Length -ne $CheckpointSize) { throw "Incorrect checkpoint size: $($item.Length)" }
        $hash = (Get-FileHash -LiteralPath $CheckpointPath -Algorithm SHA256).Hash
        if ($hash -ne $CheckpointSha256) { throw "Incorrect checkpoint SHA-256: $hash" }
    } else {
        Write-Host 'Existing checkpoint size and SHA-256 are valid; skipping download.'
    }
}

if (-not $SkipSmokeTest) {
    Write-Step 'Running ComfyUI CUDA, API, and checkpoint smoke test'
    Stop-ComfySmoke
    $stdout = Join-Path $ComfyRoot 'install-smoke.log'
    $stderr = Join-Path $ComfyRoot 'install-smoke.err.log'
    $process = Start-Process -FilePath $GpuPython `
        -ArgumentList @($Launcher, '--listen', '127.0.0.1', '--port', '8188', '--lowvram') `
        -WorkingDirectory $ComfyRoot -WindowStyle Hidden `
        -RedirectStandardOutput $stdout -RedirectStandardError $stderr -PassThru
    try {
        $deadline = (Get-Date).AddSeconds(120)
        $stats = $null
        do {
            Start-Sleep -Seconds 2
            try { $stats = Invoke-RestMethod -Uri 'http://127.0.0.1:8188/system_stats' -TimeoutSec 2 } catch { $stats = $null }
        } until ($stats -or $process.HasExited -or (Get-Date) -gt $deadline)
        if (-not $stats) {
            $tail = Get-Content -LiteralPath $stderr -Tail 80 -ErrorAction SilentlyContinue
            throw "ComfyUI API failed to start:`n$tail"
        }
        $loader = Invoke-RestMethod -Uri 'http://127.0.0.1:8188/object_info/CheckpointLoaderSimple' -TimeoutSec 10
        $checkpoints = @($loader.CheckpointLoaderSimple.input.required.ckpt_name[0])
        if (-not $SkipModelDownload -and $CheckpointName -notin $checkpoints) {
            throw "ComfyUI did not enumerate checkpoint: $CheckpointName"
        }
        Write-Host "API 200; device: $($stats.devices[0].name); checkpoint: $($checkpoints -join ', ')" -ForegroundColor Green
    } finally {
        if (-not $process.HasExited) { Stop-Process -Id $process.Id -ErrorAction SilentlyContinue }
        Stop-ComfySmoke
    }
}

Write-Host ''
Write-Host 'Local AI image-edit environment installation completed.' -ForegroundColor Green
$startCommand = '& "{0}" "{1}" --listen 127.0.0.1 --port 8188 --lowvram' -f $GpuPython, $Launcher
Write-Host "Start command: $startCommand"
