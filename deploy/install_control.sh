#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

echo "[1/4] 创建 Python 虚拟环境"
python3 -m venv .venv
.venv/bin/pip install --upgrade pip

echo "[2/4] 安装 Python 依赖"
.venv/bin/pip install -r requirements.txt

echo "[3/4] 构建前端"
if command -v npm >/dev/null 2>&1; then
  npm install
  npm run build
else
  echo "未检测到 npm，跳过前端构建（可另处构建后拷贝 dist/，或由 nginx 托管）"
fi

echo "[4/4] 完成。请编辑 deploy/control.env 后启动："
echo "  sudo cp deploy/control.service /etc/systemd/system/"
echo "  .venv/bin/python -m uvicorn server.main:app --host 0.0.0.0 --port 8000"
