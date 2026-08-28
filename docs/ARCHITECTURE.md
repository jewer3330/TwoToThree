# 架构：总控 + OSS + 显卡机器

本文描述把原本「单机一体化」的 2D→3D Studio 拆成三节点后的数据流、组件与扩展点。

## 1. 拓扑

```
                        ┌──────────────────────────────────────────────┐
                        │  总控（阿里云 ECS）                              │
                        │  FastAPI (server.main)                        │
                        │  ├─ 项目管理 / 上传校验 / 版本 / 验收 / SSE      │
                        │  ├─ 任务队列（jobs / refinement_jobs = queued） │
                        │  ├─ Worker 接口（claim/stage/log/complete/fail）│
                        │  ├─ SQLite（data/studio.db）                   │
                        │  └─ 本地磁盘缓存（data/projects/...）           │
                        └───────────────┬──────────────────────────────┘
                                        │ oss2（上传输入 / 下载产物）
                        ┌───────────────▼──────────────────────────────┐
                        │  阿里云 OSS（bucket: print-3d）                │
                        │  前缀：two-to-three/projects/<pid>/...        │
                        └───────────────▲──────────────────────────────┘
                                        │ oss2（下载输入 / 上传产物）
                        ┌───────────────┴──────────────────────────────┐
                        │  显卡机（GPU / Blender）                       │
                        │  server.remote_worker                        │
                        │  ├─ 轮询认领任务                               │
                        │  ├─ Hunyuan3D 2.1 / Blender 5.x 推理          │
                        │  └─ 上报进度与结果（HTTP）                      │
                        └──────────────────────────────────────────────┘
```

## 2. 关键数据流

### 生成任务（geometry pipeline）

1. 用户在总控上传素材 → 校验 → 创建任务，`jobs.status = queued`（`WORKER_MODE=remote` 时不再启动本地线程）。
2. 显卡机 `POST /api/worker/generate/claim`：总控原子地把最老的 `queued` 任务置为 `running`，把素材上传 OSS 并返回签名 URL + OSS 键。
3. 显卡机从 OSS 下载正面图，调用 `server.pipeline.run_pipeline` 跑 Hunyuan3D → Blender 四视图。
4. 运行中 `POST /api/worker/generate/{jid}/stage` / `.../log` 上报进度，总控写 `stages` / `events`，前端经 SSE 实时可见。
5. 完成后显卡机把 GLB/四视图上传 OSS，`POST .../complete`；总控从 OSS 下载产物到本地缓存并入库，任务 `completed`，项目 `ready_for_review`。

### 精修任务（Blender auto-refine）

与生成类似，任务类型为 `refine`：源 GLB 与正面参考图经 OSS 下发给显卡机，`refine_blender` 产出 `refined.glb` / PBR 贴图 / 四视图 / 质量报告，回传后总控复用 `_commit_refinement_result` 完成版本与产物的落库。

## 3. 代码结构

| 文件 | 职责 |
|---|---|
| `server/config.py` | 全部 env 配置：OSS 凭据、worker 模式/token、后端路径（Windows/Linux 探测） |
| `server/storage.py` | `OssStorage`（上传/下载/签名 URL/存在性）+ `Storage` 门面；未配置 OSS 时现有行为不变 |
| `server/pipeline.py` | 与存储/网络无关的流水线执行器：`STAGES`、`glb_info`、`run_pipeline`（`Reporter` 回调 + 注入 backend callable） |
| `server/backends.py` | Hunyuan/SF3D/TripoSR/Blender 的子进程适配器，路径从 `config` 读取 |
| `server/worker.py` | 本地 worker：`_DbReporter` 把 SQLite/SSE 副作用接到 `run_pipeline` |
| `server/remote_worker.py` | 显卡机 worker：HTTP 上报 + OSS 交换 + `run_pipeline` / `refine_blender` |
| `server/main.py` | 业务 API + Worker 接口（`/api/worker/...`，`X-Worker-Token` 鉴权）+ 远程模式门控 |

## 4. 扩展点

- **新增后端**：在 `server/backends.py` 加 `generate_xxx`，`server/config.py` 加路径，`server/pipeline.py` 的 `geometry` 降级链里加分支即可。
- **取消跨机传播**：给总控加 `GET /api/worker/generate/{jid}/should-cancel`，worker 用后台线程轮询刷新本地标志（当前 v1 未实现）。
- **多 worker / 高并发**：把 `jobs.status` 认领改为带超时的分布式锁或引入 Redis 队列；SQLite 需换 PostgreSQL 以支持多进程。
