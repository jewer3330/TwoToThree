# GPU 节点自注册（WebSocket 反向连接）

## 1. 动机

原有 GPU 集群是 **SSH「推」模式**：控制面要主动 SSH 进每一台算力机探测健康、scp 回传产物。
这在「自有公网 IP / 同内网」下没问题，但对以下节点失效：

- **AutoDL / 云容器**：CGNAT，`connect.xx:port` 是中继地址而非真实公网 IP，控制面根本「推」不进去（或走 relay 极慢）。
- **家宽肉鸡 / 动态 IP / NAT 后机器**：无固定公网地址、无入站端口。

自注册改为 **节点「反向连出」**：算力机主动 dial-out 到控制面的 WebSocket 长连接，注册自己、
上报能力、维持心跳、接收任务。节点只需出站连接，无需公网 IP、无需开入站端口、控制面无需持有
每台节点的 SSH 凭据（只发 per-node token 给节点）。

## 2. 拓扑

```
控制面（生产 ECS / 开发家宽机，公网可达）
├─ FastAPI WS 端点  /api/gpu/ws
├─ 内存注册表（node_id → {连接, 能力, 心跳}）
├─ 调度器：能力匹配 + 在线 + 并发上限 → 通过 WS 下发任务
└─ /gpu 控制台实时可见自注册节点（provider=selfreg）

GPU 节点（AutoDL / 肉鸡，任意 NAT 后）
└─ server.agent（常驻进程）
   ① 启动即连 wss://控制面/api/gpu/ws，携带 per-node token
   ② hello 上报 {节点名, GPU型号/显存, 能力清单, 并发上限}
   ③ 心跳 10s，断线指数退避自动重连
   ④ 收到 run_job → 本地 worker.run 执行 → 回传 job_result
```

与现有 SSH 推模式**并存**：`provider='ssh'` 走原 `backends.Remote` SSH 路径，`provider='selfreg'`
走 WS 下发路径。新增一台肉鸡只需跑 `server.agent`，无需改控制面注册表。

## 3. 消息协议（JSON 文本帧）

```
agent → control
  {"type":"hello","token":"<WORKER_TOKEN>","node":{"id","name","caps":{...},"gpu","memTotal","memUsed","diskFree","maxConcurrentJobs","labels"}}
  {"type":"ping"}
  {"type":"probe_result","probeId","caps","gpu","memTotal","memUsed","diskFree"}
  {"type":"job_event","jobId","kind":"log|stage|status","payload":{...}}
  {"type":"job_result","jobId","ok":true,"result":{...}}  |  {"ok":false,"error":"..."}

control → agent
  {"type":"hello_ack","nodeId"}
  {"type":"pong"}
  {"type":"probe","probeId"}
  {"type":"run_job","jobId","config":{...}}
```

鉴权：`hello` 携带 `token`，控制面比对 `WORKER_TOKEN`（控制面未设置时跳过校验，用于本地开发）。
WS 端点不受浏览器 session 鉴权中间件约束（http middleware 不处理 WebSocket scope），由端点内
自行校验 token。

## 4. 代码结构

| 文件 | 职责 |
|---|---|
| `server/gpu/selfreg.py` | 控制面 WS 端点、内存注册表、心跳超时监控、`dispatch`（线程安全下发）、job 事件/结果处理 |
| `server/gpu/hosts.py` | 新增 `register_dynamic` / `unregister_dynamic`（自注册节点仅存内存，不写 `gpu_hosts.json`），`list_hosts` 合并动态节点 |
| `server/gpu/scheduler.py` | `_pick_host` 天然覆盖动态节点；`_spawn` 对 `provider='selfreg'` 走 `selfreg.dispatch` 而非本地 SSH 线程 |
| `server/agent.py` | 节点常驻 agent：dial-out、hello、心跳、probe 响应、`run_job` 执行与 `job_result` 回传 |

## 5. 部署

### 控制面

无需额外依赖（`uvicorn[standard]` 已含 `websockets`）。设置 `WORKER_TOKEN` 后正常启动即可；
自注册节点会出现在 `/gpu` 控制台与 `/api/gpu/hosts`、`/api/gpu/overview`。

### 节点（肉鸡 / AutoDL）

```bash
CONTROL_URL=http://8.153.36.240:8000 \
WORKER_TOKEN=<per-node-token> \
AGENT_NAME=AutoDL-4090 AGENT_ID=agent-autodl-4090 \
.venv/bin/python -m server.agent
```

| 变量 | 说明 |
|---|---|
| `CONTROL_URL` | 控制面 API 根地址（http/https，必填），自动换算 ws/wss |
| `WORKER_TOKEN` | 与控制面一致的鉴权令牌 |
| `AGENT_NAME` / `AGENT_ID` | 节点显示名 / 稳定 id（默认 hostname） |
| `AGENT_MAX_JOBS` | 并发任务上限（默认 1） |
| `AGENT_CAPS_OVERRIDE` | 逗号分隔能力名，覆盖自动探测（测试/声明式能力） |

## 6. 当前边界（v1）

- **共享存储假设**：agent 与控制面共享同一份 SQLite + 数据目录（同机 / NFS），`worker.run` 在
  agent 本地直接落库，控制面查询即见。跨机时需把 OSS 产物交换 + 事件回传补齐（`job_event` 已
  预留，`_handle_job_event` 目前仅日志，落库逻辑在 v2）。
- **能力探测**：agent 上报 `backends.capabilities()` 的真实探测结果；`AGENT_CAPS_OVERRIDE` 仅
  用于测试或显式声明，不保证与实际执行环境一致（执行仍以真实环境为准）。
- **取消传播**：`run_job` 任务在 agent 侧的取消未跨机传播（同现有 SSH 模式限制）。

## 7. 验证

```bash
# 开发机本地（同机控制面 + agent，验证注册/心跳/断线/派发链路）
bash /tmp/selfreg_e2e.sh                 # 注册、心跳、断线检测
.venv/bin/python /tmp/selfreg_dispatch_test.py   # 造任务 → 派发 → agent 执行 → 回传
```
