@echo off
setlocal
cd /d C:\Users\vip\Documents\3d
curl.exe -L --retry 20 --retry-all-errors --output .local\Hunyuan3D-2.1-model\hunyuan3d-vae-v2-1\model.fp16.ckpt "https://hf-mirror.com/tencent/Hunyuan3D-2.1/resolve/main/hunyuan3d-vae-v2-1/model.fp16.ckpt?download=true"
if errorlevel 1 exit /b %errorlevel%
curl.exe -L --retry 20 --retry-all-errors --output .local\Hunyuan3D-2.1-model\hunyuan3d-dit-v2-1\model.fp16.ckpt "https://hf-mirror.com/tencent/Hunyuan3D-2.1/resolve/main/hunyuan3d-dit-v2-1/model.fp16.ckpt?download=true"
exit /b %errorlevel%
