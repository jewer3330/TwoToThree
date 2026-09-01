#!/usr/bin/env bash
# ============================================================
# 注册 GPU 节点到主控（无需改代码，只加一条配置）
#
# Windows 节点（密钥 SSH）：
#   ./register-gpu.sh GPU-2 100.69.5.47 d0993 /run/secrets/gpu_key D:\\print3d
#
# Linux 节点（AutoDL 等，密码 + 端口 SSH）：
#   ./register-gpu.sh AutoDL-4090 connect.westb.seetacloud.com root "" /root/autodl-tmp/print3d \
#       --os linux --port 13142 --password 'yP31+P+y6hon'
# ============================================================
set -euo pipefail
API="${API:-http://127.0.0.1:8000}"
NAME="${1:?name required}"; HOST="${2:?ip required}"; USER="${3:?ssh user required}"; KEY="${4:-}"
EXT="${5:-D:\\\\print3d}"
OS="windows"; PORT="22"; PASSWORD=""

# 解析可选参数（--os/--port/--password）
REST=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --os) OS="${2:?os value required}"; shift 2;;
    --port) PORT="${2:?port required}"; shift 2;;
    --password) PASSWORD="${2:-}"; shift 2;;
    *) REST+=("$1"); shift;;
  esac
done
set -- "${REST[@]}"
NAME="${1:?name required}"; HOST="${2:?ip required}"; USER="${3:?ssh user required}"; KEY="${4:-}"; EXT="${5:-D:\\\\print3d}"

# 组装 JSON（password 含特殊字符，用 python 保证转义正确）并注册
BODY=$(python3 - "$NAME" "$HOST" "$USER" "$KEY" "$EXT" "$OS" "$PORT" "$PASSWORD" <<'PY'
import json, sys
name, host, user, key, ext, os_, port, password = sys.argv[1:]
sep = "\\" if os_ != "linux" else "/"
root = ext.rstrip("\\/") + sep + "TwoToThree"
work = ext.rstrip("\\/") + sep + "work"
print(json.dumps({
    "name": name, "host": host, "user": user, "key": key,
    "root": root, "ext": ext.rstrip("\\/"), "work": work,
    "os": os_, "port": int(port), "password": password,
    "labels": ["gpu"], "maxConcurrentJobs": 1, "enabled": True,
}))
PY
)

curl -sf -X POST "${API}/api/gpu/hosts" -H 'Content-Type: application/json' -d "${BODY}" | python3 -m json.tool
echo "==> 已注册 ${NAME}（os=${OS} port=${PORT}）；稍候在控制台 ${API}/gpu 查看探测状态"
