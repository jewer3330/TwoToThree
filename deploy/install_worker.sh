#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

echo "[1/3] 创建 Python 虚拟环境"
python3 -m venv .venv
.venv/bin/pip install --upgrade pip

echo "[2/3] 安装 Python 依赖"
.venv/bin/pip install -r requirements.txt

echo "[3/3] 完成。请编辑 deploy/worker.env（HUNYUAN_*/BLENDER 路径）后启动："
echo "  sudo cp deploy/worker.service /etc/systemd/system/"
echo "  .venv/bin/python -m server.remote_worker"
