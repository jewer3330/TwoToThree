param([ValidateSet('auto','sf3d','triposr')][string]$Backend = 'auto')
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot; $config = Get-Content (Join-Path $PSScriptRoot 'config.json') -Raw | ConvertFrom-Json
$externalRoot = if ($env:STUDIO_EXTERNAL_ROOT) { $env:STUDIO_EXTERNAL_ROOT } else { Join-Path $HOME 'AIData\3d' }; $local = Join-Path $externalRoot 'local'
$inputPath = Join-Path $root $config.input; $staging = Join-Path $local 'output'; $final = Join-Path $root $config.output
New-Item -ItemType Directory -Force -Path $staging,(Split-Path -Parent $final) | Out-Null
function Run-SF3D {
  $repo = Join-Path $local 'stable-fast-3d'; $python = Join-Path $repo '.venv-runtime\Scripts\python.exe'; if (!(Test-Path $python)) { throw 'SF3D environment missing. Run npm run model:install.' }
  Push-Location $repo; try { & $python run.py $inputPath --output-dir $staging --texture-resolution $config.textureResolution --remesh_option none --target_vertex_count $config.targetVertexCount; if ($LASTEXITCODE -ne 0) { throw 'SF3D inference failed.' } } finally { Pop-Location }
  $mesh = Get-ChildItem $staging -Recurse -Filter mesh.glb | Sort-Object LastWriteTime -Descending | Select-Object -First 1; if (!$mesh) { throw 'SF3D produced no mesh.glb.' }; Copy-Item -LiteralPath $mesh.FullName -Destination $final -Force
}
function Run-TripoSR {
  $repo = Join-Path $local 'TripoSR'; $python = Join-Path $repo '.venv-runtime\Scripts\python.exe'; if (!(Test-Path $python)) { throw 'TripoSR environment missing. Run npm run model:install.' }
  Push-Location $repo; try { & $python run.py $inputPath --output-dir $staging --model-save-format glb; if ($LASTEXITCODE -ne 0) { throw 'TripoSR inference failed.' } } finally { Pop-Location }
  $mesh = Get-ChildItem $staging -Recurse -Filter '*.glb' | Sort-Object LastWriteTime -Descending | Select-Object -First 1; if (!$mesh) { throw 'TripoSR produced no GLB.' }; Copy-Item -LiteralPath $mesh.FullName -Destination $final -Force
}
if ($Backend -eq 'sf3d') { Run-SF3D } elseif ($Backend -eq 'triposr') { Run-TripoSR } else { try { Run-SF3D } catch { Write-Warning "SF3D failed: $($_.Exception.Message) Falling back to TripoSR."; Run-TripoSR } }
Write-Host "GLB ready: $final" -ForegroundColor Green
