$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot; $externalRoot = if ($env:STUDIO_EXTERNAL_ROOT) { $env:STUDIO_EXTERNAL_ROOT } else { Join-Path $HOME 'AIData\3d' }; $local = Join-Path $externalRoot 'local'
New-Item -ItemType Directory -Force -Path $local | Out-Null
function Clone-IfMissing([string]$url,[string]$target) { if (Test-Path -LiteralPath $target) { Write-Host "Already present: $target"; return }; git clone --depth 1 $url $target; if ($LASTEXITCODE -ne 0) { throw "Clone failed: $url" } }
Clone-IfMissing 'https://github.com/Stability-AI/stable-fast-3d.git' (Join-Path $local 'stable-fast-3d')
Clone-IfMissing 'https://github.com/VAST-AI-Research/TripoSR.git' (Join-Path $local 'TripoSR')
Write-Host 'Sources ready. Run npm run model:install.' -ForegroundColor Green
