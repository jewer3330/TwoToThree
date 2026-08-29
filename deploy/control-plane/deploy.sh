#!/usr/bin/env bash
# ============================================================
# 主控（Mac mini / Linux）一键部署：构建 Docker 镜像并启动容器
# 用法：./deploy.sh [--host 100.69.5.47] [--user d0993] [--ext D:\\print3d] [--rebuild]
# ============================================================
set -euo pipefail
cd "$(dirname "$0")/../.."  # 仓库根

REMOTE_HOST="${REMOTE_HOST:-100.69.5.47}"
REMOTE_USER="${REMOTE_USER:-d0993}"
REMOTE_EXT="${REMOTE_EXT:-D:\\\\print3d}"
REBUILD="${REBUILD:-0}"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --host) REMOTE_HOST="$2"; shift 2;;
    --user) REMOTE_USER="$2"; shift 2;;
    --ext)  REMOTE_EXT="$2"; shift 2;;
    --rebuild) REBUILD=1; shift;;
    *) echo "unknown arg: $1"; exit 1;;
  esac
done

echo "==> 构建前端 dist"
export PATH="/Applications/Docker.app/Contents/Resources/bin:$PATH" 2>/dev/null || true
npm run build

SERVERS_DIR="${SERVERS_DIR:-/Volumes/ssd/servers}"
STACK="${SERVERS_DIR}/print3d_server"
echo "==> 部署目录: ${STACK} (REMOTE_HOST=${REMOTE_HOST} user=${REMOTE_USER} ext=${REMOTE_EXT})"

if [[ ! -d "${STACK}" ]]; then
  mkdir -p "${STACK}/data" "${STACK}/keys"
  cp ~/.ssh/id_ed25519_ai_video "${STACK}/keys/" 2>/dev/null || true
fi

export PRINT3D_REMOTE_HOST="${REMOTE_HOST}" PRINT3D_REMOTE_USER="${REMOTE_USER}" PRINT3D_REMOTE_EXT="${REMOTE_EXT}"
if [[ "${REBUILD}" == "1" ]]; then
  (cd "${STACK}" && DOCKER_BUILDKIT=0 docker compose build)
fi
(cd "${STACK}" && docker compose up -d)
echo "==> 等待启动..."
sleep 6
curl -sf http://127.0.0.1:8000/api/system/health | python3 -m json.tool || echo "health 未就绪，查看 docker logs"
echo "==> 完成。控制台: http://127.0.0.1:8000/gpu"
