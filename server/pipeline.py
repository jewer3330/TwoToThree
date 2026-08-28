"""与存储/进程无关的生成流水线执行器。

把原 worker.py 中的阶段循环抽取出来，通过 ``Reporter`` 回调和注入的 backend
callable 与外部解耦：

  - 本地 worker（worker.py）：``Reporter`` 写入 SQLite 并发出 SSE 事件。
  - 远程 worker（remote_worker.py）：``Reporter`` 通过 HTTP 上报总控。

流水线只操作文件并返回结构化结果，不直接接触数据库或网络。
"""
from __future__ import annotations

import json
import struct
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Protocol

from .backends import BackendError, CancelledError
from .core import now

STAGES = [
    ("intake", "素材接收"),
    ("analysis", "主体分析"),
    ("geometry", "几何生成"),
    ("glb_validation", "GLB 检查"),
    ("multi_view_render", "Blender 标准化与四视图"),
    ("web_optimization", "Web GLB 输出"),
]


@dataclass
class Artifact:
    kind: str
    label: str
    path: Path
    mime: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class PipelineResult:
    actual_backend: str
    model_version: str | None
    artifacts: list[Artifact]
    quality: dict[str, Any]
    stage_results: list[dict[str, Any]]


class Reporter(Protocol):
    def log(self, message: str) -> None: ...
    def should_cancel(self) -> bool: ...
    def stage_started(self, key: str, label: str) -> None: ...
    def stage_completed(self, key: str, warnings: list[str], report_path: Path) -> None: ...
    def artifact(self, artifact: Artifact) -> None: ...
    def backend(self, actual_backend: str, model_version: str | None) -> None: ...


GenerateFn = Callable[[Path, Path, int, str, Callable[[str], None], Callable[[], bool]], dict]
RenderFn = Callable[[Path, Path, Path, Callable[[str], None], Callable[[], bool]], dict]


def glb_info(path: Path) -> dict[str, Any]:
    with path.open("rb") as f:
        head = f.read(12)
    if len(head) != 12 or head[:4] != b"glTF":
        raise ValueError("文件缺少 glTF 二进制文件头")
    version, length = struct.unpack("<II", head[4:])
    actual = path.stat().st_size
    if version != 2:
        raise ValueError(f"不支持的 glTF 版本 {version}")
    if length != actual:
        raise ValueError(f"GLB 声明长度 {length} 与文件长度 {actual} 不一致")
    return {"glbVersion": version, "byteLength": actual, "header": "glTF"}


def _write_report(
    version_root: Path,
    stage: str,
    status: str,
    started: str,
    warnings: list[str],
    next_action: str | None,
) -> Path:
    folder = version_root / "reports"
    folder.mkdir(parents=True, exist_ok=True)
    payload = {
        "schemaVersion": 1,
        "stage": stage,
        "status": status,
        "startedAt": started,
        "completedAt": now(),
        "inputs": [],
        "outputs": [],
        "metrics": {},
        "warnings": warnings or [],
        "error": None,
        "nextAction": next_action,
    }
    path = folder / f"{stage}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _build_quality(web_glb: Path, actual_backend: str | None) -> dict[str, Any]:
    size = f"{web_glb.stat().st_size / 1048576:.2f} MB" if web_glb.exists() else "unknown"
    return {
        "scores": {
            "轮廓匹配": 0,
            "比例一致性": 0,
            "正面可信度": 0,
            "侧面可信度": 0,
            "背面可信度": 0,
        },
        "stats": {"fileSize": size, "backend": actual_backend},
        "differences": [
            {"severity": "info", "message": "自动视觉评分尚未接入；请依据四视图和交互模型人工验收。"}
        ],
        "approximations": [
            {"region": "未提供视角覆盖的隐藏区域", "confidence": 0.5, "note": "单图生成结果需要人工复核"}
        ],
    }


def run_pipeline(
    *,
    config: dict[str, Any],
    source_image: Path,
    version_root: Path,
    seed: int,
    reporter: Reporter,
    capabilities: Callable[[], dict],
    generate_hunyuan: GenerateFn,
    generate_sf3d: GenerateFn,
    generate_triposr: GenerateFn,
    render_blender: RenderFn,
    source_meta: dict[str, Any] | None = None,
) -> PipelineResult:
    actual_backend: str | None = None
    model_version: str | None = None
    artifacts: list[Artifact] = []
    stage_results: list[dict[str, Any]] = []
    web_glb = version_root / "models" / "web.glb"

    for index, (key, label) in enumerate(STAGES):
        if reporter.should_cancel():
            raise CancelledError("收到取消信号；保留所有已生成产物")
        started = now()
        reporter.stage_started(key, label)
        time.sleep(0.22)
        warnings: list[str] = []

        if key == "geometry":
            out = version_root / "models" / "baseline.glb"
            out.parent.mkdir(parents=True, exist_ok=True)
            requested = [config.get("primaryBackend", "hunyuan3d"), *config.get("fallbackBackends", ["sf3d", "triposr"])]
            available = capabilities()
            errors: list[str] = []
            result: dict[str, Any] | None = None
            for backend in dict.fromkeys(requested):
                if not available.get(backend):
                    errors.append(f"{backend}: environment unavailable")
                    continue
                try:
                    if backend == "hunyuan3d":
                        result = generate_hunyuan(
                            source_image, out, seed, config.get("geometryQuality", "standard"),
                            reporter.log, reporter.should_cancel,
                        )
                    elif backend == "sf3d":
                        result = generate_sf3d(
                            source_image, out, config.get("textureResolution", 2048),
                            reporter.log, reporter.should_cancel,
                        )
                    elif backend == "triposr":
                        result = generate_triposr(source_image, out, reporter.log, reporter.should_cancel)
                    if result:
                        break
                except CancelledError:
                    raise
                except Exception as exc:  # noqa: BLE001 - 逐后端降级
                    errors.append(f"{backend}: {exc}")
                    warnings.append(f"{backend}-failed")
                    reporter.log(f"{backend} 失败，准备降级：{exc}")
            if not result:
                raise BackendError("所有生成后端失败：" + "; ".join(errors))
            actual_backend = result["backend"]
            model_version = result.get("modelVersion")
            reporter.backend(actual_backend, model_version)
            metadata: dict[str, Any] = {**result, "preservedBaseline": True}
            if source_meta:
                metadata.update(source_meta)
            artifact = Artifact("glb", "baseline.glb", out, "model/gltf-binary", metadata)
            artifacts.append(artifact)
            reporter.artifact(artifact)

        elif key == "glb_validation":
            out = version_root / "models" / "baseline.glb"
            info = glb_info(out)
            reporter.log(f"GLB 文件头通过：glTF v{info['glbVersion']}，{info['byteLength']} bytes")

        elif key == "multi_view_render":
            baseline = version_root / "models" / "baseline.glb"
            outdir = version_root / "renders"
            outdir.mkdir(parents=True, exist_ok=True)
            render_sources = render_blender(baseline, outdir, web_glb, reporter.log, reporter.should_cancel)
            web_artifact = Artifact(
                "glb", "web.glb", web_glb, "model/gltf-binary",
                {"backend": actual_backend, "normalizedBy": "Blender 5.2", "source": "baseline.glb"},
            )
            artifacts.append(web_artifact)
            reporter.artifact(web_artifact)
            for view, source in render_sources.items():
                render = Artifact("render", view, source, "image/png", {"view": view, "renderer": "Blender 5.2"})
                artifacts.append(render)
                reporter.artifact(render)

        report_path = _write_report(
            version_root, key, "passed", started, warnings,
            next_action=STAGES[index + 1][0] if index + 1 < len(STAGES) else "ready_for_review",
        )
        reporter.stage_completed(key, warnings, report_path)
        stage_results.append(
            {"key": key, "label": label, "status": "passed", "warnings": warnings, "reportPath": report_path}
        )

    return PipelineResult(
        actual_backend=actual_backend or "",
        model_version=model_version,
        artifacts=artifacts,
        quality=_build_quality(web_glb, actual_backend),
        stage_results=stage_results,
    )
