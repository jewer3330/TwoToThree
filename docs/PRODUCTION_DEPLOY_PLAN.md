# 正式环境部署计划（生产）

> 状态：**待用户确认**（2026-09-02 编写）
> 执行方式：分阶段，每阶段跑 `scripts/check_deployment.py` 验证后再进下一阶段。

## 0. 现状与目标

### 现状（已就绪）

| 项 | 现状 |
|---|---|
| 生产总控 | 阿里云 ECS `8.153.36.240`，已跑 nginx + FastAPI + SQLite（三节点旧部署，**缺自注册代码与账户系统**） |
| 生产域名 | `3.lovesun.top`（Cloudflare 代理，已修好 443/521） |
| OSS | `print-3d`（oss-cn-shanghai），前缀 `two-to-three` |
| 开发环境 | 家宽 Mac `print3d-server` Docker + `t.lovesun.top` tunnel（自注册 WS 已实测通过） |
| 代码 | `jewer3330/TwoToThree` `printworld-all` 分支（自注册 + 环境监测脚本，PR #2 待合并） |
| 4060 节点 | Windows，Tailscale `100.69.5.47`，SSH 免密（端口非 22，待确认） |
| 账户系统 | Authentik OIDC 已集成（`server/auth.py`），家宽已部署一套；生产需独立部署 |

### 目标架构

```
浏览器 ──▶ 3.lovesun.top (Cloudflare)
              │
              ▼
        生产总控 ECS 8.153.36.240
        ├─ nginx(80/443) + FastAPI + SQLite
        ├─ 账户系统：Authentik OIDC（studio-admin / studio-user 组）
        ├─ WORKER_TOKEN + OSS 凭据
        └─ WS 端点 /api/gpu/ws（自注册）
              ▲
              │ wss://3.lovesun.top/api/gpu/ws（dial-out）
        ┌─────┴──────┐
   4060 节点      AutoDL 肉鸡
   (Tailscale)    (明天实测)
   server.agent   server.agent
```

## 1. 阶段 0 — 环境监测基线

生产 ECS 与新节点都先跑监测脚本，摸清缺口再动手。

```bash
# 生产 ECS（用部署实际 python）
cd /opt/two-to-three && .venv/bin/python scripts/check_deployment.py --role control

# 4060 节点（Windows）
cd D:\print3d\TwoToThree && python scripts\check_deployment.py --role node

# AutoDL 肉鸡（Linux）
cd /root/autodl-tmp/print3d/TwoToThree && python3 scripts/check_deployment.py --role node
```

> 脚本尚未在 ECS 上（需先拉新代码），阶段 0 可先只跑本地/节点。

## 2. 阶段 1 — ECS 拉新代码 + 基础配置

1. **拉新代码**到 ECS `/opt/two-to-three`（当前是 DEPLOYMENT_REPORT 的旧版）。
2. **生成强随机凭据**并写入 `deploy/control.env`（权限 600）：
   - `WORKER_TOKEN`（`openssl rand -hex 32`）
   - `OSS_ACCESS_KEY_ID` / `OSS_ACCESS_KEY_SECRET` / `OSS_BUCKET=print-3d`
3. 前端 `npm run build` 生成 `dist/`，nginx 继续托管并反代 `/api` `/data` `/public`。
4. 重启 API，`check_deployment.py --role control` 应通过（除 auth 外）。

## 3. 阶段 2 — 账户系统（Authentik OIDC）

生产 ECS 独立部署 Authentik（家宽那套不稳定，不能复用）。步骤见 `deploy/authentik/README.md`：

1. 在 ECS 上用 Docker compose 部署 Authentik + Postgres + Redis（固定 `AUTHENTIK_TAG`，禁 `latest`）。
2. 建 OAuth2/OpenID Provider（Confidential，Redirect URI = `https://3.lovesun.top/api/auth/callback`）。
3. 建 `studio-admin` / `studio-user` 组 + 至少一个管理员账号。
4. ECS 配置（`control.env`）：
   ```
   AUTH_DISABLED=false
   SESSION_SECRET=<openssl rand -base64 48>
   OIDC_ISSUER=https://<authentik>/application/o/studio/
   OIDC_CLIENT_ID=...   OIDC_CLIENT_SECRET=...
   OIDC_ADMIN_GROUP=studio-admin   OIDC_USER_GROUP=studio-user
   ```
5. 验证：`/api/projects` 匿名 401，`/api/system/health` 200，普通用户访问 `/api/gpu/*` 403。

> **待确认**：Authentik 放 ECS 同机（省一台机器，够用）还是独立实例？域名 `auth.lovesun.top` 还是同域 `/authentik/` 路径？

## 4. 阶段 3 — 4060 节点注册（自注册 agent）

4060 是 Windows + Tailscale，走自注册（不再依赖 SSH 推模式）：

```powershell
# 在 4060 上（仓库已在 D:\print3d\TwoToThree）
$env:STUDIO_EXTERNAL_ROOT = 'D:\print3d'
$env:CONTROL_URL = 'https://3.lovesun.top'
$env:WORKER_TOKEN = '<与总控一致>'
$env:AGENT_ID = 'gpu-4060'
$env:AGENT_NAME = 'RTX 4060'
.\.venv\Scripts\python.exe -m server.agent
```

验证：`check_deployment.py --role node` 全绿 → 控制台 `/gpu` 看到 4060 在线、能力正确。

> **待确认**：4060 的 SSH 端口（我测 22 超时，但你说免密直连，可能端口非 22 或需等 Tailscale 直连建立）。自注册不依赖 SSH，只要 agent 能出网连 `3.lovesun.top` 即可。

## 5. 阶段 4 — AutoDL 肉鸡实测（明天）

1. 在 AutoDL 实例跑 `deploy/gpu-node/setup.sh`（Linux 装机，含 Hunyuan3D-2.1 权重 + Blender + torch）。
2. `check_deployment.py --role node` 验证环境。
3. 启动 agent 连 `wss://3.lovesun.top/api/gpu/ws`，控制台确认在线 + 能力。
4. 端到端：造一个任务 → 调度器派发 → agent 推理 → 产物回传。

> 若 AutoDL 是 Pro 实例，可配 `AUTODL_API_TOKEN` 让调度器按需开机/空闲关机。

## 6. 阶段 5 — 验证与切换

- [ ] `check_deployment.py --role control` 全绿（含 auth）
- [ ] 4060 + AutoDL 都在 `/gpu` 控制台在线
- [ ] 匿名业务 API 401，管理员能登录
- [ ] 端到端任务跑通（2D→3D 生成 + 四视图）
- [ ] 域名 `3.lovesun.top` 全链路 HTTPS

## 7. 待确认清单（明天问用户）

1. **Authentik 部署位置**：ECS 同机 Docker，还是独立实例？域名方案（`auth.lovesun.top` vs 同域 `/authentik/`）。
2. **4060 SSH 端口**：22 我测超时，免密直连用的什么端口？还是干脆只走自注册、不配 SSH？
3. **OSS 凭据**：ECS 上 `control.env` 里是否已有 OSS AccessKey？（DEPLOYMENT_REPORT 说有，但需确认是否还可用）
4. **AutoDL 实例**：明天用哪台？是否 Pro（支持按需开关机）？
5. **PR #2**：caohanzhi 是否已合并？正式线部署前建议先合入上游 main。

## 8. 风险与回滚

- **账户系统 fail-closed**：OIDC 配错会导致全站 401。回滚 = `AUTH_DISABLED=true` 临时放行，修好再关。
- **WORKER_TOKEN 不匹配**：节点连不上，WS 握手会明确报 `invalid worker token`，易定位。
- **ECS 旧代码覆盖**：拉新代码前先 `git stash`/备份 `/opt/two-to-three`，保留 `control.env`。
- **生产与开发隔离**：生产 `WORKER_TOKEN`/`SESSION_SECRET`/OSS 前缀（`two-to-three`）与开发环境分开，避免串数据。
