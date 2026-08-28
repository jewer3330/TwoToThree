# 总控 + OSS + 显卡机器 部署指南

三节点架构把原来单机的「API + 本地线程 Worker + 本地磁盘」拆成三层：

```
浏览器 ──▶ 总控 ECS（FastAPI + SQLite + 前端静态页）──▶ OSS（对象存储）
                                                              ▲  ▲
                                                              │  │
显卡机（remote_worker：Hunyuan3D + Blender）──────────▶ 下载输入 / 上传产物
```

- **总控**：跑 `server.main:app`，`WORKER_MODE=remote`，任务停留在 `queued`，由显卡机认领；产物经 OSS 回传后落回本地缓存并入库。
- **OSS**：输入素材与产物的共享交换层（bucket `print-3d`），总控与显卡机共用同一份 AccessKey。
- **显卡机**：跑 `server.remote_worker`，轮询认领生成/精修任务，本地 Hunyuan3D/Blender 推理，产物回传 OSS 并上报总控。

## 一、总控（ECS）

```bash
cd /opt && git clone https://github.com/hanzhicao82-stack/TwoToThree.git two-to-three
cd two-to-three
bash deploy/install_control.sh
cp deploy/control.env.example deploy/control.env
# 编辑 deploy/control.env：填入 OSS 凭据 + 设置 WORKER_TOKEN
```

启动（二选一）：

```bash
# 方式 A：systemd
sudo cp deploy/control.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now two-to-three-control

# 方式 B：前台调试
.venv/bin/python -m uvicorn server.main:app --host 0.0.0.0 --port 8000
```

前端静态页：`npm run build` 生成 `dist/`，由 nginx 托管并反代 `/api`、`/data`、`/public` 到 `127.0.0.1:8000`：

```nginx
server {
  listen 80;
  root /opt/two-to-three/dist;
  index index.html;
  location /api/   { proxy_pass http://127.0.0.1:8000; }
  location /data/  { proxy_pass http://127.0.0.1:8000; }
  location /public/{ proxy_pass http://127.0.0.1:8000; }
  location /       { try_files $uri /index.html; }
}
```

## 二、显卡机（GPU / Blender）

前提：Hunyuan3D 2.1 权重、对应 Python 环境、Blender 均已就绪（路径通过 env 指定）。

```bash
cd /opt && git clone https://github.com/hanzhicao82-stack/TwoToThree.git two-to-three
cd two-to-three
bash deploy/install_worker.sh
cp deploy/worker.env.example deploy/worker.env
# 编辑 deploy/worker.env：CONTROL_URL、WORKER_TOKEN、OSS 凭据、HUNYUAN_*/BLENDER 路径
```

启动：

```bash
sudo cp deploy/worker.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now two-to-three-worker
# 或前台调试：.venv/bin/python -m server.remote_worker
```

## 三、环境变量参考

| 变量 | 作用 | 节点 |
|---|---|---|
| `WORKER_MODE` | `local`(默认) / `remote` | 总控 |
| `WORKER_TOKEN` | 总控↔显卡机鉴权令牌 | 两者 |
| `CONTROL_URL` | 总控 API 根地址 | 显卡机 |
| `OSS_ENDPOINT` | OSS 地域节点 | 两者 |
| `OSS_BUCKET` | 桶名 | 两者 |
| `OSS_ACCESS_KEY_ID` / `OSS_ACCESS_KEY_SECRET` | OSS 凭据 | 两者 |
| `OSS_PREFIX` | 对象键前缀（默认 `two-to-three`） | 两者 |
| `HUNYUAN_PY` / `HUNYUAN_MODEL` / `HUNYUAN_RUNNER` | Hunyuan 环境/权重/脚本 | 显卡机 |
| `BLENDER` / `BLENDER_RENDERER` / `BLENDER_REFINER` | Blender 及脚本 | 显卡机 |
| `POLL_INTERVAL` | 认领轮询间隔（秒，默认 5） | 显卡机 |
| `WORK_DIR` | worker 本地临时目录（默认 `data/worker`） | 显卡机 |

后端路径未配置时，`server/config.py` 会自动探测 Windows 与 Linux 的常见布局；已自定义安装路径时用 env 覆盖。

## 四、已知限制（v1）

- 总控的「取消」信号暂不跨机传播：显卡机 `should_cancel` 恒为 False，取消需直接终止 worker 进程。
- 阶段级 `reports/*.json` 不随远程任务回传，仅质量报告（`qualityReport`）会落库；阶段进度通过 SSE 事件反映。
- 建议总控以单 uvicorn worker 运行（SQLite 锁与原子认领按单进程设计）；并发多进程需引入独立消息队列/数据库。
- 任务被认领后（`running`）若 worker 崩溃，任务会滞留 `running`，需人工重试（`POST /api/jobs/{jid}/retry`）。
