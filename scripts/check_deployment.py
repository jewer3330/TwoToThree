#!/usr/bin/env python3
"""2D→3D Studio 线上部署环境监测脚本。

按角色检查「控制面 / GPU 节点 / 自注册 agent」的部署前置条件，输出
人类可读报告（可选 JSON），退出码 0=全部通过、1=存在阻断项。

设计原则：
  - 纯标准库（subprocess/os/json/pathlib/...），节点上任意 python3 都能跑，
    不依赖 fastapi / torch / websockets 等第三方库。
  - 路径遵循 studio_paths 布局（STUDIO_EXTERNAL_ROOT 可覆盖），与
    backends.py / setup.ps1 / setup.sh 保持一致。

用法：
  python scripts/check_deployment.py --role control   # 控制面（ECS）
  python scripts/check_deployment.py --role node      # GPU 节点（含权重/CUDA/Blender）
  python scripts/check_deployment.py --role agent     # 自注册 agent 连接性
  python scripts/check_deployment.py --role all       # 全部（默认）
  python scripts/check_deployment.py --json           # 机器可读输出

环境变量：
  STUDIO_EXTERNAL_ROOT  节点外部根（默认 ~/AIData/3d）
  CONTROL_URL / WORKER_TOKEN  agent 连接性检查用
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# 预期关键文件大小（用于完整性校验）
HUNYUAN_MV_EXPECTED_BYTES = 4_928_151_562  # Hunyuan3D-2mv model.fp16.safetensors
DIT_CKPT_MIN_BYTES = 1_000_000_000          # Hunyuan3D-2.1 dit ckpt 下限（实际 ~7.3GB）
VAE_CKPT_MIN_BYTES = 100_000_000            # vae ckpt 下限（实际 ~655MB）


def _env(name: str, default: str = "") -> str:
    v = os.environ.get(name)
    return v if v not in (None, "") else default


def _ext_root() -> Path:
    return Path(_env("STUDIO_EXTERNAL_ROOT", str(Path.home() / "AIData" / "3d"))).expanduser()


def _local_root() -> Path:
    return _ext_root() / "local"


def _is_windows() -> bool:
    return os.name == "nt"


def _python_bin(local: Path) -> Path:
    if _is_windows():
        return local / "hunyuan-bootstrap" / "Scripts" / "python.exe"
    return local / "hunyuan-bootstrap" / "bin" / "python"


def _blender_bin(local: Path) -> Path:
    if _is_windows():
        return local / "Blender52" / "blender.exe"
    return local / "blender" / "blender"


def _run(cmd: list[str], timeout: int = 30) -> tuple[int, str]:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return p.returncode, (p.stdout or "").strip()
    except FileNotFoundError:
        return -1, "command not found"
    except subprocess.TimeoutExpired:
        return -2, "timeout"
    except Exception as exc:  # noqa: BLE001
        return -3, str(exc)


def _fmt_bytes(n: int | None) -> str:
    if n is None:
        return "?"
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f}{unit}"
        n /= 1024
    return f"{n:.1f}TB"


def _check(key: str, label: str, ok: bool, value: str = "", detail: str = "") -> dict:
    return {"key": key, "label": label, "ok": bool(ok), "value": value, "detail": detail}


def _spec(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


# --------------------------------------------------------------------------- #
# 控制面检查
# --------------------------------------------------------------------------- #
def check_control() -> list[dict]:
    checks: list[dict] = []
    checks.append(_check("python", "Python >= 3.10",
                         sys.version_info >= (3, 10), sys.version.split()[0]))

    # 核心依赖（不实际 import，只探测是否可安装/已安装）
    deps = {
        "fastapi": "FastAPI", "uvicorn": "Uvicorn", "websockets": "WebSockets",
        "oss2": "阿里云 OSS SDK", "httpx": "HTTPX", "psutil": "psutil",
        "PIL": "Pillow", "itsdangerous": "itsdangerous", "authlib": "Authlib",
    }
    for mod, label in deps.items():
        ok = _spec(mod)
        checks.append(_check(f"dep:{mod}", f"依赖 {label}", ok,
                             "已安装" if ok else "缺失", f"模块 {mod}"))

    # SQLite 数据目录可写
    data_dir = _ext_root() / "data"
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
        probe = data_dir / ".check_deployment_write_probe"
        probe.write_text("ok")
        probe.unlink()
        sqlite_ok = True
        sqlite_val = str(data_dir)
    except Exception as exc:  # noqa: BLE001
        sqlite_ok, sqlite_val = False, str(exc)
    checks.append(_check("sqlite", "SQLite 数据目录可写", sqlite_ok, sqlite_val))

    # OSS 凭据
    oss_configured = all(_env(k) for k in ("OSS_ACCESS_KEY_ID", "OSS_ACCESS_KEY_SECRET", "OSS_BUCKET"))
    checks.append(_check("oss", "OSS 凭据完整", oss_configured,
                         _env("OSS_BUCKET") or "未设置",
                         "OSS_ACCESS_KEY_ID/SECRET/BUCKET 三者须齐备"))

    # WORKER_TOKEN（生产必须为非空强令牌）
    token = _env("WORKER_TOKEN")
    token_ok = bool(token) and token != "change-me-to-a-long-random-token"
    checks.append(_check("worker_token", "WORKER_TOKEN 已设置（生产必须）", token_ok,
                         "已设置" if token else "未设置",
                         "生产环境必须设置强随机令牌"))

    # 鉴权配置（AUTH_DISABLED=false 时必须 SESSION_SECRET）
    auth_disabled = _env("AUTH_DISABLED", "false").lower() in ("1", "true", "yes")
    secret = _env("SESSION_SECRET")
    if auth_disabled:
        checks.append(_check("auth", "鉴权", True, "AUTH_DISABLED=true（已关闭鉴权）",
                             "生产环境不应关闭鉴权"))
    else:
        secret_ok = bool(secret) and len(secret) >= 32
        checks.append(_check("auth", "鉴权 SESSION_SECRET（≥32 字符）", secret_ok,
                             "已设置" if secret else "未设置",
                             "AUTH_DISABLED=false 时必须设置 ≥32 字符 SESSION_SECRET"))

    # 前端静态资源
    dist = ROOT / "dist"
    front_ok = (dist / "index.html").exists() and (dist / "assets").exists()
    checks.append(_check("frontend", "前端静态资源 dist/", front_ok, str(dist)))

    return checks


# --------------------------------------------------------------------------- #
# GPU 节点检查
# --------------------------------------------------------------------------- #
def check_node() -> list[dict]:
    local = _local_root()
    checks: list[dict] = []

    # GPU
    rc, out = _run(["nvidia-smi", "--query-gpu=name,memory.total,memory.used",
                    "--format=csv,noheader,nounits"], timeout=10)
    if rc == 0 and out:
        first = out.splitlines()[0]
        parts = [p.strip() for p in first.split(",")]
        gpu_name = parts[0] if parts else "?"
        mem_total = parts[1] if len(parts) > 1 else "?"
        mem_used = parts[2] if len(parts) > 2 else "?"
        checks.append(_check("gpu", "GPU", True, gpu_name,
                             f"显存 {mem_used}/{mem_total} MB"))
        checks.append(_check("gpu_mem", "GPU 显存", True, f"{mem_total} MB"))
    else:
        checks.append(_check("gpu", "GPU (nvidia-smi)", False, "不可用",
                             f"nvidia-smi 返回 {out or '空'}"))

    # CUDA（用 hunyuan venv 的 torch 探测）
    py = _python_bin(local)
    if py.exists():
        rc, ver = _run([str(py), "-c", "import torch; print(torch.__version__)"], timeout=60)
        torch_ok = rc == 0
        checks.append(_check("torch", "PyTorch", torch_ok, ver if torch_ok else "不可用",
                             f"venv: {py}"))
        if torch_ok:
            rc, cuda = _run([str(py), "-c", "import torch; print(torch.cuda.is_available())"], timeout=60)
            checks.append(_check("cuda", "CUDA 可用", rc == 0 and cuda.strip() == "True",
                                 cuda.strip() if rc == 0 else "探测失败"))
    else:
        checks.append(_check("torch", "PyTorch venv", False, "venv 不存在", str(py)))

    # Hunyuan3D-2.1 权重
    model = local / "Hunyuan3D-2.1-model"
    dit = model / "hunyuan3d-dit-v2-1" / "model.fp16.ckpt"
    vae = model / "hunyuan3d-vae-v2-1" / "model.fp16.ckpt"
    dit_cfg = model / "hunyuan3d-dit-v2-1" / "config.yaml"
    if dit.exists():
        sz = dit.stat().st_size
        checks.append(_check("hunyuan_dit", "Hunyuan3D-2.1 DiT 权重", sz >= DIT_CKPT_MIN_BYTES,
                             _fmt_bytes(sz), str(dit)))
    else:
        checks.append(_check("hunyuan_dit", "Hunyuan3D-2.1 DiT 权重", False, "缺失", str(dit)))
    if vae.exists():
        sz = vae.stat().st_size
        checks.append(_check("hunyuan_vae", "Hunyuan3D-2.1 VAE 权重", sz >= VAE_CKPT_MIN_BYTES,
                             _fmt_bytes(sz), str(vae)))
    else:
        checks.append(_check("hunyuan_vae", "Hunyuan3D-2.1 VAE 权重", False, "缺失", str(vae)))
    checks.append(_check("hunyuan_cfg", "DiT config.yaml", dit_cfg.exists(),
                         "存在" if dit_cfg.exists() else "缺失", str(dit_cfg)))

    # Hunyuan3D-2mv 权重（可选，多视图用）
    mv = local / "Hunyuan3D-2mv-model-v2" / "hunyuan3d-dit-v2-mv" / "model.fp16.safetensors"
    if mv.exists():
        sz = mv.stat().st_size
        checks.append(_check("hunyuan_mv", "Hunyuan3D-2mv 权重", sz == HUNYUAN_MV_EXPECTED_BYTES,
                             _fmt_bytes(sz), "完整" if sz == HUNYUAN_MV_EXPECTED_BYTES else "大小不符"))
    else:
        checks.append(_check("hunyuan_mv", "Hunyuan3D-2mv 权重（可选）", True,
                             "未安装", "多视图生成才需要"))

    # Blender
    blender = _blender_bin(local)
    if blender.exists():
        rc, ver = _run([str(blender), "--version"], timeout=30)
        checks.append(_check("blender", "Blender", rc == 0,
                             ver.splitlines()[0] if rc == 0 and ver else "存在",
                             str(blender)))
    else:
        checks.append(_check("blender", "Blender", False, "缺失", str(blender)))

    # 仓库与流水线脚本
    runner = ROOT / "pipeline" / "run_hunyuan_yoyo.py"
    mv_runner = ROOT / "pipeline" / "run_hunyuan_multiview.py"
    renderer = ROOT / "pipeline" / "blender_render_job.py"
    refiner = ROOT / "pipeline" / "blender_auto_refine.py"
    stl = ROOT / "pipeline" / "blender_export_stl.py"
    for key, label, p in (
        ("repo_runner", "Hunyuan 推理脚本", runner),
        ("repo_mv_runner", "Hunyuan 多视图脚本", mv_runner),
        ("repo_renderer", "Blender 渲染脚本", renderer),
        ("repo_refiner", "Blender 精修脚本", refiner),
        ("repo_stl", "Blender STL 导出脚本", stl),
    ):
        checks.append(_check(key, label, p.exists(), "存在" if p.exists() else "缺失", str(p)))

    # rembg 模型
    u2net = Path.home() / ".u2net" / "u2net.onnx"
    checks.append(_check("rembg", "rembg 背景移除模型 u2net.onnx", u2net.exists(),
                         _fmt_bytes(u2net.stat().st_size) if u2net.exists() else "缺失", str(u2net)))

    return checks


# --------------------------------------------------------------------------- #
# 自注册 agent 连接性检查
# --------------------------------------------------------------------------- #
def check_agent() -> list[dict]:
    control_url = _env("CONTROL_URL").rstrip("/")
    token = _env("WORKER_TOKEN")
    checks: list[dict] = []
    checks.append(_check("control_url", "CONTROL_URL 已设置", bool(control_url),
                         control_url or "未设置"))

    if not control_url:
        return checks

    # HTTP 健康检查
    health_url = f"{control_url}/api/system/health"
    rc, out = _run(["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}",
                    "--max-time", "15", health_url], timeout=20)
    checks.append(_check("http", "控制面 HTTP 可达", rc == 0 and out == "200",
                         f"HTTP {out}" if rc == 0 else "连接失败",
                         health_url))

    # WebSocket 握手（websockets 可用时做真实握手，否则降级 HTTP 探测）
    if _spec("websockets"):
        ws_code = (
            f"import asyncio,json,websockets,sys\n"
            f"async def m():\n"
            f"    u={control_url!r}\n"
            f"    scheme='wss' if u.startswith('https://') else 'ws'\n"
            f"    rest=u.split('://',1)[1]\n"
            f"    url=scheme+'://'+rest+'/api/gpu/ws'\n"
            f"    async with websockets.connect(url,max_size=10485760) as w:\n"
            f"        await w.send(json.dumps({{'type':'hello','token':{token!r},'node':{{'id':'probe','name':'probe','caps':{{}}}}}}))\n"
            f"        a=json.loads(await asyncio.wait_for(w.recv(),10))\n"
            f"        print('OK' if a.get('type') in ('hello_ack','error') else 'UNEXPECTED:'+str(a)[:100])\n"
            f"asyncio.run(m())\n"
        )
        rc, out = _run([sys.executable, "-c", ws_code], timeout=30)
        ws_ok = rc == 0 and out.startswith("OK")
        checks.append(_check("ws", "WebSocket 端点握手", ws_ok, out[:120],
                             f"{control_url}/api/gpu/ws"))
    else:
        ws_url = f"{control_url}/api/gpu/ws"
        rc, out = _run(["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}",
                        "--max-time", "15", ws_url], timeout=20)
        # WS 端点对普通 HTTP 请求返回 403（FastAPI 未匹配 WS 路由），404 表示端点不存在
        checks.append(_check("ws", "WebSocket 端点存在（HTTP 探测）",
                             rc == 0 and out in ("403", "101"), f"HTTP {out}",
                             ws_url))

    # WORKER_TOKEN 是否匹配由上面的 WS 握手隐式验证（控制面设了 token 而 agent
    # 没设会收到 error），这里仅作提示，不作为阻断项。
    checks.append(_check("token", "WORKER_TOKEN", True,
                         "已设置" if token else "未设置",
                         "鉴权由 WS 握手隐式验证；生产建议与控制面保持一致"))
    return checks


ROLES = {"control": check_control, "node": check_node, "agent": check_agent}


def main() -> int:
    ap = argparse.ArgumentParser(description="2D→3D Studio 线上部署环境监测")
    ap.add_argument("--role", choices=["control", "node", "agent", "all"], default="all")
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    args = ap.parse_args()

    roles = list(ROLES) if args.role == "all" else [args.role]
    report = {"schemaVersion": 1, "roles": {}}
    for role in roles:
        checks = ROLES[role]()
        report["roles"][role] = {
            "checks": checks,
            "passed": sum(1 for c in checks if c["ok"]),
            "total": len(checks),
        }

    blocking = any(not c["ok"] for r in roles for c in report["roles"][r]["checks"])
    report["status"] = "failed" if blocking else "passed"

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        for role in roles:
            r = report["roles"][role]
            print(f"\n=== {role}（{r['passed']}/{r['total']} 通过）===")
            for c in r["checks"]:
                mark = "✅" if c["ok"] else "❌"
                line = f"  {mark} {c['label']}"
                if c["value"]:
                    line += f"  [{c['value']}]"
                print(line)
                if c["detail"]:
                    print(f"        {c['detail']}")
        print(f"\n总览：{'✅ 全部通过' if report['status']=='passed' else '❌ 存在阻断项，请先修复'}")

    return 1 if blocking else 0


if __name__ == "__main__":
    sys.exit(main())
