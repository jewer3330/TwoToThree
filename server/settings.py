"""站点配置中心。

把「写死在各处 / 散落在 env」的站点级可配置项收拢为统一配置目录：
- 默认值来自环境变量（部署时注入）
- 管理员可通过系统设置页 /api/settings 覆盖（持久化到 <DATA>/site_settings.json）
- 运行时消费方（如 CORS 中间件）读取当前值，改后无需重启即生效

设计：通用 key-value + 分组 + 敏感标记。敏感值（凭据类）只读展示时掩码，
且默认仅从 env 读取、不落盘（除非管理员显式覆盖）。
"""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any

from .core import DATA

_lock = threading.RLock()
_SETTINGS_FILE = DATA / "site_settings.json"

# --------------------------------------------------------------------------- #
# 配置目录：key -> 定义
#   env        默认值来源环境变量名（可空 = 无 env 默认）
#   group      分组
#   label      展示名
#   hint       说明
#   sensitive  敏感（掩码显示，保存时若留空则保留原值）
#   secret     从不下发/不上传（仅后端使用，如凭据默认值）
# --------------------------------------------------------------------------- #
CATALOG: dict[str, dict[str, Any]] = {
    # -- 站点信息 --
    "site.name": {
        "env": "SITE_NAME", "default": "2D→3D 造物坊", "group": "站点信息",
        "label": "站点名称", "hint": "浏览器标题、登录页与落地页展示名",
    },
    "site.publicBaseUrl": {
        "env": "SITE_PUBLIC_BASE_URL", "default": "", "group": "站点信息",
        "label": "对外访问地址", "hint": "例如 https://3.lovesun.top（留空=同源相对路径）",
    },
    # -- 域名 / 接入 --
    "site.corsOrigins": {
        "env": "CORS_ORIGINS",
        "default": "http://localhost:5173,http://127.0.0.1:5173",
        "group": "域名与接入", "label": "允许跨域来源",
        "hint": "逗号分隔。开发与生产前端域名都列在此，改后即时生效",
    },
    "site.oidcIssuer": {
        "env": "OIDC_ISSUER", "default": "", "group": "域名与接入",
        "label": "OIDC Issuer", "hint": "账户系统 Authentik 的 issuer 地址（展示）",
    },
    "site.oidcRedirectUri": {
        "env": "OIDC_REDIRECT_URI", "default": "", "group": "域名与接入",
        "label": "OIDC 回调地址", "hint": "登录回跳地址（展示）",
    },
    "site.authentikBaseUrl": {
        "env": "AUTHENTIK_BASE_URL", "default": "", "group": "域名与接入",
        "label": "Authentik 入口", "hint": "例如 https://3.lovesun.top/authentik/（展示）",
    },
    "site.gpuNodeControlUrl": {
        "env": "CONTROL_URL", "default": "", "group": "域名与接入",
        "label": "算力节点接入地址",
        "hint": "GPU 节点 agent 需要连入的控制面地址（部署用提示）",
    },
    # -- 对象存储 --
    "storage.backend": {
        "env": "STORAGE_BACKEND", "default": "auto", "group": "对象存储",
        "label": "传输 / 存储后端",
        "hint": "auto=有 OSS 凭据用 OSS 否则走 CDN/节点直传；oss=强制阿里 OSS；cdn=强制 CDN/节点直传。保存后立即生效，不再需要改环境变量。",
        "options": [
            {"value": "auto", "label": "自动（auto）"},
            {"value": "oss", "label": "阿里云 OSS（oss）"},
            {"value": "cdn", "label": "CDN / 节点直传（cdn）"},
        ],
    },
    "site.ossBucket": {
        "env": "OSS_BUCKET", "default": "", "group": "对象存储",
        "label": "OSS Bucket", "hint": "阿里云 OSS 桶名（凭据仍从环境变量读取）",
    },
    "site.ossEndpoint": {
        "env": "OSS_ENDPOINT", "default": "", "group": "对象存储",
        "label": "OSS Endpoint", "hint": "地域节点（凭据仍从环境变量读取）",
    },
    "site.ossPublicEndpoint": {
        "env": "OSS_PUBLIC_ENDPOINT", "default": "", "group": "对象存储",
        "label": "OSS 公网域名", "hint": "CNAME/自定义域名，浏览器下载签名使用（凭据仍从环境变量读取）",
    },
    # -- 安全 --
    "auth.disabled": {
        "env": "AUTH_DISABLED", "default": "false", "group": "安全",
        "label": "关闭鉴权", "hint": "true/false；生产必须 false",
    },
}


def _env(name: str, default: str = "") -> str:
    v = os.environ.get(name)
    return v if v not in (None, "") else default


def _read_overrides() -> dict:
    if not _SETTINGS_FILE.exists():
        return {}
    try:
        data = json.loads(_SETTINGS_FILE.read_text(encoding="utf-8"))
        values = data.get("values") if isinstance(data, dict) else None
        return values if isinstance(values, dict) else {}
    except Exception:
        return {}


def _write_overrides(overrides: dict) -> None:
    _SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    _SETTINGS_FILE.write_text(
        json.dumps({"schemaVersion": 1, "values": overrides},
                   ensure_ascii=False, indent=2),
        encoding="utf-8")


def current(key: str) -> str:
    """读取某个配置的当前生效值（覆盖 > env > 默认）。"""
    with _lock:
        overrides = _read_overrides()
    if key in overrides:
        return str(overrides[key])
    definition = CATALOG.get(key)
    if not definition:
        return ""
    return _env(definition.get("env", ""), definition.get("default", ""))


def current_all() -> dict[str, str]:
    with _lock:
        overrides = _read_overrides()
    out: dict[str, str] = {}
    for key, definition in CATALOG.items():
        out[key] = str(overrides.get(key, _env(definition.get("env", ""), definition.get("default", ""))))
    return out


def catalog_entries(admin: bool = False) -> list[dict]:
    """按分组返回可展示配置（前端设置页用）。secret 项对非管理员过滤。"""
    values = current_all()
    out: list[dict] = []
    for key, definition in CATALOG.items():
        if definition.get("secret") and not admin:
            continue
        value = values.get(key, "")
        out.append({
            "key": key,
            "group": definition["group"],
            "label": definition["label"],
            "hint": definition.get("hint", ""),
            "sensitive": bool(definition.get("sensitive")),
            "secret": bool(definition.get("secret")),
            "options": definition.get("options"),
            "value": value,
        })
    out.sort(key=lambda e: e["key"])
    return out


def update(entries: dict[str, str]) -> dict[str, str]:
    """管理员保存覆盖值。只接受目录内存在的 key；敏感项留空=不修改。"""
    with _lock:
        overrides = _read_overrides()
        for key, raw in entries.items():
            if key not in CATALOG:
                continue
            definition = CATALOG[key]
            value = (raw or "").strip()
            if definition.get("sensitive") and not value:
                continue  # 敏感项空值 = 保持原状
            if value:
                overrides[key] = value
            else:
                overrides.pop(key, None)  # 空值 = 恢复 env/默认
        _write_overrides(overrides)
        return current_all()


def cors_origins() -> list[str]:
    """CORS 中间件运行时读取（改配置即时生效）。"""
    value = current("site.corsOrigins")
    return [o.strip() for o in value.split(",") if o.strip()]
