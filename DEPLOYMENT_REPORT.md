# 2D→3D Studio 三节点部署交付文档

> 部署完成时间：2026-08-28
> 交付人：Codely CLI（自动化部署）

---

## 1. 架构概览

将原本「单机一体化」的 2D→3D Studio 重构为三节点架构：

```
浏览器 ──▶ 总控 ECS（nginx + FastAPI + SQLite）──▶ OSS（对象存储）
                │                                        ▲  ▲
                │                                        │  │
        显卡机（remote_worker）◀────────── 下载输入 / 上传产物 ─┘
        （Hunyuan3D + Blender）
```

| 节点 | 地址 | 角色 |
|---|---|---|
| 总控 ECS | `8.153.36.240`（80 / 8000） | nginx 托管前端 + FastAPI API + SQLite + 任务队列 |
| OSS | `print-3d`（oss-cn-shanghai） | 输入素材与产物的共享交换层，前缀 `two-to-three` |
| 显卡机 | `connect.westb.seetacloud.com:13142`（AutoDL 容器） | RTX 4090 D 24GB，跑 Hunyuan3D-2.1 + Blender 5.2.1 |

**数据流（生成任务）**：

```
1. 用户在总控上传素材 → 校验 → 创建任务（jobs.status = queued）
2. 显卡机 POST /api/worker/generate/claim 认领（原子置 running）
3. 总控把素材上传 OSS，返回签名 URL
4. 显卡机从 OSS 下载输入 → Hunyuan3D 生成 → Blender 四视图渲染
5. 产物上传 OSS → POST /complete 上报
6. 总控从 OSS 下载产物落库 → 任务 completed → 项目 ready_for_review
```

---

## 2. 访问入口

| 入口 | URL |
|---|---|
| 前端工作台 | `http://8.153.36.240/` |
| API 文档 | `http://8.153.36.240/api/docs` |
| 健康检查 | `http://8.153.36.240/api/system/health` |

---

## 3. 代码改动清单

### 3.1 新增文件

| 文件 | 职责 |
|---|---|
| `server/config.py` | 全部 env 配置（OSS 凭据、worker 模式/token、后端路径 Windows/Linux 自动探测） |
| `server/storage.py` | `OssStorage`（上传/下载/签名 URL）+ `Storage` 门面 |
| `server/pipeline.py` | 与存储/网络无关的流水线执行器（`Reporter` 回调 + 注入 backend callable） |
| `server/remote_worker.py` | 显卡机 worker：认领 → OSS 交换 → 推理 → 上报 |
| `deploy/` | `control.env.example`、`worker.env.example`、systemd 单元、install 脚本、README |
| `docs/ARCHITECTURE.md` | 架构与数据流文档 |

### 3.2 修改文件

| 文件 | 改动 |
|---|---|
| `server/backends.py` | 后端可执行路径全部从 `config` 读取，去 Windows 硬编码 |
| `server/worker.py` | 本地 worker 改为 `_DbReporter` 接 `run_pipeline` |
| `server/main.py` | 新增 `/api/worker/*` 接口 + 远程模式门控 + 命名遮蔽修复 |
| `pipeline/run_hunyuan_yoyo.py` | 由 `hy3dshape` 改写为官方 `hy3dgen`，加载 2.1 权重 |
| `requirements.txt` | 新增 `oss2>=2.18.0,<3.0` |

---

## 4. 关键决策与问题解决

### 4.1 `hy3dshape` 源码之谜
- **现象**：`run_hunyuan_yoyo.py` 引用 `from hy3dshape.pipelines import ...`，但官方仓库没有该包。
- **结论**：`hy3dshape` 就是官方 GitHub `Tencent-Hunyuan/Hunyuan3D-2` 仓库的 `hy3dgen`（旧名）。config.yaml 里的 `hy3dshape.*` 会被官方代码 `instantiate_from_config` 自动 `replace("hy3dshape", "hy3dgen.shapegen")` 映射。
- **加载方式**：Hunyuan3D-2.1 的 `hunyuan3d-dit-v2-1/model.fp16.ckpt` 内含 `model`/`vae`/`conditioner` 三个分量（顶层键已确认），用：
  ```python
  Hunyuan3DDiTFlowMatchingPipeline.from_pretrained(
      model_path, subfolder="hunyuan3d-dit-v2-1",
      use_safetensors=False, device="cuda", dtype=torch.float16,
  )
  ```

### 4.2 命名遮蔽 bug（部署中发现并修复）
- `new_job(pid, config, attempt)` 参数 `config` 遮蔽了模块 `server.config`，导致 `config.WORKER_MODE` 报 `AttributeError: 'dict' object has no attribute 'WORKER_MODE'`。
- `storage` 模块与 `storage.storage` 实例混用，导致 `module 'server.storage' has no attribute 'oss'`。
- **修复**：`from . import config as server_config` + `from .storage import storage`。

### 4.3 Blender 依赖
- 显卡机缺 `libSM.so.6`、`libICE.so.6`、`libEGL.so.1`，导致 Blender 退出码 127 / SIGABRT(-6)。
- **修复**：`apt-get install libsm6 libice6 libegl1 libegl-mesa0 libgl1-mesa-dri libgl1-mesa-glx libgles2 libosmesa6`。

### 4.4 rembg 背景移除模型
- `u2net.onnx`（176MB）从 GitHub 直连下载极慢，改用本机下载后 scp 上传到显卡机 `~/.u2net/`。

---

## 5. 显卡机环境清单

| 组件 | 版本 / 路径 |
|---|---|
| Python | `/root/miniconda3/bin/python`（3.10.8） |
| PyTorch | 2.6.0+cu124（CUDA 可用） |
| Hunyuan3D-2.1 权重 | `/root/autodl-tmp/two-to-three/.local/Hunyuan3D-2.1-model/`（DiT 7.3GB + VAE 655MB + config.yaml） |
| hy3dgen 源码 | `/root/autodl-tmp/Hunyuan3D-2/`（官方 Hunyuan3D-2 仓库） |
| Blender | `/root/autodl-tmp/blender/blender-5.2.1-linux-x64/blender`（5.2.1 LTS） |
| rembg 模型 | `/root/.u2net/u2net.onnx`（176MB） |
| worker 配置 | `/root/autodl-tmp/worker.env` |
| worker 启动脚本 | `/root/autodl-tmp/start_worker.sh` |
| 工作目录 | `/root/autodl-tmp/worker-data/` |

---

## 6. 端到端验证结果

任务 `job_f4b9315bad694931` 完整跑通，6 阶段全 `passed`：

| 阶段 | 状态 | 产物 |
|---|---|---|
| intake（素材接收） | ✅ passed | - |
| analysis（主体分析） | ✅ passed | - |
| geometry（几何生成） | ✅ passed | `baseline.glb`（178,811 顶点 / 357,648 面，6.4MB） |
| glb_validation（GLB 检查） | ✅ passed | glTF v2 校验通过 |
| multi_view_render（四视图） | ✅ passed | `web.glb`（30MB）+ front/left-three-quarter/side/back 四张 PNG |
| web_optimization（Web 输出） | ✅ passed | - |

**实际后端**：`hunyuan3d`（tencent/Hunyuan3D-2.1），20 steps / 256 resolution。

---

## 7. 运维要点

### 7.1 环境变量（凭据位置）
- 总控 env：`/opt/two-to-three/deploy/control.env`（含 OSS AccessKey + WORKER_TOKEN，权限 600）
- 显卡机 env：`/root/autodl-tmp/worker.env`
- 原始凭据记录：`C:\Users\D0993\Desktop\阿里云总控.md`（本地）

### 7.2 服务重启
```bash
# 总控 API（工作目录 /opt/two-to-three）
set -a && . deploy/control.env && set +a
nohup .venv/bin/python -m uvicorn server.main:app --host 0.0.0.0 --port 8000 &

# 总控 nginx
systemctl restart nginx

# 显卡机 worker
nohup bash /root/autodl-tmp/start_worker.sh > /root/autodl-tmp/worker.log 2>&1 &
```

### 7.3 日志位置
- 总控 API：`/var/log/two-to-three.log`
- 显卡机 worker：`/root/autodl-tmp/worker.log`

### 7.4 已知限制（v1）
1. **取消不跨机传播**：总控取消信号不会传到显卡机，需在显卡机终止 worker 进程。
2. **阶段级 report 不回传**：只回传质量报告（qualityReport），阶段级 `reports/*.json` 留在显卡机本地。
3. **单进程假设**：总控建议单 uvicorn worker（SQLite 锁 + 原子认领按单进程设计）。
4. **任务滞留风险**：任务被认领后（running）若 worker 崩溃，会滞留 running，需人工 `POST /api/jobs/{jid}/retry`。

---

## 8. 后续可做（非阻塞）

- [ ] 把 4 个本地 commit push 到 GitHub 仓库（需确认）
- [ ] 取消信号跨机传播（加 `should-cancel` 轮询接口）
- [ ] 阶段级 report 回传 OSS
- [ ] 生产化：换 PostgreSQL + 消息队列，支持多 worker
