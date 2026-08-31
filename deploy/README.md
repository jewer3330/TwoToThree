# 2D→3D Studio 分布式部署

主控（Mac mini/Linux，Docker） + N 台 GPU 机器（Windows，SSH）。**新增机器 = 注册一条配置**，无需改代码。

```
Mac mini (主控)                          GPU-1 / GPU-2 / ...（算力节点）
┌─────────────────────────┐             ┌──────────────────────────┐
│ Docker print3d-server   │  ── SSH ──▶ │ Windows 10/11             │
│  FastAPI + Worker       │  scp 回传   │  D:\print3d\              │
│  GPU 控制台 /api/gpu/*  │             │   ├─ local\Blender52      │
│  主机注册表 gpu_hosts   │             │   ├─ local\hunyuan-...    │
│  健康探测 + 队列调度    │             │   ├─ local\Hunyuan3D-2.1  │
│  OIDC 登录 + 本地数据卷 │             │   └─ TwoToThree\(仓库)    │
└─────────────────────────┘             └──────────────────────────┘
```

## 1. 部署主控（Mac mini）

```bash
cd deploy/control-plane
./deploy.sh --host 100.69.5.47 --user d0993 --rebuild   # 首次加 --rebuild
# 配置 Authentik OIDC 后打开 https://studio.example.com/gpu
```

依赖：Docker Desktop、`/Volumes/ssd/servers/print3d_server` 目录（含 `keys/` SSH 私钥、`data/` 数据卷）、compose 需在 `love-net` 网络。

登录部署见 [`deploy/authentik/README.md`](authentik/README.md)。生产环境缺少 OIDC 或 Session 密钥时服务会拒绝启动。

## 2. 部署 GPU 节点（Windows）

```powershell
# 在 GPU 机器上（管理员 PowerShell），或从主控 SSH 执行
scp -i ~/.ssh/id_ed25519_ai_video deploy/gpu-node/setup.ps1 <user>@<ip>:D:/setup.ps1
ssh <user>@<ip> "powershell -ExecutionPolicy Bypass -File D:\setup.ps1"
```

脚本参数：`-Root D:\print3d`（默认）、`-SkipWeights`（权重已有/暂缓）、`-SkipBlender`、`-SkipRepo`。
**GitHub 被墙时**：从主控打包直传（仓库代码在 Mac 上有）：

```bash
cd <repo根> && tar czf /tmp/twotothree.tar.gz pipeline server studio_paths.py
scp -i ~/.ssh/id_ed25519_ai_video /tmp/twotothree.tar.gz <user>@<ip>:D:/print3d/
ssh <user>@<ip> "powershell -Command \"New-Item -ItemType Directory -Force D:\print3d\TwoToThree; tar -xzf D:\print3d\twotothree.tar.gz -C D:\print3d; Move-Item D:\print3d\pipeline,D:\print3d\server,D:\print3d\studio_paths.py D:\print3d\TwoToThree\""
```

## 3. 注册 GPU 节点（新增机器 = 一步）

```bash
cd deploy/control-plane
./register-gpu.sh GPU-2 100.69.5.47 d0993 /run/secrets/gpu_key D:\\print3d
# 或直接编辑主控 data/gpu_hosts.json（容器内 /app/ext/data/gpu_hosts.json）
```

注册后探针自动识别 GPU/显存/磁盘/能力，调度器即可把任务派发到该机。支持 `maxConcurrentJobs`、`enabled`（暂停/启用）、`labels`。

## 4. 任务队列

- 任务创建后进入 `queued`，调度器每 5s 按 **能力匹配 + 在线 + 并发上限** 派发到最优主机
- 控制台 `/gpu`：主机状态卡片（在线/显存/磁盘/能力徽章）、队列三列视图（排队/运行/最近）、暂停/恢复调度
- 无任何在线主机时自动退回本机执行（兼容单机模式）

## 5. 运维

```bash
docker logs -f print3d-server          # 日志
docker compose up -d --build           # 更新（deploy.sh --rebuild）
cat /Volumes/ssd/servers/print3d_server/data/gpu_hosts.json   # 主机配置
# GPU 管理 API 需要已登录的管理员 Session；不要再匿名 curl 管理接口。
```
