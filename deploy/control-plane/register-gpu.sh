#!/usr/bin/env bash
# ============================================================
# 注册 GPU 节点到主控（无需改代码，只加一条配置）
# 用法：./register-gpu.sh <name> <ip> <ssh-user> <key-path> [work-root]
# 示例：./register-gpu.sh GPU-2 100.69.5.47 d0993 /run/secrets/gpu_key D:\\print3d
# 注意：Docker 容器内密钥路径是 /run/secrets/gpu_key；本机直跑时用 ~/.ssh/id_ed25519_ai_video
# ============================================================
set -euo pipefail
API="${API:-http://127.0.0.1:8000}"
NAME="${1:?name required}"; HOST="${2:?ip required}"; USER="${3:?ssh user required}"; KEY="${4:?key path required}"
EXT="${5:-D:\\\\print3d}"

curl -sf -X POST "${API}/api/gpu/hosts" -H 'Content-Type: application/json' -d "{
  \"name\":\"${NAME}\",\"host\":\"${HOST}\",\"user\":\"${USER}\",\"key\":\"${KEY}\",
  \"root\":\"${EXT}\\\\TwoToThree\",\"ext\":\"${EXT}\",\"work\":\"${EXT}\\\\work\",
  \"labels\":[\"gpu\"],\"maxConcurrentJobs\":1,\"enabled\":true
}" | python3 -m json.tool
echo "==> 已注册 ${NAME}；稍候在控制台 http://127.0.0.1:8000/gpu 查看探测状态"
