$ErrorActionPreference = 'Stop'
$externalRoot = if ($env:STUDIO_EXTERNAL_ROOT) { $env:STUDIO_EXTERNAL_ROOT } else { Join-Path $HOME 'AIData\3d' }
$video = Join-Path $externalRoot 'local\ComfyUI\output\video\two-cats-wan22-smoke_00001_.mp4'
$frameDir = 'C:\Users\vip\Documents\3d\diagnostics\two-cats-wan22-smoke-frames'
New-Item -ItemType Directory -Force -Path $frameDir | Out-Null
& ffmpeg -hide_banner -loglevel error -y -i $video -vf "select='eq(n,0)+eq(n,4)+eq(n,8)+eq(n,12)+eq(n,16)+eq(n,20)+eq(n,24)+eq(n,28)+eq(n,32)',scale=768:-1,tile=3x3" -frames:v 1 (Join-Path $frameDir 'contact-sheet.png')
Get-Item (Join-Path $frameDir 'contact-sheet.png') | Select-Object FullName,Length
