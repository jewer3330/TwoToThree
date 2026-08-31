param([ValidateSet('all','sf3d','triposr')][string]$Backend = 'all')
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot; $externalRoot = if ($env:STUDIO_EXTERNAL_ROOT) { $env:STUDIO_EXTERNAL_ROOT } else { Join-Path $HOME 'AIData\3d' }; $local = Join-Path $externalRoot 'local'
function Install-Backend([string]$name,[string]$folder) {
  $repo = Join-Path $local $folder; if (!(Test-Path (Join-Path $repo 'requirements.txt'))) { throw "$name source missing. Run npm run model:setup." }
  $venv = Join-Path $repo '.venv-runtime'; $basePython = uv python find 3.10; if ($LASTEXITCODE -ne 0) { throw 'Python 3.10 is unavailable.' }; & $basePython -m venv $venv; if ($LASTEXITCODE -ne 0) { throw "$name venv creation failed." }; $python = Join-Path $venv 'Scripts\python.exe'
  uv pip install --python $python wheel 'setuptools==69.5.1' scikit-build-core cmake ninja pybind11; if ($LASTEXITCODE -ne 0) { throw "$name bootstrap failed." }
  uv pip install --python $python torch torchvision --index-url https://download.pytorch.org/whl/cu121; if ($LASTEXITCODE -ne 0) { throw "$name PyTorch install failed." }
  Push-Location $repo
  try {
    uv pip install --python $python --no-build-isolation -r 'requirements.txt'
    if ($LASTEXITCODE -ne 0) { throw "$name requirements install failed." }
  } finally { Pop-Location }
  Write-Host "$name installed: $venv" -ForegroundColor Green
}
if ($Backend -in @('all','sf3d')) { Install-Backend 'Stable Fast 3D' 'stable-fast-3d' }
if ($Backend -in @('all','triposr')) { Install-Backend 'TripoSR' 'TripoSR' }
