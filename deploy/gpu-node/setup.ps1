param(
  [string]$Root = 'D:\print3d',
  [string]$GitRef = 'agent/blender-auto-refinement-v1',
  [switch]$SkipWeights,
  [switch]$SkipBlender,
  [switch]$SkipRepo
)
# ============================================================
# GPU 节点一键环境安装（Windows）
# 用法（在 GPU 机器的 PowerShell 管理员执行，或从 Mac 经 SSH 执行）：
#   powershell -ExecutionPolicy Bypass -File setup.ps1
#   powershell -ExecutionPolicy Bypass -File setup.ps1 -Root D:\print3d -SkipWeights
# 安装内容（全部落在 <Root>\local\ 下，仓库在 <Root>\TwoToThree）：
#   Python 3.11 / Blender 5.2.1 / 仓库 / Hunyuan3D-2.1 代码 / bootstrap venv(torch cu124) / 权重(可选)
# ============================================================
$ErrorActionPreference = 'Continue'
$log = "$Root\setup.log"
New-Item -ItemType Directory -Force -Path "$Root\local","$Root\data","$Root\output" | Out-Null
function Log($m) { $t = Get-Date -Format 'HH:mm:ss'; $line = "[$t] $m"; Write-Host $line; Add-Content -Path $log -Value $line }
function Check($cond, $msg) { if (-not $cond) { Log "FAIL: $msg"; throw $msg } }

Log '=== GPU node setup start ==='

# 1) Python 3.11
$py = "$env:LOCALAPPDATA\Programs\Python\Python311\python.exe"
if (-not (Test-Path $py)) {
    Log 'installing Python 3.11 via winget...'
    winget install -e --id Python.Python.3.11 --accept-package-agreements --accept-source-agreements --disable-interactivity 2>&1 | Out-String | Add-Content $log
}
if (-not (Test-Path $py)) { $py = 'C:\Python311\python.exe' }
Check (Test-Path $py) "python311 not found"
Log "python: $py $(& $py --version 2>&1)"
$env:Path = (Split-Path $py) + ';' + $env:Path

# 2) Blender 5.2.1 -> <Root>\local\Blender52
if (-not $SkipBlender) {
  $zip = "$Root\blender-5.2.1-windows-x64.zip"
  if (-not (Test-Path "$Root\local\Blender52\blender.exe")) {
      if (-not (Test-Path $zip)) {
          Log 'downloading Blender 5.2.1 (~400MB, aliyun mirror)...'
          curl.exe -L -sS -o $zip https://mirrors.aliyun.com/blender/release/Blender5.2/blender-5.2.1-windows-x64.zip
          Log "blender zip size: $((Get-Item $zip).Length)"
      } else { Log 'blender zip exists, skipping' }
      Log 'extracting Blender...'
      Expand-Archive -Path $zip -DestinationPath "$Root\local" -Force
      if (Test-Path "$Root\local\blender-5.2.1-windows-x64") { Move-Item "$Root\local\blender-5.2.1-windows-x64" "$Root\local\Blender52" -Force }
  }
  Check (Test-Path "$Root\local\Blender52\blender.exe") 'blender.exe missing'
  Log "blender: $(& "$Root\local\Blender52\blender.exe" --version 2>&1 | Select-Object -First 1)"
}

# 3) 仓库（agent 分支；GitHub 被墙时从主控 tar 直传）
if (-not $SkipRepo) {
  if (-not (Test-Path "$Root\TwoToThree\pipeline\run_hunyuan_yoyo.py")) {
      Log 'cloning TwoToThree repo...'
      if (Test-Path "$Root\TwoToThree") { Remove-Item "$Root\TwoToThree" -Recurse -Force }
      git clone --depth 1 --branch $GitRef https://github.com/hanzhicao82-stack/TwoToThree.git "$Root\TwoToThree" 2>&1 | Out-String | Add-Content $log
  }
  Check (Test-Path "$Root\TwoToThree\pipeline\run_hunyuan_yoyo.py") 'repo missing (GitHub 被墙时：从主控 scp tar 包，tar -xzf 到 <Root> 并移动 pipeline/server/studio_paths.py 到 <Root>\TwoToThree)'
  Log "repo HEAD: $(git -C "$Root\TwoToThree" rev-parse --short HEAD 2>&1)"
}

# 4) Hunyuan3D-2.1 代码 -> <Root>\local\Hunyuan3D-2.1-space
if (-not (Test-Path "$Root\local\Hunyuan3D-2.1-space\hy3dshape\hy3dshape\pipelines.py")) {
    Log 'cloning Hunyuan3D-2.1 code...'
    git clone --depth 1 https://github.com/Tencent-Hunyuan/Hunyuan3D-2.1.git "$Root\local\Hunyuan3D-2.1-space" 2>&1 | Out-String | Add-Content $log
}
Check (Test-Path "$Root\local\Hunyuan3D-2.1-space\hy3dshape\hy3dshape\pipelines.py") 'hy3dshape missing'
Log 'hy3dshape ok'

# 5) bootstrap venv -> <Root>\local\hunyuan-bootstrap
$venv = "$Root\local\hunyuan-bootstrap"
if (-not (Test-Path "$venv\Scripts\python.exe")) { & $py -m venv $venv }
$vpy = "$venv\Scripts\python.exe"
Log "venv python: $(& $vpy --version 2>&1)"
$torchOk = & $vpy -c "import torch; print(torch.__version__)" 2>&1
if ($LASTEXITCODE -ne 0) {
    Log 'installing torch (cu124, ~2.5GB)...'
    & $vpy -m pip install --quiet --upgrade pip 2>&1 | Out-String | Add-Content $log
    & $vpy -m pip install torch torchvision --index-url https://download.pytorch.org/whl/cu124 2>&1 | Out-String | Add-Content $log
    $torchOk = & $vpy -c "import torch; print(torch.__version__)" 2>&1
}
Check ($LASTEXITCODE -eq 0) "torch install failed: $torchOk"
Log "torch: $torchOk cuda=$(& $vpy -c 'import torch; print(torch.cuda.is_available())' 2>&1)"
$depsOk = & $vpy -c "import diffusers, transformers, accelerate, rembg, trimesh, pymeshlab, timm, tqdm, yaml, onnxruntime" 2>&1
if ($LASTEXITCODE -ne 0) {
    Log 'installing hunyuan deps...'
    & $vpy -m pip install diffusers==0.30.0 transformers==4.46.0 accelerate==1.1.1 safetensors einops omegaconf huggingface_hub hf-transfer rembg onnxruntime pillow numpy scipy opencv-python imageio scikit-image --extra-index-url https://mirrors.cloud.tencent.com/pypi/simple/ 2>&1 | Out-String | Add-Content $log
    & $vpy -m pip install trimesh pymeshlab tqdm pyyaml timm torchmetrics torchdiffeq sentencepiece --extra-index-url https://mirrors.cloud.tencent.com/pypi/simple/ 2>&1 | Out-String | Add-Content $log
    $depsOk = & $vpy -c "import diffusers, transformers, accelerate, rembg, trimesh, pymeshlab, timm, tqdm, yaml, onnxruntime" 2>&1
}
Check ($LASTEXITCODE -eq 0) "deps install failed: $depsOk"
Log 'venv deps ok'

# 6) 权重 -> <Root>\local\Hunyuan3D-2.1-model（curl 直下，hf-mirror）
$model = "$Root\local\Hunyuan3D-2.1-model"
if (-not $SkipWeights) {
  if (-not (Test-Path "$model\hunyuan3d-dit-v2-1\model.fp16.ckpt")) {
      Log 'downloading Hunyuan3D-2.1 weights via curl (~4.4GB)...'
      New-Item -ItemType Directory -Force -Path "$model\hunyuan3d-dit-v2-1","$model\hunyuan3d-vae-v2-1" | Out-Null
      $base = 'https://hf-mirror.com/tencent/Hunyuan3D-2.1/resolve/main'
      curl.exe -L -sS -o "$model\hunyuan3d-dit-v2-1\config.yaml" "$base/hunyuan3d-dit-v2-1/config.yaml" 2>&1 | Out-String | Add-Content $log
      Log "dit config: $((Get-Item "$model\hunyuan3d-dit-v2-1\config.yaml").Length) bytes"
      Log 'downloading dit ckpt (~4.3GB)...'
      curl.exe -L -C - -sS -o "$model\hunyuan3d-dit-v2-1\model.fp16.ckpt" "$base/hunyuan3d-dit-v2-1/model.fp16.ckpt" 2>&1 | Out-String | Add-Content $log
      Log "dit ckpt size: $((Get-Item "$model\hunyuan3d-dit-v2-1\model.fp16.ckpt").Length)"
      curl.exe -L -sS -o "$model\hunyuan3d-vae-v2-1\config.yaml" "$base/hunyuan3d-vae-v2-1/config.yaml" 2>&1 | Out-String | Add-Content $log
      curl.exe -L -C - -sS -o "$model\hunyuan3d-vae-v2-1\model.fp16.ckpt" "$base/hunyuan3d-vae-v2-1/model.fp16.ckpt" 2>&1 | Out-String | Add-Content $log
      Log "vae ckpt size: $((Get-Item "$model\hunyuan3d-vae-v2-1\model.fp16.ckpt").Length)"
  } else { Log 'weights exist, skipping' }
  Check (Test-Path "$model\hunyuan3d-dit-v2-1\model.fp16.ckpt") 'weights missing'
}

Log '=== GPU node setup done ==='
