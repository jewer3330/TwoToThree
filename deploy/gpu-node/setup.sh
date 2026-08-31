#!/usr/bin/env bash
# ============================================================
# GPU 节点一键环境安装（Linux，AutoDL / 自建 Linux GPU 机）
# 用法（在 GPU 机器的 root shell 执行，或从主控经 SSH 执行）：
#   bash setup.sh
#   bash setup.sh -Root /root/autodl-tmp/print3d -SkipWeights
#   bash setup.sh -Root /root/autodl-tmp/print3d -CUDA cu121 -SkipBlender -SkipRepo
#
# 安装内容（全部落在 <Root>/local/ 下，仓库在 <Root>/TwoToThree）：
#   Python3 venv / Blender / 仓库 / Hunyuan3D-2.1 代码 / bootstrap venv(torch cu*) / 权重(可选)
# 布局与 Windows setup.ps1 保持一致，仅路径分隔符与二进制名不同（bin/python、blender）。
# ============================================================
set -uo pipefail
ROOT="/root/autodl-tmp/print3d"
CUDA="cu121"          # AutoDL Linux 常见 CUDA 12.1；H20/5090 等可换 cu124/cu126
GITREF="main"
SKIP_WEIGHTS=0; SKIP_BLENDER=0; SKIP_REPO=0; SKIP_MV=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    -Root|--Root) ROOT="$2"; shift 2;;
    -CUDA|--CUDA) CUDA="$2"; shift 2;;
    -GitRef|--GitRef) GITREF="$2"; shift 2;;
    -SkipWeights|--SkipWeights) SKIP_WEIGHTS=1; shift;;
    -SkipBlender|--SkipBlender) SKIP_BLENDER=1; shift;;
    -SkipRepo|--SkipRepo) SKIP_REPO=1; shift;;
    -SkipMV|--SkipMV) SKIP_MV=1; shift;;
    *) echo "unknown: $1"; shift;;
  esac
done

LOG="$ROOT/setup.log"
mkdir -p "$ROOT/local" "$ROOT/data" "$ROOT/output" "$ROOT/work"
log(){ echo "[$(date +%H:%M:%S)] $*" | tee -a "$LOG"; }
fail(){ log "FAIL: $*"; exit 1; }

log "=== Linux GPU node setup start (ROOT=$ROOT CUDA=$CUDA) ==="

# 0) 基础依赖
if command -v apt-get >/dev/null 2>&1; then
  apt-get update -y >>"$LOG" 2>&1 || true
  apt-get install -y --no-install-recommends python3 python3-venv python3-pip git curl tar bzip2 xz-utils >>"$LOG" 2>&1 || true
fi

# 1) venv -> <Root>/local/hunyuan-bootstrap
VENV="$ROOT/local/hunyuan-bootstrap"
VPY="$VENV/bin/python"
if [[ ! -x "$VPY" ]]; then
  log "creating venv $VENV ..."
  python3 -m venv "$VENV" >>"$LOG" 2>&1 || fail "venv create failed"
fi
log "venv python: $($VPY --version 2>&1)"

# 2) torch + 依赖
if ! $VPY -c "import torch" >>"$LOG" 2>&1; then
  log "installing torch ($CUDA, ~2.5GB)..."
  $VPY -m pip install --upgrade pip >>"$LOG" 2>&1
  $VPY -m pip install torch torchvision --index-url "https://download.pytorch.org/whl/$CUDA" >>"$LOG" 2>&1 || fail "torch install failed"
fi
log "torch: $($VPY -c 'import torch;print(torch.__version__)' 2>&1) cuda=$($VPY -c 'import torch;print(torch.cuda.is_available())' 2>&1)"
if ! $VPY -c "import diffusers, transformers, accelerate, rembg, trimesh, pymeshlab, timm, tqdm, yaml, onnxruntime" >>"$LOG" 2>&1; then
  log "installing hunyuan deps..."
  $VPY -m pip install diffusers==0.30.0 transformers==4.46.0 accelerate==1.1.1 safetensors einops omegaconf huggingface_hub hf-transfer rembg onnxruntime pillow numpy scipy opencv-python imageio scikit-image --extra-index-url https://mirrors.cloud.tencent.com/pypi/simple/ >>"$LOG" 2>&1
  $VPY -m pip install trimesh pymeshlab tqdm pyyaml timm torchmetrics torchdiffeq sentencepiece --extra-index-url https://mirrors.cloud.tencent.com/pypi/simple/ >>"$LOG" 2>&1
  $VPY -c "import diffusers, transformers, accelerate, rembg, trimesh, pymeshlab, timm, tqdm, yaml, onnxruntime" >>"$LOG" 2>&1 || fail "deps install failed"
fi
log "venv deps ok"

# 3) Blender -> <Root>/local/blender（Linux tar.xz，阿里云镜像；版本对齐 Windows 5.2.1）
if [[ "$SKIP_BLENDER" == "0" ]]; then
  if [[ ! -x "$ROOT/local/blender/blender" ]]; then
    log "downloading Blender 5.2.1 (~400MB, aliyun mirror)..."
    BZ="$ROOT/blender-5.2.1-linux-x64.tar.xz"
    if [[ ! -f "$BZ" ]]; then
      curl -L -sS -o "$BZ" https://mirrors.aliyun.com/blender/release/Blender5.2/blender-5.2.1-linux-x64.tar.xz || fail "blender download failed"
    fi
    log "extracting Blender..."
    tar -xJf "$BZ" -C "$ROOT/local" || fail "blender extract failed"
    if [[ -d "$ROOT/local/blender-5.2.1-linux-x64" ]]; then mv "$ROOT/local/blender-5.2.1-linux-x64" "$ROOT/local/blender"; fi
  fi
  [[ -x "$ROOT/local/blender/blender" ]] || fail "blender binary missing"
  log "blender: $("$ROOT/local/blender/blender" --version 2>&1 | head -1)"
fi

# 4) 仓库 -> <Root>/TwoToThree
if [[ "$SKIP_REPO" == "0" ]]; then
  if [[ ! -f "$ROOT/TwoToThree/pipeline/run_hunyuan_yoyo.py" ]]; then
    log "cloning TwoToThree repo..."
    rm -rf "$ROOT/TwoToThree"
    git clone --depth 1 --branch "$GITREF" https://github.com/hanzhicao82-stack/TwoToThree.git "$ROOT/TwoToThree" >>"$LOG" 2>&1 || log "github clone failed（GitHub 被墙时从主控 tar 直传，见 deploy/README.md）"
  fi
  [[ -f "$ROOT/TwoToThree/pipeline/run_hunyuan_yoyo.py" ]] || fail "repo missing"
  log "repo HEAD: $(git -C "$ROOT/TwoToThree" rev-parse --short HEAD 2>&1)"
fi

# 5) Hunyuan3D-2.1 代码 -> <Root>/local/Hunyuan3D-2.1-space
if [[ ! -f "$ROOT/local/Hunyuan3D-2.1-space/hy3dshape/hy3dshape/pipelines.py" ]]; then
  log "cloning Hunyuan3D-2.1 code..."
  git clone --depth 1 https://github.com/Tencent-Hunyuan/Hunyuan3D-2.1.git "$ROOT/local/Hunyuan3D-2.1-space" >>"$LOG" 2>&1 || fail "hy3dshape clone failed"
fi
log "hy3dshape ok"

# 6) Hunyuan3D-2.1 权重 -> <Root>/local/Hunyuan3D-2.1-model（hf-mirror，curl 直下）
MODEL="$ROOT/local/Hunyuan3D-2.1-model"
if [[ "$SKIP_WEIGHTS" == "0" ]]; then
  if [[ ! -f "$MODEL/hunyuan3d-dit-v2-1/model.fp16.ckpt" ]]; then
    log "downloading Hunyuan3D-2.1 weights (~4.4GB)..."
    mkdir -p "$MODEL/hunyuan3d-dit-v2-1" "$MODEL/hunyuan3d-vae-v2-1"
    BASE='https://hf-mirror.com/tencent/Hunyuan3D-2.1/resolve/main'
    curl -L -sS -o "$MODEL/hunyuan3d-dit-v2-1/config.yaml" "$BASE/hunyuan3d-dit-v2-1/config.yaml"
    log "downloading dit ckpt (~4.3GB)..."
    curl -L -C - -sS -o "$MODEL/hunyuan3d-dit-v2-1/model.fp16.ckpt" "$BASE/hunyuan3d-dit-v2-1/model.fp16.ckpt"
    curl -L -sS -o "$MODEL/hunyuan3d-vae-v2-1/config.yaml" "$BASE/hunyuan3d-vae-v2-1/config.yaml"
    curl -L -C - -sS -o "$MODEL/hunyuan3d-vae-v2-1/model.fp16.ckpt" "$BASE/hunyuan3d-vae-v2-1/model.fp16.ckpt"
  fi
  [[ -f "$MODEL/hunyuan3d-dit-v2-1/model.fp16.ckpt" ]] || fail "weights missing"
fi

# 7) Hunyuan3D-2mv 代码 + 权重（多视图）-> <Root>/local/Hunyuan3D-2mv-runtime / -2mv-model-v2
if [[ "$SKIP_MV" == "0" ]]; then
  if [[ ! -f "$ROOT/local/Hunyuan3D-2mv-runtime/hy3dgen/shapegen/__init__.py" ]]; then
    log "cloning Hunyuan3D-2mv code..."
    git clone --depth 1 https://github.com/Tencent-Hunyuan/Hunyuan3D-2mv.git "$ROOT/local/Hunyuan3D-2mv-runtime" >>"$LOG" 2>&1 || log "2mv code clone failed"
  fi
  MVW="$ROOT/local/Hunyuan3D-2mv-model-v2/hunyuan3d-dit-v2-mv/model.fp16.safetensors"
  if [[ "$SKIP_WEIGHTS" == "0" && ! -f "$MVW" ]]; then
    log "downloading Hunyuan3D-2mv weights (~4.6GB)..."
    mkdir -p "$ROOT/local/Hunyuan3D-2mv-model-v2/hunyuan3d-dit-v2-mv"
    curl -L -C - -sS -o "$MVW" "https://hf-mirror.com/tencent/Hunyuan3D-2mv/resolve/main/hunyuan3d-dit-v2-mv/model.fp16.safetensors"
  fi
fi

log "=== Linux GPU node setup done ==="
