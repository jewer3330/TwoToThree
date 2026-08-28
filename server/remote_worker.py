"""显卡机远端 Worker（三节点架构）。

运行于带 GPU/Blender 的机器，职责：
  - 轮询总控认领几何生成任务；
  - 从 OSS 下载 front/side/back 素材；
  - 调用 Hunyuan3D-2mv（多视图）/ Hunyuan3D-2.1（单图）+ Blender 跑流水线；
  - 将产物上传回 OSS，并通过 HTTP 上报进度与结果。

取消信号 v1 不跨机传播：``should_cancel`` 恒为 False，取消请直接终止本进程。
"""
from __future__ import annotations

import json
import sys
import time
import traceback
from pathlib import Path

import httpx

from . import config
from .backends import (
    capabilities,
    generate_hunyuan,
    generate_hunyuan_multiview,
    generate_sf3d,
    generate_triposr,
    render_blender,
)
from .core import sha256
from .pipeline import run_geometry_pipeline
from .storage import OssStorage


class Client:
    def __init__(self) -> None:
        if not config.CONTROL_URL:
            raise SystemExit("缺少 CONTROL_URL（总控 API 根地址）")
        if not config.WORKER_TOKEN:
            raise SystemExit("缺少 WORKER_TOKEN（与总控一致的鉴权令牌）")
        self._http = httpx.Client(base_url=config.CONTROL_URL, timeout=config.CONTROL_TIMEOUT)

    def _headers(self) -> dict:
        return {"X-Worker-Token": config.WORKER_TOKEN, "Content-Type": "application/json"}

    def post(self, path: str, body: dict | None = None):
        resp = self._http.post(path, json=body, headers=self._headers())
        resp.raise_for_status()
        return resp.json() if resp.content else None


class _HttpReporter:
    """把流水线进度回调转发为总控的 HTTP 上报（best-effort，失败不中断流水线）。"""

    def __init__(self, client: Client, job_id: str):
        self._client = client
        self._job_id = job_id

    def _post(self, path: str, body: dict) -> None:
        try:
            self._client.post(path, body)
        except Exception as exc:  # noqa: BLE001
            print(f"[worker] 上报失败 {path}: {exc}", file=sys.stderr)

    def log(self, message: str) -> None:
        self._post(f"/api/worker/generate/{self._job_id}/log", {"message": message})

    def should_cancel(self) -> bool:
        return False

    def stage_started(self, key: str, label: str) -> None:
        self._post(f"/api/worker/generate/{self._job_id}/stage", {"stage": key, "status": "running", "label": label})

    def stage_completed(self, key: str, warnings: list[str]) -> None:
        self._post(f"/api/worker/generate/{self._job_id}/stage", {"stage": key, "status": "passed", "warnings": warnings})

    def backend(self, actual_backend: str, model_version: str | None) -> None:
        pass  # 后端信息随 complete 一并上报


def _process_generate(client: Client, task: dict, oss: OssStorage) -> None:
    job_id = task["jobId"]
    project_id = task["projectId"]
    version_id = task["versionId"]
    root = Path(config.WORK_DIR) / "jobs" / job_id
    input_dir = root / "input"
    input_dir.mkdir(parents=True, exist_ok=True)

    source_images: dict[str, Path] = {}
    for role, item in task.get("sourceImages", {}).items():
        ext = Path(item.get("originalName", role)).suffix or ".png"
        dest = input_dir / f"{role}{ext}"
        oss.download(item["ossKey"], dest)
        source_images[role] = dest

    version_root = root / "versions" / version_id
    (root / "job-config.json").write_text(json.dumps(task.get("config", {}), ensure_ascii=False, indent=2), encoding="utf-8")

    result = run_geometry_pipeline(
        config=task.get("config", {}),
        source_images=source_images,
        version_root=version_root,
        seed=task.get("seed", 0),
        subject_type=task.get("subjectType", "character"),
        reporter=_HttpReporter(client, job_id),
        capabilities=capabilities,
        generate_hunyuan=generate_hunyuan,
        generate_hunyuan_multiview=generate_hunyuan_multiview,
        generate_sf3d=generate_sf3d,
        generate_triposr=generate_triposr,
        render_blender=render_blender,
    )

    artifacts = []
    for art in result.artifacts:
        rel = art.path.relative_to(version_root).as_posix()
        key = f"projects/{project_id}/versions/{version_id}/{rel}"
        oss.upload(art.path, key)
        artifacts.append({
            "kind": art.kind,
            "label": art.label,
            "relPath": rel,
            "mimeType": art.mime,
            "byteSize": art.path.stat().st_size,
            "sha256": sha256(art.path),
            "metadata": art.metadata,
        })
    client.post(
        f"/api/worker/generate/{job_id}/complete",
        {
            "actualBackend": result.actual_backend,
            "modelVersion": result.model_version,
            "geometryMetrics": result.geometry_metrics,
            "artifacts": artifacts,
        },
    )
    print(f"[worker] 生成任务完成：{job_id}")


def main() -> None:
    client = Client()
    oss = OssStorage()
    print(f"[worker] 已连接总控 {config.CONTROL_URL}，轮询间隔 {config.POLL_INTERVAL}s")
    while True:
        try:
            task = client.post("/api/worker/generate/claim") or {}
            if task:
                try:
                    _process_generate(client, task, oss)
                except Exception as exc:  # noqa: BLE001
                    traceback.print_exc()
                    try:
                        client.post(f"/api/worker/generate/{task['jobId']}/fail", {"error": str(exc)})
                    except Exception:  # noqa: BLE001
                        pass
                continue
        except Exception as exc:  # noqa: BLE001
            print(f"[worker] 轮询异常：{exc}", file=sys.stderr)
            traceback.print_exc()
        time.sleep(config.POLL_INTERVAL)


if __name__ == "__main__":
    main()
