"""各生成/渲染后端的子进程适配器。

可执行文件与权重路径统一从 ``server.config`` 读取（环境变量可覆盖），
默认自动探测 Windows 与 Linux 布局，函数签名保持不变。
"""
from __future__ import annotations

import os
import subprocess
import threading
import time
from pathlib import Path
from typing import Callable

from . import config
from .core import ROOT


class BackendError(RuntimeError):
    pass


class CancelledError(RuntimeError):
    pass


def capabilities() -> dict[str, bool]:
    return {
        "hunyuan3d": Path(config.HUNYUAN_PY).exists()
        and Path(config.HUNYUAN_RUNNER).exists()
        and Path(config.HUNYUAN_MODEL).exists(),
        "sf3d": Path(config.SF3D_PY).exists() and (Path(config.SF3D_REPO) / "run.py").exists(),
        "triposr": Path(config.TRIPOSR_PY).exists() and (Path(config.TRIPOSR_REPO) / "run.py").exists(),
        "blender": Path(config.BLENDER).exists() and Path(config.BLENDER_RENDERER).exists(),
        "blenderRefinement": Path(config.BLENDER).exists() and Path(config.BLENDER_REFINER).exists(),
    }


def run_process(
    command: list[str],
    cwd: Path,
    log: Callable[[str], None],
    cancelled: Callable[[], bool],
    env: dict | None = None,
    timeout: int = 3600,
) -> None:
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    process = subprocess.Popen(
        command,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
        env=env or os.environ.copy(),
        creationflags=creationflags,
    )
    deadline = time.monotonic() + timeout

    def pump() -> None:
        assert process.stdout
        for line in process.stdout:
            line = line.strip()
            if line and ("%|" not in line or "100%" in line):
                log(line[-1000:])

    reader = threading.Thread(target=pump, daemon=True)
    reader.start()
    while process.poll() is None:
        if cancelled():
            process.terminate()
            try:
                process.wait(10)
            except subprocess.TimeoutExpired:
                process.kill()
            raise CancelledError("任务已取消，推理子进程已终止")
        if time.monotonic() > deadline:
            process.kill()
            raise BackendError(f"命令超过 {timeout} 秒超时")
        time.sleep(0.25)
    reader.join(timeout=2)
    if process.returncode:
        raise BackendError(f"命令退出码 {process.returncode}")


def generate_hunyuan(image: Path, output: Path, seed: int, quality: str, log, cancelled) -> dict:
    steps = {"standard": 20, "high": 30, "ultra": 40}.get(quality, 20)
    resolution = 256 if quality != "ultra" else 384
    command = [
        config.HUNYUAN_PY,
        config.HUNYUAN_RUNNER,
        "--image", str(image),
        "--model", config.HUNYUAN_MODEL,
        "--output", str(output),
        "--steps", str(steps),
        "--resolution", str(resolution),
        "--seed", str(seed),
    ]
    log(f"Hunyuan3D 2.1 启动：steps={steps}, octree={resolution}, seed={seed}")
    run_process(command, ROOT, log, cancelled, timeout=2400)
    if not output.exists():
        raise BackendError("Hunyuan3D 未生成 GLB")
    return {
        "backend": "hunyuan3d",
        "modelVersion": "tencent/Hunyuan3D-2.1",
        "steps": steps,
        "resolution": resolution,
        "seed": seed,
        "command": [Path(x).name if i < 2 else x for i, x in enumerate(command)],
    }


def generate_sf3d(image: Path, output: Path, texture_resolution: int, log, cancelled) -> dict:
    staging = output.parent / "sf3d-output"
    staging.mkdir(parents=True, exist_ok=True)
    command = [
        config.SF3D_PY, "run.py", str(image),
        "--output-dir", str(staging),
        "--texture-resolution", str(texture_resolution),
        "--remesh_option", "none",
        "--target_vertex_count", "-1",
    ]
    log(f"Stable Fast 3D 启动：texture={texture_resolution}")
    run_process(command, Path(config.SF3D_REPO), log, cancelled, timeout=1200)
    candidates = sorted(staging.rglob("mesh.glb"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not candidates:
        raise BackendError("SF3D 未生成 mesh.glb")
    output.write_bytes(candidates[0].read_bytes())
    return {"backend": "sf3d", "modelVersion": "stabilityai/stable-fast-3d", "textureResolution": texture_resolution}


def generate_triposr(image: Path, output: Path, log, cancelled) -> dict:
    staging = output.parent / "triposr-output"
    staging.mkdir(parents=True, exist_ok=True)
    command = [
        config.TRIPOSR_PY, "run.py", str(image),
        "--output-dir", str(staging),
        "--model-save-format", "glb",
    ]
    log("TripoSR 启动")
    run_process(command, Path(config.TRIPOSR_REPO), log, cancelled, timeout=1200)
    candidates = sorted(staging.rglob("*.glb"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not candidates:
        raise BackendError("TripoSR 未生成 GLB")
    output.write_bytes(candidates[0].read_bytes())
    return {"backend": "triposr", "modelVersion": "stabilityai/TripoSR"}


def render_blender(source: Path, output_dir: Path, web_glb: Path, log, cancelled) -> dict:
    command = [
        config.BLENDER, "--background", "--factory-startup", "--python", config.BLENDER_RENDERER,
        "--", "--input", str(source), "--output-dir", str(output_dir), "--web-glb", str(web_glb),
    ]
    log("Blender 5.2 后台四视图渲染启动")
    run_process(command, ROOT, log, cancelled, timeout=900)
    expected = {v: output_dir / f"{v}.png" for v in ("front", "left-three-quarter", "side", "back")}
    missing = [v for v, p in expected.items() if not p.exists()]
    if missing or not web_glb.exists():
        raise BackendError(f"Blender 产物不完整：{missing}")
    return expected


def refine_blender(
    source: Path,
    output_dir: Path,
    config_path: Path,
    log,
    cancelled,
    reference_image: Path | None = None,
) -> dict:
    command = [
        config.BLENDER, "--background", "--factory-startup", "--python", config.BLENDER_REFINER,
        "--", "--input", str(source), "--output-dir", str(output_dir), "--config", str(config_path),
    ]
    if reference_image:
        command.extend(["--reference-image", str(reference_image)])
    log("启动真实 Blender 后台自动精修")
    run_process(command, ROOT, log, cancelled, timeout=1800)
    report = output_dir / "quality-report.json"
    if not report.exists():
        raise BackendError("Blender 未生成质量报告")
    import json

    result = json.loads(report.read_text(encoding="utf-8"))
    if not (output_dir / "refined.glb").exists():
        raise BackendError("Blender 未生成 refined.glb")
    return result
