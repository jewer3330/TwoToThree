"""与存储/网络无关的几何生成流水线执行器。

把 worker.py 中 geometry → glb_validation → multi_view_render 的推理逻辑抽出，
通过 ``Reporter`` 回调与外部解耦：

  - 本地 worker：``Reporter`` 写 SQLite 并发 SSE 事件。
  - 远程 worker：``Reporter`` 通过 HTTP 上报总控。

流水线只操作文件并返回结构化结果（产物列表 + 几何指标 + 质量报告），
不直接接触数据库或网络。
"""
from __future__ import annotations

import json
import math
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
    geometry_metrics: dict[str, Any] | None
    awaiting_geometry_confirmation: bool


class Reporter(Protocol):
    def log(self, message: str) -> None: ...
    def should_cancel(self) -> bool: ...
    def stage_started(self, key: str, label: str) -> None: ...
    def stage_completed(self, key: str, warnings: list[str]) -> None: ...
    def backend(self, actual_backend: str, model_version: str | None) -> None: ...


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


def glb_geometry_metrics(path: Path) -> dict[str, Any]:
    """Use robust POSITION percentiles so isolated outlier vertices cannot hide a flat mesh."""
    raw = path.read_bytes()
    offset = 12
    doc = None
    binary = b""
    while offset + 8 <= len(raw):
        length, kind = struct.unpack_from("<II", raw, offset)
        payload = raw[offset + 8:offset + 8 + length]
        offset += 8 + length
        if kind == 0x4E4F534A:
            doc = json.loads(payload.rstrip(b"\x00 ").decode("utf-8"))
        elif kind == 0x004E4942:
            binary = payload
    if not doc or not binary:
        raise ValueError("GLB 缺少 JSON 或 BIN 数据块")
    axes = [[], [], []]
    formats = {5126: ("f", 4), 5123: ("H", 2), 5125: ("I", 4), 5121: ("B", 1), 5122: ("h", 2)}
    for mesh in doc.get("meshes", []):
        for primitive in mesh.get("primitives", []):
            index = primitive.get("attributes", {}).get("POSITION")
            if index is None:
                continue
            accessor = doc["accessors"][index]
            view = doc["bufferViews"][accessor["bufferView"]]
            fmt, size = formats[accessor["componentType"]]
            start = view.get("byteOffset", 0) + accessor.get("byteOffset", 0)
            stride = view.get("byteStride", size * 3)
            for i in range(accessor["count"]):
                xyz = struct.unpack_from("<" + fmt * 3, binary, start + i * stride)
                for axis, value in enumerate(xyz):
                    axes[axis].append(float(value))
    if not axes[0]:
        raise ValueError("GLB 没有 POSITION 顶点数据")

    def q(values, p):
        values.sort()
        index = (len(values) - 1) * p
        lo = math.floor(index)
        hi = math.ceil(index)
        return values[lo] if lo == hi else values[lo] * (hi - index) + values[hi] * (index - lo)

    robust = [q(v, .95) - q(v, .05) for v in axes]
    ordered = sorted(robust)
    ratio = ordered[0] / max(ordered[-1], 1e-9)
    return {
        "vertexCount": len(axes[0]),
        "robustDimensions": {"x": robust[0], "y": robust[1], "z": robust[2]},
        "thinAxisRatio": ratio,
        "flat": ratio < .08,
    }


def _write_report(version_root: Path, stage: str, started: str, warnings: list[str], next_action: str | None) -> Path:
    folder = version_root / "reports"
    folder.mkdir(parents=True, exist_ok=True)
    payload = {
        "schemaVersion": 1, "stage": stage, "status": "passed", "startedAt": started,
        "completedAt": now(), "inputs": [], "outputs": [], "metrics": {},
        "warnings": warnings or [], "error": None, "nextAction": next_action,
    }
    path = folder / f"{stage}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _build_quality(web_glb: Path, actual_backend: str | None) -> dict[str, Any]:
    size = f"{web_glb.stat().st_size / 1048576:.2f} MB" if web_glb.exists() else "unknown"
    return {
        "scores": {"轮廓匹配": 0, "比例一致性": 0, "正面可信度": 0, "侧面可信度": 0, "背面可信度": 0},
        "stats": {"fileSize": size, "backend": actual_backend},
        "differences": [{"severity": "info", "message": "自动视觉评分尚未接入；请依据四视图和交互模型人工验收。"}],
        "approximations": [{"region": "未提供视角覆盖的隐藏区域", "confidence": 0.5, "note": "单图生成结果需要人工复核"}],
    }


def run_geometry_pipeline(
    *,
    config: dict[str, Any],
    source_images: dict[str, Path],
    version_root: Path,
    seed: int,
    subject_type: str,
    reporter: Reporter,
    capabilities: Callable[[], dict],
    generate_hunyuan,
    generate_hunyuan_multiview,
    generate_sf3d,
    generate_triposr,
    render_blender,
) -> PipelineResult:
    actual_backend: str | None = None
    model_version: str | None = None
    artifacts: list[Artifact] = []
    geometry_metrics: dict[str, Any] | None = None
    web_glb = version_root / "models" / "web.glb"
    front = source_images.get("front")

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
            multi = len(source_images) > 1
            for backend in dict.fromkeys(requested):
                if multi and backend != "hunyuan3d":
                    errors.append(f"{backend}: multi-view unsupported; fallback refused")
                    continue
                if multi and backend == "hunyuan3d" and not available.get("hunyuan3dMultiview"):
                    errors.append("hunyuan3d: Hunyuan3D-2mv environment unavailable")
                    continue
                if not available.get(backend):
                    errors.append(f"{backend}: environment unavailable")
                    continue
                try:
                    if backend == "hunyuan3d":
                        if multi:
                            result = generate_hunyuan_multiview(
                                source_images, out, seed, config.get("geometryQuality", "standard"),
                                config.get("viewWeights", {"front": 1.8, "side": 1.0, "back": 0.7}),
                                reporter.log, reporter.should_cancel,
                                config.get("visualConditioning"), config.get("modelStyle", "realistic"),
                            )
                        else:
                            result = generate_hunyuan(
                                front, out, seed, config.get("geometryQuality", "standard"),
                                reporter.log, reporter.should_cancel,
                            )
                    elif backend == "sf3d":
                        result = generate_sf3d(front, out, config.get("textureResolution", 2048), reporter.log, reporter.should_cancel)
                    elif backend == "triposr":
                        result = generate_triposr(front, out, reporter.log, reporter.should_cancel)
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
            artifacts.append(Artifact("glb", "baseline.glb", out, "model/gltf-binary", {**result, "preservedBaseline": True}))
            processed = Path(result["processedImage"]) if result.get("processedImage") else None
            if processed and processed.exists():
                artifacts.append(Artifact("condition-image", "实际送入 Hunyuan 的裁边图", processed, "image/png", {"role": "front", "backgroundRemoved": True, "foregroundCropped": True}))
            for role, path_text in result.get("processedImages", {}).items():
                path = Path(path_text)
                if path.exists():
                    artifacts.append(Artifact("condition-image", f"实际送入 Hunyuan3D-2mv：{role}", path, "image/png", {"role": role, "backgroundRemoved": True, "foregroundCropped": True, "multiView": True}))
            for role, variants in result.get("visualCandidates", {}).items():
                for variant, path_text in variants.items():
                    path = Path(path_text)
                    if path.exists():
                        artifacts.append(Artifact("visual-condition", f"{role} · {variant}", path, "image/png", {"role": role, "variant": variant, "selected": variant == result.get("visualConditioning", {}).get("selectedMode"), "experimental": variant == "depth-cue-experimental"}))
            visual_report = Path(result["visualConditioningReport"]) if result.get("visualConditioningReport") else None
            if visual_report and visual_report.exists():
                artifacts.append(Artifact("quality_report", "三视图视觉增强报告", visual_report, "application/json", {"selectedMode": result.get("visualConditioning", {}).get("selectedMode")}))

        elif key == "glb_validation":
            baseline = version_root / "models" / "baseline.glb"
            metrics = glb_geometry_metrics(baseline)
            geometry_metrics = metrics
            reporter.log(f"稳健包围尺寸={metrics['robustDimensions']}；厚度比={metrics['thinAxisRatio']:.4f}")
            if metrics["flat"] and subject_type in ("character", "hybrid"):
                raise BackendError(f"模型厚度质量门禁未通过：thinAxisRatio={metrics['thinAxisRatio']:.4f} < 0.08。该角色模型接近薄片，禁止进入预览评审。")
            info = glb_info(baseline)
            reporter.log(f"GLB 文件头通过：glTF v{info['glbVersion']}，{info['byteLength']} bytes")

        elif key == "multi_view_render":
            baseline = version_root / "models" / "baseline.glb"
            outdir = version_root / "renders"
            outdir.mkdir(parents=True, exist_ok=True)
            quality = config.get("geometryQuality", "standard")
            texture_resolution = 0 if quality == "standard" else (4096 if quality == "ultra" else 2048)
            processed_dir = version_root / "models" / "multiview-conditions"
            references = {"front": processed_dir / "condition-front.png", "side": processed_dir / "condition-left.png", "back": processed_dir / "condition-back.png"}
            if not references["front"].exists():
                references = {"front": version_root / "models" / "condition-front.png"}
            style = config.get("stylePreset", {"id": config.get("modelStyle", "realistic"), "depthScale": 1.0})
            render_sources = render_blender(baseline, outdir, web_glb, reporter.log, reporter.should_cancel, quality, texture_resolution, references, style)
            artifacts.append(Artifact("glb", "web.glb", web_glb, "model/gltf-binary", {"backend": actual_backend, "normalizedBy": "Blender 5.2", "source": "baseline.glb", "quality": quality, "modelStyle": style.get("id", "realistic"), "styleFeaturePrompt": style.get("featurePrompt", ""), "depthScale": style.get("depthScale", 1.0), "geometryResolution": {"standard": 256, "high": 384, "ultra": 512}[quality], "textureResolution": texture_resolution or None, "faceRefinement": quality == "ultra"}))
            for view, source in render_sources.items():
                artifacts.append(Artifact("render", view, source, "image/png", {"view": view, "renderer": "Blender 5.2"}))
            for texture in sorted((outdir / "textures").glob("*.png")):
                artifacts.append(Artifact("texture", texture.name, texture, "image/png", {"resolution": texture_resolution, "projection": "multi-view", "embeddedIn": "web.glb"}))

        _write_report(version_root, key, started, warnings, next_action=STAGES[index + 1][0] if index + 1 < len(STAGES) else "ready_for_review")
        reporter.stage_completed(key, warnings)

        if key == "multi_view_render":
            # 几何确认中间态：等待用户确认后再进入后续（web_optimization 为空操作，本地标记即可）
            return PipelineResult(
                actual_backend=actual_backend or "",
                model_version=model_version,
                artifacts=artifacts,
                quality=_build_quality(web_glb, actual_backend),
                geometry_metrics=geometry_metrics,
                awaiting_geometry_confirmation=True,
            )

    return PipelineResult(
        actual_backend=actual_backend or "",
        model_version=model_version,
        artifacts=artifacts,
        quality=_build_quality(web_glb, actual_backend),
        geometry_metrics=geometry_metrics,
        awaiting_geometry_confirmation=False,
    )
