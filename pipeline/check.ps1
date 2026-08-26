$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$externalRoot = if ($env:STUDIO_EXTERNAL_ROOT) { $env:STUDIO_EXTERNAL_ROOT } else { Join-Path $HOME 'AIData\3d' }; $local = Join-Path $externalRoot 'local'
$config = Get-Content (Join-Path $PSScriptRoot 'config.json') -Raw | ConvertFrom-Json
Write-Host '=== Character-to-GLB preflight ==='
foreach ($key in @('input','frontReference','sideReference','backReference')) {
  $path = Join-Path $root $config.$key
  if (Test-Path -LiteralPath $path) { Write-Host "[ok] $key -> $path" -ForegroundColor Green } else { Write-Host "[missing] $key -> $path" -ForegroundColor Red }
}
$gpu = & nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader 2>$null
if ($LASTEXITCODE -eq 0) { Write-Host "[ok] GPU: $gpu" -ForegroundColor Green } else { Write-Host '[missing] NVIDIA driver / nvidia-smi' -ForegroundColor Red }
$blender = Get-Command blender -ErrorAction SilentlyContinue
if ($blender) { Write-Host "[ok] Blender: $($blender.Source)" -ForegroundColor Green } else { Write-Host '[action] Install Blender 4.x and add it to PATH; then enable a Blender MCP server/add-on.' -ForegroundColor Yellow }
$sf3d = Join-Path $local 'stable-fast-3d\run.py'; $triposr = Join-Path $local 'TripoSR\run.py'
Write-Host "[$(if(Test-Path $sf3d){'ok'}else{'action'})] SF3D source: $sf3d"
Write-Host "[$(if(Test-Path $triposr){'ok'}else{'action'})] TripoSR fallback: $triposr"
$token = if ($env:HF_TOKEN) { $env:HF_TOKEN } else { $env:HUGGING_FACE_HUB_TOKEN }
if ($token) { Write-Host '[ok] Hugging Face token available (hidden).' -ForegroundColor Green } else { Write-Host '[action] Accept the SF3D license and set HF_TOKEN.' -ForegroundColor Yellow }
