# 2D→3D Studio

面向 Windows 工作站与局域网的单用户 2D→3D 生产工作台。实现了设计文档规定的六个核心页面、FastAPI/SQLite、本地文件版本、素材技术检查、不可变任务配置、单任务 Worker、SSE 事件、GLB 完整性检查、四视图产物、真实 Three.js 预览和人工验收闭环。

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

## 当前运行边界

- 示例任务使用仓库内已有、已验证的 Hunyuan/Blender 基线 GLB 和四视图，以便完整演示验收闭环。
- Worker 会明确记录 `local-verified-baseline`，不会把示例基线冒充为本次 Hunyuan 推理。
- 在接入生产 GPU 前，先配置模型权重与命令适配器；缺少 Blender 或 Hunyuan 权重不会被伪装为健康状态。
- SQLite 与所有任务产物位于 `data/`。基线文件只复制到新版本目录，不会被覆盖。

## 验证

```powershell
npm run build
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe scripts/check_environment.py
```

## 目录

- `src/`：React/TypeScript 工作台与 Three.js 视口
- `server/`：FastAPI、SQLite、上传验证、SSE 与本地 Worker
- `data/projects/<project-id>/versions/<version-id>/`：隔离的配置、模型、渲染、报告和日志
- `tests/`：上传安全与端到端任务契约测试
- `design/`：原始产品与实施规范

## 安全与可追踪性

上传会校验角色、扩展名、实际文件内容、大小和 SHA-256；存储路径只使用服务端 ID。任务配置按版本写入 `job-config.json`，重试创建新 Attempt，返工关联原版本，验收版本不会被原地覆盖。阶段输出采用 UTF-8 JSON 报告并保留失败诊断信息。
