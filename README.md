# 2D→3D Studio

面向 Windows 工作站与局域网的单用户 2D→3D 生产工作台。实现了设计文档规定的六个核心页面、FastAPI/SQLite、本地文件版本、素材技术检查、不可变任务配置、单任务 Worker、SSE 事件、GLB 完整性检查、四视图产物、真实 Three.js 预览和人工验收闭环。

未登录首页为**温暖治愈风落地页**（奶油米色 + 樱花粉，参考「春日慢递」风格，含花瓣飘落、工坊清单勾选、拆信申请等交互），视觉参考与原始实现见 `design/sakura-bunny-site/`，落地页实现见 `src/pages/LandingPage.tsx`。

支持**分布式 GPU 集群**：主控（Mac mini / Linux，Docker）统一调度，任意数量 Windows GPU 节点通过 SSH 提供算力。新增一台机器只需注册一条配置（详见 `deploy/README.md`）。

## 快速启动

```powershell
powershell -ExecutionPolicy Bypass -File scripts/install.ps1
powershell -ExecutionPolicy Bypass -File scripts/start.ps1
```

打开 `http://127.0.0.1:5173`。API 文档位于 `http://127.0.0.1:8000/api/docs`。

手动启动：

```powershell
npm run api
npm run dev
```

## 部署架构（总控 + OSS + 显卡机器）

默认仍是单机模式（`WORKER_MODE=local`，进程内线程跑流水线）。设置 `WORKER_MODE=remote` 后拆为三节点：

- **总控**（ECS）：FastAPI + SQLite + 前端，任务停在 `queued`，通过 `/api/worker/*` 接口供远端认领。
- **OSS**：输入素材与产物的共享交换层。
- **显卡机**：`server.remote_worker` 拉取任务、跑 Hunyuan3D/Blender、产物回传 OSS 并上报。

部署步骤与环境变量见 [`deploy/README.md`](deploy/README.md)，架构与数据流见 [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)。

## 分布式 GPU 集群

Docker 部署（主控，含 GPU 控制台与队列调度）：

```bash
cd deploy/control-plane
./deploy.sh --host 100.69.5.47 --user d0993 --rebuild
# 控制台: http://127.0.0.1:8000/gpu
```

### 集群架构

```
主控（Docker print3d-server:8000）               GPU-1 / GPU-2 / ...（算力节点，Windows）
├─ FastAPI + Worker + 队列调度器                ├─ D:\print3d\local\Blender52
├─ GPU 控制台 (/gpu)：主机状态/队列/暂停         ├─ D:\print3d\local\hunyuan-bootstrap (torch cu124)
├─ 主机注册表 data/gpu_hosts.json                ├─ D:\print3d\local\Hunyuan3D-2.1-model (权重)
└─ 健康探测线程（GPU/显存/磁盘/能力）            └─ D:\print3d\TwoToThree (仓库)
        │ SSH + scp (压缩回传)
```

- **主机注册**：`deploy/control-plane/register-gpu.sh <name> <ip> <user> <key> <ext>`，或控制台表单；配置持久化在 `data/gpu_hosts.json`
- **健康探测**：每 30s 自动探测各主机在线状态、GPU 型号/显存、磁盘剩余、能力清单（Hunyuan/多视图/Blender/精修/STL）
- **任务队列**：任务创建后入队，调度器按「主后端能力匹配 + 在线 + 并发上限」派发到最优主机；主机禁用/离线自动跳过；无在线主机时回退本机执行
- **控制面板**（`/gpu`）：主机卡片（状态灯/GPU/显存条/磁盘/能力徽章/运行数）+ 队列三列视图（排队/运行/最近）+ 暂停/恢复调度
- **传输优化**：GLB 远端 tar.gz 压缩后回传（~65% 体积缩减）+ scp keepalive/重试，适配 tailscale/跨网段低带宽

部署手册：`deploy/README.md`（主控部署、GPU 节点安装、注册、运维速查）。

## 拓竹打印机接入（LAN 模式）

支持 Bambu Lab A1/P1/X1 系列局域网接入，通过 MQTT over TLS (8883) 读取实时状态。

- **开启 LAN 模式**：打印机屏幕 → 设置 → 局域网 → 开启局域网模式，记下访问码
- **注册**：控制台「打印机」页面（`/printer`）或 API `POST /api/printer/printers`（ip + accessCode）
- **状态**：每 20s 自动探测——在线/打印状态（空闲/待机预热/打印中/完成/失败/暂停）、喷嘴/热床温度、进度、层数、剩余时间、gcode 名、错误
- **配置**：`data/printers.json`；接入一台新打印机 = 加一条配置

## 打印流程（分模块 + AMS 多色）

打印工作台（`/print-workflow`）：导入模型 → 分模块 → 上色 → 导出 3MF → 发送打印。

- **① 导入模型**：GLB/STL/OBJ/3MF 拖拽上传
- **② 分模块**：Blender 在 GPU 节点按连通体自动拆分 → 每部件独立 STL + 预览图 + 尺寸/体积（`pipeline/blender_split_connected.py`，Blender 5.2 API 适配）
- **③ 上色**：每部件分配 AMS 线材色（12 色卡）→ 保存多色分配
- **④ 导出 3MF**：主控纯 Python 生成多色 3MF（`server/printpipeline/three_mf.py`，无需 Blender 3MF 插件）
- **⑤ 发送打印**：FTP（curl，拓竹 990 隐式 TLS）上传到打印机 → 可选 MQTT 启动命令

打印任务持久化在 `data/print_jobs/`，API 前缀 `/api/print/*`。

## 基础设施保障

- **GPU 故障转移**：打印流水线按 GPU-1→GPU-2→GPU-3… 顺序尝试，每台带超时保底，失败自动切换下一台（`run_on_hosts`）；GPU 控制台可随时禁用主机
- **CDN 大文件传输**：上传到 GPU 节点优先走 CDN（局域网 `192.168.31.210:12080` → 公网 `cdn.lovesun.top`，GPU 直接 curl 拉取），绕开 tailscale relay 慢路径（31MB 模型 0.5s vs 20 分钟）；scp 仅作兜底
- **探测隔离**：每台 GPU 主机独立探测线程（互不阻塞），单次命令 25s 硬超时

## 当前运行边界

- 示例任务使用仓库内已有、已验证的 Hunyuan/Blender 基线 GLB 和四视图，以便完整演示验收闭环。
- Worker 会明确记录 `local-verified-baseline`，不会把示例基线冒充为本次 Hunyuan 推理。
- 远程执行通过 `PRINT3D_MODE=remote` + `PRINT3D_REMOTE_HOST/USER/KEY/ROOT/EXT/WORK` 配置；单机模式保持原有本地执行。
- 大模型、SQLite 与生成产物默认位于 `%USERPROFILE%\AIData\3d`，可用 `STUDIO_EXTERNAL_ROOT` 覆盖。基线文件只复制到新版本目录，不会被覆盖。

## 验证

```powershell
npm run build
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe scripts/check_environment.py
```

## 目录

- `src/`：React/TypeScript 工作台与 Three.js 视口（含 GPU 控制台 `src/pages/GpuConsolePage.tsx`、打印机 `PrinterConsolePage.tsx`、打印工作台 `PrintWorkflowPage.tsx`）
- `server/`：FastAPI、SQLite、上传验证、SSE、本地 Worker 与远程执行层
- `server/gpu/`：**独立 GPU 集群模块**（主机注册表/健康探测/队列调度/控制面板 API，前缀 `/api/gpu/*`）
- `server/printer/`：**拓竹打印机接入模块**（LAN MQTT 客户端/注册表/状态探测，前缀 `/api/printer/*`）
- `server/printpipeline/`：**打印流程模块**（打印任务/分模块/AMS 上色，前缀 `/api/print/*`）
- `deploy/`：部署脚本（`gpu-node/setup.ps1` GPU 节点安装、`control-plane/` 主控部署与注册）
- `pipeline/blender_split_connected.py`：连通体拆分脚本（分模块打印）
- `%USERPROFILE%\AIData\3d\data\projects\<project-id>\versions\<version-id>\`：隔离的配置、模型、渲染、报告和日志
- `tests/`：上传安全与端到端任务契约测试
- `design/`：原始产品与实施规范，含落地页视觉参考 `design/sakura-bunny-site/`（「春日慢递·兔兔邮局」风格示例）

## 安全与可追踪性

上传会校验角色、扩展名、实际文件内容、大小和 SHA-256；存储路径只使用服务端 ID。任务配置按版本写入 `job-config.json`，重试创建新 Attempt，返工关联原版本，验收版本不会被原地覆盖。阶段输出采用 UTF-8 JSON 报告并保留失败诊断信息。
