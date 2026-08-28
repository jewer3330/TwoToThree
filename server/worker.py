"""本地 worker：在 API 进程内以线程方式串行执行生成流水线。

流水线逻辑在 ``server.pipeline`` 中；这里只负责把 SQLite/SSE 的副作用（``_DbReporter``）
接到流水线上。``capabilities`` / ``generate_hunyuan`` / ``render_blender`` 等保留为模块级
名称，以便测试用 monkeypatch 替换。
"""
from __future__ import annotations

import json
import threading
from pathlib import Path

from .backends import CancelledError, capabilities, generate_hunyuan, generate_sf3d, generate_triposr, render_blender
from .core import ROOT, db, dump, now, project_dir, sha256, uid
from .pipeline import STAGES, Artifact, run_pipeline

_threads: dict[str, threading.Thread] = {}


def emit(job_id: str, event_type: str, payload: dict) -> None:
    with db() as con:
        con.execute(
            "INSERT INTO events(job_id,event_type,payload,created_at) VALUES(?,?,?,?)",
            (job_id, event_type, dump(payload), now()),
        )


def log(job_id: str, message: str) -> None:
    emit(job_id, "stage.log", {"message": f"[{now()[11:19]}] {message}"})


def add_artifact(job: dict, artifact: Artifact) -> str:
    aid = uid("art")
    rel = artifact.path.relative_to(ROOT).as_posix()
    with db() as con:
        con.execute(
            "INSERT INTO artifacts VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (
                aid,
                job["id"],
                job["version_id"],
                artifact.kind,
                artifact.label,
                rel,
                artifact.mime,
                artifact.path.stat().st_size,
                sha256(artifact.path),
                dump(artifact.metadata),
                now(),
            ),
        )
    emit(job["id"], "stage.output", {"artifactId": aid, "type": artifact.kind, "label": artifact.label})
    return aid


def state_for(stage: str) -> str:
    return {
        "intake": "queued",
        "analysis": "generating_geometry",
        "geometry": "generating_geometry",
        "glb_validation": "validating_glb",
        "multi_view_render": "rendering_review",
        "visual_review": "rendering_review",
        "manual_refine": "awaiting_manual_refine",
        "materials": "processing_materials",
        "web_optimization": "optimizing_web",
    }.get(stage, "queued")


class _DbReporter:
    def __init__(self, job: dict):
        self.job = job
        self.job_id = job["id"]

    def log(self, message: str) -> None:
        log(self.job_id, message)

    def should_cancel(self) -> bool:
        with db() as con:
            return bool(con.execute("SELECT cancel_requested FROM jobs WHERE id=?", (self.job_id,)).fetchone()[0])

    def stage_started(self, key: str, label: str) -> None:
        stamp = now()
        with db() as con:
            con.execute("UPDATE stages SET status='running',started_at=? WHERE job_id=? AND stage_key=?", (stamp, self.job_id, key))
            con.execute("UPDATE jobs SET current_stage=? WHERE id=?", (key, self.job_id))
            con.execute("UPDATE projects SET status=?,updated_at=? WHERE id=?", (state_for(key), stamp, self.job["project_id"]))
        emit(self.job_id, "stage.started", {"stage": key, "label": label})
        log(self.job_id, f"开始{label}")

    def stage_completed(self, key: str, warnings: list[str], report_path: Path) -> None:
        rel = report_path.relative_to(ROOT).as_posix()
        with db() as con:
            con.execute("UPDATE stages SET status='passed',completed_at=?,report_path=? WHERE job_id=? AND stage_key=?", (now(), rel, self.job_id, key))
            passed = con.execute("SELECT COUNT(*) FROM stages WHERE job_id=? AND status='passed'", (self.job_id,)).fetchone()[0]
            con.execute("UPDATE projects SET passed_stages=?,updated_at=? WHERE id=?", (passed, now(), self.job["project_id"]))
        emit(self.job_id, "stage.completed", {"stage": key, "status": "passed", "warnings": warnings})

    def artifact(self, artifact: Artifact) -> None:
        add_artifact(self.job, artifact)

    def backend(self, actual_backend: str, model_version: str | None) -> None:
        with db() as con:
            con.execute("UPDATE jobs SET actual_backend=?,model_version=? WHERE id=?", (actual_backend, model_version, self.job_id))
            con.execute("UPDATE projects SET actual_backend=? WHERE id=?", (actual_backend, self.job["project_id"]))


def run(job_id: str) -> None:
    try:
        with db() as con:
            job = dict(con.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone())
            asset = con.execute(
                "SELECT * FROM assets WHERE project_id=? AND role='front' AND active=1 ORDER BY created_at DESC LIMIT 1",
                (job["project_id"],),
            ).fetchone()
            con.execute("UPDATE jobs SET status='running',started_at=? WHERE id=?", (now(), job_id))
        if not asset:
            raise ValueError("缺少活动正面素材")
        source_image = ROOT / asset["storage_path"]
        config = json.loads(job["config_snapshot"])
        version_root = project_dir(job["project_id"]) / "versions" / job["version_id"]

        emit(job_id, "job.status", {"status": "running"})
        log(job_id, "Worker 已领取任务；资源类型 gpu，单任务串行执行")

        reporter = _DbReporter(job)
        result = run_pipeline(
            config=config,
            source_image=source_image,
            version_root=version_root,
            seed=job["seed"],
            reporter=reporter,
            capabilities=capabilities,
            generate_hunyuan=generate_hunyuan,
            generate_sf3d=generate_sf3d,
            generate_triposr=generate_triposr,
            render_blender=render_blender,
            source_meta={"sourceAssetId": asset["id"], "sourceSha256": asset["sha256"]},
        )

        with db() as con:
            con.execute("UPDATE jobs SET status='completed',completed_at=? WHERE id=?", (now(), job_id))
            con.execute(
                "UPDATE projects SET status='ready_for_review',passed_stages=?,total_stages=?,updated_at=? WHERE id=?",
                (len(STAGES), len(STAGES), now(), job["project_id"]),
            )
            con.execute("UPDATE versions SET status='ready_for_review',quality_report=? WHERE id=?", (dump(result.quality), job["version_id"]))
        log(job_id, "全部阶段完成；模型已进入人工验收")
        emit(job_id, "job.completed", {"status": "completed", "versionId": job["version_id"]})
    except CancelledError as exc:
        with db() as con:
            con.execute("UPDATE jobs SET status='cancelled',completed_at=? WHERE id=?", (now(), job_id))
            con.execute("UPDATE projects SET status='cancelled',updated_at=? WHERE current_job_id=?", (now(), job_id))
        log(job_id, str(exc))
        emit(job_id, "job.status", {"status": "cancelled"})
    except Exception as exc:  # noqa: BLE001 - 失败需落库并上报
        with db() as con:
            con.execute("UPDATE jobs SET status='failed',error_code='WORKER_ERROR',error_summary=?,completed_at=? WHERE id=?", (str(exc), now(), job_id))
            con.execute("UPDATE projects SET status='failed',updated_at=? WHERE current_job_id=?", (now(), job_id))
        log(job_id, f"任务失败：{exc}")
        emit(job_id, "stage.failed", {"error": str(exc)})


def launch(job_id: str) -> None:
    t = threading.Thread(target=run, args=(job_id,), daemon=True, name=f"studio-{job_id}")
    _threads[job_id] = t
    t.start()
