"""显卡机上的远端 Worker。

运行于带 GPU/Blender 的机器，职责：

  - 轮询总控认领「生成 / 精修」任务；
  - 从 OSS 下载输入（正面图 / 源 GLB / 参考图）；
  - 调用本地 Hunyuan3D / Blender 跑流水线（复用 ``server.pipeline`` / ``server.backends``）；
  - 将产物上传回 OSS，并通过 HTTP 向总控上报进度与结果。

所需环境变量（与总控共享 OSS 凭据）：见 ``deploy/worker.env.example``。

限制（v1）：总控的取消信号暂不跨机传播，本 worker 的 ``should_cancel`` 恒为 False；
如需取消请直接终止本进程。
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
    generate_sf3d,
    generate_triposr,
    refine_blender,
    render_blender,
)
from .core import sha256
from .pipeline import run_pipeline
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


def _generate_oss_key(project_id: str, version_id: str, artifact) -> str:
    if artifact.kind == "render":
        return f"projects/{project_id}/versions/{version_id}/renders/{artifact.label}.png"
    return f"projects/{project_id}/versions/{version_id}/models/{artifact.label}"


class _RemoteReporter:
    """把流水线进度回调转发为总控的 HTTP 上报（best-effort，失败不中断流水线）。"""

    def __init__(self, client: Client, job_id: str):
        self._client = client
        self._job_id = job_id

    def log(self, message: str) -> None:
        try:
            self._client.post(f"/api/worker/generate/{self._job_id}/log", {"message": message})
        except Exception as exc:  # noqa: BLE001
            print(f"[worker] 上报日志失败：{exc}", file=sys.stderr)

    def should_cancel(self) -> bool:
        return False

    def stage_started(self, key: str, label: str) -> None:
        try:
            self._client.post(f"/api/worker/generate/{self._job_id}/stage", {"stage": key, "status": "running", "label": label})
        except Exception as exc:  # noqa: BLE001
            print(f"[worker] 上报阶段失败：{exc}", file=sys.stderr)

    def stage_completed(self, key: str, warnings: list[str], report_path: Path) -> None:
        try:
            self._client.post(f"/api/worker/generate/{self._job_id}/stage", {"stage": key, "status": "passed", "warnings": warnings})
        except Exception as exc:  # noqa: BLE001
            print(f"[worker] 上报阶段失败：{exc}", file=sys.stderr)

    def artifact(self, artifact) -> None:
        pass

    def backend(self, actual_backend: str, model_version: str | None) -> None:
        pass


def _process_generate(client: Client, task: dict, oss: OssStorage) -> None:
    job_id = task["jobId"]
    project_id = task["projectId"]
    version_id = task["versionId"]
    root = Path(config.WORK_DIR) / "jobs" / job_id
    input_dir = root / "input"
    input_dir.mkdir(parents=True, exist_ok=True)

    front: Path | None = None
    for item in task.get("inputs", []):
        ext = Path(item.get("originalName", "input")).suffix or ".png"
        dest = input_dir / f"{item['role']}{ext}"
        oss.download(item["ossKey"], dest)
        if item["role"] == "front":
            front = dest
    if front is None:
        raise RuntimeError("任务缺少正面素材（front）")

    version_root = root / "versions" / version_id
    (root / "job-config.json").write_text(json.dumps(task.get("config", {}), ensure_ascii=False, indent=2), encoding="utf-8")

    result = run_pipeline(
        config=task.get("config", {}),
        source_image=front,
        version_root=version_root,
        seed=task.get("seed", 0),
        reporter=_RemoteReporter(client, job_id),
        capabilities=capabilities,
        generate_hunyuan=generate_hunyuan,
        generate_sf3d=generate_sf3d,
        generate_triposr=generate_triposr,
        render_blender=render_blender,
    )

    artifacts = []
    for art in result.artifacts:
        key = _generate_oss_key(project_id, version_id, art)
        oss.upload(art.path, key)
        artifacts.append({
            "kind": art.kind,
            "label": art.label,
            "ossKey": key,
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
            "qualityReport": result.quality,
            "artifacts": artifacts,
        },
    )
    print(f"[worker] 生成任务完成：{job_id}")


def _refine_files(root: Path, config_path: Path) -> list[tuple[str, str, Path, str]]:
    files = [
        ("glb", "refined.glb", root / "refined.glb", "model/gltf-binary"),
        ("quality_report", "quality-report.json", root / "quality-report.json", "application/json"),
        ("config", "config-snapshot.json", config_path, "application/json"),
    ]
    files += [("texture", f"{n}.png", root / "textures" / f"{n}.png", "image/png") for n in ("base-color", "roughness", "metallic", "normal", "ao")]
    files += [("render", f"{n}.png", root / f"{n}.png", "image/png") for n in ("front", "left-three-quarter", "side", "back")]
    return files


def _process_refine(client: Client, task: dict, oss: OssStorage) -> None:
    jid = task["refinementJobId"]
    project_id = task["projectId"]
    root = Path(config.WORK_DIR) / "refine" / jid
    root.mkdir(parents=True, exist_ok=True)

    source = root / "source.glb"
    oss.download(task["sourceGlb"]["ossKey"], source)
    reference = None
    if task.get("reference"):
        reference = root / "reference.png"
        oss.download(task["reference"]["ossKey"], reference)

    config_path = root / "config-snapshot.json"
    config_path.write_text(json.dumps(task.get("config", {}), ensure_ascii=False, indent=2), encoding="utf-8")

    def log(message: str) -> None:
        try:
            client.post(f"/api/worker/refine/{jid}/log", {"message": message})
        except Exception as exc:  # noqa: BLE001
            print(f"[worker] 精修日志上报失败：{exc}", file=sys.stderr)

    result = refine_blender(source, root, config_path, log, lambda: False, reference)

    artifacts = []
    for kind, label, path, mime in _refine_files(root, config_path):
        if not path.exists():
            continue
        key = f"projects/{project_id}/refinements/{jid}/{Path(label).name}"
        oss.upload(path, key)
        artifacts.append({
            "kind": kind,
            "label": label,
            "ossKey": key,
            "mimeType": mime,
            "byteSize": path.stat().st_size,
            "sha256": sha256(path),
            "metadata": {},
        })
    client.post(f"/api/worker/refine/{jid}/complete", {"result": result, "artifacts": artifacts})
    print(f"[worker] 精修任务完成：{jid}")


def _dispatch(client: Client, task: dict, oss: OssStorage) -> None:
    kind = task.get("type")
    if kind == "generate":
        try:
            _process_generate(client, task, oss)
        except Exception as exc:  # noqa: BLE001
            traceback.print_exc()
            try:
                client.post(f"/api/worker/generate/{task['jobId']}/fail", {"error": str(exc)})
            except Exception:  # noqa: BLE001
                pass
    elif kind == "refine":
        try:
            _process_refine(client, task, oss)
        except Exception as exc:  # noqa: BLE001
            traceback.print_exc()
            try:
                client.post(f"/api/worker/refine/{task['refinementJobId']}/fail", {"error": str(exc)})
            except Exception:  # noqa: BLE001
                pass
    else:
        print(f"[worker] 未知任务类型：{kind}", file=sys.stderr)


def main() -> None:
    client = Client()
    oss = OssStorage()
    print(f"[worker] 已连接总控 {config.CONTROL_URL}，轮询间隔 {config.POLL_INTERVAL}s")
    while True:
        try:
            task = client.post("/api/worker/generate/claim") or {}
            if not task:
                task = client.post("/api/worker/refine/claim") or {}
            if task:
                _dispatch(client, task, oss)
                continue
        except Exception as exc:  # noqa: BLE001
            print(f"[worker] 轮询异常：{exc}", file=sys.stderr)
            traceback.print_exc()
        time.sleep(config.POLL_INTERVAL)


if __name__ == "__main__":
    main()
