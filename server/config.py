"""运行时配置，全部来自环境变量；未配置时回退到单机/Windows 默认行为。

总控 + OSS + 显卡机器 三节点架构的关键变量：
  - OSS_*：阿里云对象存储凭据与端点，配置后才启用 OSS 交换层。
  - WORKER_MODE：local（默认，进程内线程跑流水线）或 remote（任务停在 queued 等远端 worker）。
  - WORKER_TOKEN：总控与显卡机之间鉴权令牌。
  - CONTROL_URL：显卡机上的远端 worker 指向总控地址。
  - HUNYUAN_*/BLENDER/SF3D_*/TRIPOSR_*：各后端可执行文件/权重路径，允许覆盖默认探测值。
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _env(name: str, default: str | None = None) -> str | None:
    value = os.environ.get(name)
    return value if value not in (None, "") else default


# --------------------------------------------------------------------------- #
# OSS（共享存储 / 交换层）
# --------------------------------------------------------------------------- #
OSS_ENDPOINT = _env("OSS_ENDPOINT", "oss-cn-shanghai.aliyuncs.com")
# 控制面与 OSS 同地域时走内网端点上传/校验，浏览器签名仍使用公网端点。
OSS_INTERNAL_ENDPOINT = _env("OSS_INTERNAL_ENDPOINT", "")
OSS_PUBLIC_ENDPOINT = _env("OSS_PUBLIC_ENDPOINT", "")
OSS_BUCKET = _env("OSS_BUCKET", "")
OSS_ACCESS_KEY_ID = _env("OSS_ACCESS_KEY_ID", "")
OSS_ACCESS_KEY_SECRET = _env("OSS_ACCESS_KEY_SECRET", "")
# 所有对象键的统一前缀，便于在一个 bucket 内隔离多个环境。
OSS_PREFIX = (_env("OSS_PREFIX", "two-to-three") or "").strip("/")
# 签名 URL 有效期（秒）。
OSS_URL_EXPIRES = int(_env("OSS_URL_EXPIRES", "3600") or "3600")
# 浏览器下载使用更短的签名，API 每次访问时按权限即时生成。
OSS_DOWNLOAD_EXPIRES = int(_env("OSS_DOWNLOAD_EXPIRES", "600") or "600")
# 最终制品使用内容寻址键，和 GPU 临时交换对象分开。
OSS_ARTIFACT_PREFIX = (_env("OSS_ARTIFACT_PREFIX", "artifacts") or "artifacts").strip("/")


# --------------------------------------------------------------------------- #
# Worker 模式与鉴权
# --------------------------------------------------------------------------- #
WORKER_MODE = (_env("WORKER_MODE", "local") or "local").strip().lower()  # local | remote
WORKER_TOKEN = _env("WORKER_TOKEN", "")
# 显卡机上的远端 worker 使用，指向总控的 API 根地址（例如 http://8.153.36.240:8000）。
CONTROL_URL = (_env("CONTROL_URL", "") or "").rstrip("/")
# 远端 worker 本地工作目录（下载输入、运行流水线的临时空间）。
WORK_DIR = _env("WORK_DIR", str(ROOT / "data" / "worker"))
# 无任务时的轮询间隔（秒）。
POLL_INTERVAL = float(_env("POLL_INTERVAL", "5") or "5")
# 调用总控接口的超时（秒）。
CONTROL_TIMEOUT = float(_env("CONTROL_TIMEOUT", "30") or "30")


# --------------------------------------------------------------------------- #
# AutoDL（显卡机自动启停，作为 GPU 集群 provider=autodl 节点）
# --------------------------------------------------------------------------- #
AUTODL_TOKEN = _env("AUTODL_TOKEN", "")
AUTODL_INSTANCE_UUID = _env("AUTODL_INSTANCE_UUID", "")
# 显卡机空闲多少秒后自动关机（0 = 禁用自动关机）
AUTODL_IDLE_TIMEOUT = float(_env("AUTODL_IDLE_TIMEOUT", "900") or "0")
# 总控 autostart 轮询间隔（秒，AutoDL 生命周期检查并入调度器后仅作参考）
AUTOSTART_POLL_INTERVAL = float(_env("AUTOSTART_POLL_INTERVAL", "15") or "15")
# 开机后 worker 启动命令（可选，覆盖 AutoDL 创建实例时设置）
AUTODL_START_COMMAND = _env("AUTODL_START_COMMAND", "")
# 节点注册信息（SSH 访问 AutoDL 实例）
AUTODL_NAME = _env("AUTODL_NAME", "AutoDL-GPU")
AUTODL_HOST = _env("AUTODL_HOST", "")          # AutoDL 实例 SSH 地址 host:port
AUTODL_SSH_USER = _env("AUTODL_SSH_USER", "root")
AUTODL_SSH_KEY = _env("AUTODL_SSH_KEY", "")
AUTODL_REPO_ROOT = _env("AUTODL_REPO_ROOT", "")  # 远端仓库目录（含 pipeline/server）
AUTODL_EXT_ROOT = _env("AUTODL_EXT_ROOT", "")    # 远端本地环境根（python/权重/Blender 所在）
AUTODL_WORK_DIR = _env("AUTODL_WORK_DIR", "")


# --------------------------------------------------------------------------- #
# 传输层（可插拔：OSS 对象存储 / CDN+scp 节点直传）
# --------------------------------------------------------------------------- #
# auto = 配了 OSS 凭据用 OSS，否则 CDN+scp；oss = 强制对象存储；cdn = 强制 CDN+scp
STORAGE_BACKEND = (_env("STORAGE_BACKEND", "auto") or "auto").strip().lower()


# --------------------------------------------------------------------------- #
# 后端可执行文件 / 权重路径（Windows 与 Linux 自动探测，env 优先）
# --------------------------------------------------------------------------- #
def _default_hunyuan_py() -> str:
    base = ROOT / ".local" / "hunyuan-bootstrap"
    for candidate in (base / "Scripts" / "python.exe", base / "bin" / "python", base / "bin" / "python3"):
        if candidate.exists():
            return str(candidate)
    return str(base / "Scripts" / "python.exe")


def _default_blender() -> str:
    windows = ROOT / ".local" / "Blender52" / "blender.exe"
    if windows.exists():
        return str(windows)
    linux = ROOT / ".local" / "blender" / "blender"
    if linux.exists():
        return str(linux)
    which = shutil.which("blender")
    return which or "blender"


HUNYUAN_PY = _env("HUNYUAN_PY", _default_hunyuan_py())
HUNYUAN_MODEL = _env("HUNYUAN_MODEL", str(ROOT / ".local" / "Hunyuan3D-2.1-model"))
HUNYUAN_RUNNER = _env("HUNYUAN_RUNNER", str(ROOT / "pipeline" / "run_hunyuan_yoyo.py"))

SF3D_PY = _env("SF3D_PY", str(ROOT / ".local" / "stable-fast-3d" / ".venv-runtime" / "Scripts" / "python.exe"))
SF3D_REPO = _env("SF3D_REPO", str(ROOT / ".local" / "stable-fast-3d"))
TRIPOSR_PY = _env("TRIPOSR_PY", str(ROOT / ".local" / "TripoSR" / ".venv-runtime" / "Scripts" / "python.exe"))
TRIPOSR_REPO = _env("TRIPOSR_REPO", str(ROOT / ".local" / "TripoSR"))

BLENDER = _env("BLENDER", _default_blender())
BLENDER_RENDERER = _env("BLENDER_RENDERER", str(ROOT / "pipeline" / "blender_render_job.py"))
BLENDER_REFINER = _env("BLENDER_REFINER", str(ROOT / "pipeline" / "blender_auto_refine.py"))


def backend_paths() -> dict[str, str]:
    """汇总后端路径，便于日志与诊断。"""
    return {
        "hunyuanPy": HUNYUAN_PY,
        "hunyuanModel": HUNYUAN_MODEL,
        "hunyuanRunner": HUNYUAN_RUNNER,
        "sf3dPy": SF3D_PY,
        "sf3dRepo": SF3D_REPO,
        "triposrPy": TRIPOSR_PY,
        "triposrRepo": TRIPOSR_REPO,
        "blender": BLENDER,
        "blenderRenderer": BLENDER_RENDERER,
        "blenderRefiner": BLENDER_REFINER,
    }
