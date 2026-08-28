"""部署配置：三节点架构（总控 + OSS + 显卡机）。

数据路径沿用 ``studio_paths``（STUDIO_EXTERNAL_ROOT 可覆盖），本模块只负责
部署相关的环境变量：worker 模式、OSS、鉴权、后端可执行路径（env 覆盖）。

未配置时保持单机行为不变。
"""
from __future__ import annotations

import os
from pathlib import Path

from studio_paths import LOCAL_ROOT


def _env(name: str, default: str | None = None) -> str | None:
    value = os.environ.get(name)
    return value if value not in (None, "") else default


# --------------------------------------------------------------------------- #
# Worker 模式与鉴权
# --------------------------------------------------------------------------- #
WORKER_MODE = (_env("WORKER_MODE", "local") or "local").strip().lower()  # local | remote
WORKER_TOKEN = _env("WORKER_TOKEN", "")
CONTROL_URL = (_env("CONTROL_URL", "") or "").rstrip("/")
WORK_DIR = _env("WORK_DIR", str(Path.home() / ".studio-worker"))
POLL_INTERVAL = float(_env("POLL_INTERVAL", "5") or "5")
CONTROL_TIMEOUT = float(_env("CONTROL_TIMEOUT", "30") or "30")


# --------------------------------------------------------------------------- #
# OSS（共享存储 / 交换层）
# --------------------------------------------------------------------------- #
OSS_ENDPOINT = _env("OSS_ENDPOINT", "oss-cn-shanghai.aliyuncs.com")
OSS_BUCKET = _env("OSS_BUCKET", "")
OSS_ACCESS_KEY_ID = _env("OSS_ACCESS_KEY_ID", "")
OSS_ACCESS_KEY_SECRET = _env("OSS_ACCESS_KEY_SECRET", "")
OSS_PREFIX = (_env("OSS_PREFIX", "two-to-three") or "").strip("/")
OSS_URL_EXPIRES = int(_env("OSS_URL_EXPIRES", "3600") or "3600")


# --------------------------------------------------------------------------- #
# 后端可执行文件路径（env 覆盖 studio_paths 默认值；默认兼容 Windows/Linux 探测）
# --------------------------------------------------------------------------- #
def _hunyuan_py() -> str:
    for candidate in (LOCAL_ROOT / "hunyuan-bootstrap" / "Scripts" / "python.exe",
                      LOCAL_ROOT / "hunyuan-bootstrap" / "bin" / "python",
                      LOCAL_ROOT / "hunyuan-bootstrap" / "bin" / "python3"):
        if candidate.exists():
            return str(candidate)
    return str(LOCAL_ROOT / "hunyuan-bootstrap" / "bin" / "python")


def _blender() -> str:
    for candidate in (LOCAL_ROOT / "Blender52" / "blender.exe",
                      LOCAL_ROOT / "blender" / "blender"):
        if candidate.exists():
            return str(candidate)
    return _env("BLENDER", "blender") or "blender"


HUNYUAN_PY = _env("HUNYUAN_PY", _hunyuan_py())
HUNYUAN_MODEL = _env("HUNYUAN_MODEL", str(LOCAL_ROOT / "Hunyuan3D-2.1-model"))
HUNYUAN_RUNNER = _env("HUNYUAN_RUNNER", str(Path(__file__).resolve().parents[1] / "pipeline" / "run_hunyuan_yoyo.py"))
HUNYUAN_MV_MODEL = _env("HUNYUAN_MV_MODEL", str(LOCAL_ROOT / "Hunyuan3D-2mv-model-v2"))
HUNYUAN_MV_RUNNER = _env("HUNYUAN_MV_RUNNER", str(Path(__file__).resolve().parents[1] / "pipeline" / "run_hunyuan_multiview.py"))

SF3D_PY = _env("SF3D_PY", str(LOCAL_ROOT / "stable-fast-3d" / ".venv-runtime" / "Scripts" / "python.exe"))
SF3D_REPO = _env("SF3D_REPO", str(LOCAL_ROOT / "stable-fast-3d"))
TRIPOSR_PY = _env("TRIPOSR_PY", str(LOCAL_ROOT / "TripoSR" / ".venv-runtime" / "Scripts" / "python.exe"))
TRIPOSR_REPO = _env("TRIPOSR_REPO", str(LOCAL_ROOT / "TripoSR"))

BLENDER = _env("BLENDER", _blender())
BLENDER_RENDERER = _env("BLENDER_RENDERER", str(Path(__file__).resolve().parents[1] / "pipeline" / "blender_render_job.py"))
BLENDER_REFINER = _env("BLENDER_REFINER", str(Path(__file__).resolve().parents[1] / "pipeline" / "blender_auto_refine.py"))
BLENDER_STL_EXPORTER = _env("BLENDER_STL_EXPORTER", str(Path(__file__).resolve().parents[1] / "pipeline" / "blender_export_stl.py"))
