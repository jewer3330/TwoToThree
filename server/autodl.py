"""AutoDL 容器实例 Pro API 客户端（自动启停）。

官方 API（仅 Pro 实例支持开机/关机）：
  - base URL: https://api.autodl.com
  - 鉴权: Authorization: <token>（无 Bearer 前缀）
  - 开机: POST /api/v1/dev/instance/pro/power_on   body {"instance_uuid","payload":"gpu","start_command"?}
  - 关机: POST /api/v1/dev/instance/pro/power_off  body {"instance_uuid"}
  - 状态: GET  /api/v1/dev/instance/pro/status     body {"instance_uuid"}
  - 列表: POST /api/v1/dev/instance/pro/list       body {} (可选 page_index/page_size)
"""
from __future__ import annotations

from typing import Any

import httpx

from . import config


class AutoDlError(RuntimeError):
    pass


class AutoDlClient:
    def __init__(self, token: str | None = None) -> None:
        self._token = token or config.AUTODL_TOKEN
        if not self._token:
            raise AutoDlError("缺少 AUTODL_TOKEN")
        self._http = httpx.Client(base_url="https://api.autodl.com", timeout=30)

    def _headers(self) -> dict:
        # 官方要求：Authorization 直接放 token，无 Bearer 前缀
        return {"Authorization": self._token, "Content-Type": "application/json"}

    def _call(self, method: str, path: str, body: dict | None = None) -> dict[str, Any]:
        resp = self._http.request(method, path, json=body, headers=self._headers())
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") != "Success":
            raise AutoDlError(f"AutoDL API 失败：{data.get('code')} {data.get('msg')}")
        return data

    def list_instances(self) -> list[dict[str, Any]]:
        data = self._call("POST", "/api/v1/dev/instance/pro/list", {})
        return data.get("data", {}).get("list", [])

    def status(self, instance_uuid: str) -> str:
        data = self._call("GET", "/api/v1/dev/instance/pro/status", {"instance_uuid": instance_uuid})
        return data.get("data", "")

    def power_on(self, instance_uuid: str, start_command: str | None = None) -> dict[str, Any]:
        body: dict[str, Any] = {"instance_uuid": instance_uuid, "payload": "gpu"}
        if start_command:
            body["start_command"] = start_command
        return self._call("POST", "/api/v1/dev/instance/pro/power_on", body)

    def power_off(self, instance_uuid: str) -> dict[str, Any]:
        return self._call("POST", "/api/v1/dev/instance/pro/power_off", {"instance_uuid": instance_uuid})

    def is_running(self, instance_uuid: str) -> bool:
        return self.status(instance_uuid) in ("running",)


def client() -> AutoDlClient:
    return AutoDlClient()
