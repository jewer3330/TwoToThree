"""AutoDL 容器实例 Pro API 客户端 + 管理路由（前缀 /api/autodl，仅管理员）。

用途：云算力按需开关机——任务排队时开机、空闲时关机以控制成本；
GPU 集群以 provider='autodl' 节点接入，生命周期由 gpu/scheduler.py 管理。
凭据（开发者 Token）走环境变量 AUTODL_API_TOKEN / AUTODL_TOKEN，不出现在代码或 Git 仓库。

官方 API（仅 Pro 实例支持开机/关机）：
  - HOST: https://api.autodl.com
  - 鉴权: headers = {"Authorization": "<token>"}（原始 token，非 Bearer）
"""
from __future__ import annotations

import os
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from . import config

AUTODL_API_TOKEN = os.environ.get('AUTODL_API_TOKEN', '') or config.AUTODL_TOKEN
AUTODL_API_BASE = os.environ.get('AUTODL_API_BASE', 'https://api.autodl.com')

router = APIRouter(prefix='/api/autodl', tags=['autodl'])


class AutoDlError(RuntimeError):
    pass


class AutoDlClient:
    """官方 Pro API 客户端（gpu/scheduler 生命周期与 backends 探测使用）。"""

    def __init__(self, token: str | None = None) -> None:
        self._token = token or AUTODL_API_TOKEN
        if not self._token:
            raise AutoDlError('AutoDL 未配置：缺少 AUTODL_API_TOKEN / AUTODL_TOKEN')
        self._http = httpx.Client(base_url=AUTODL_API_BASE, timeout=30)

    def _headers(self) -> dict:
        # 官方要求：Authorization 直接放 token，无 Bearer 前缀
        return {'Authorization': self._token, 'Content-Type': 'application/json'}

    def _call(self, method: str, path: str, body: dict | None = None) -> dict[str, Any]:
        resp = self._http.request(method, path, json=body or {}, headers=self._headers())
        resp.raise_for_status()
        data = resp.json()
        if data.get('code') != 'Success':
            raise AutoDlError(f"AutoDL API 失败：{data.get('code')} {data.get('msg')}")
        return data

    def list_instances(self, page_index: int = 1, page_size: int = 50) -> list[dict[str, Any]]:
        data = self._call('POST', '/api/v1/dev/instance/pro/list',
                          {'page_index': page_index, 'page_size': page_size})
        return (data.get('data') or {}).get('list', [])

    def status(self, instance_uuid: str) -> str:
        data = self._call('GET', '/api/v1/dev/instance/pro/status', {'instance_uuid': instance_uuid})
        return data.get('data', '')

    def power_on(self, instance_uuid: str, start_command: str | None = None, payload: str = 'gpu') -> dict[str, Any]:
        body: dict[str, Any] = {'instance_uuid': instance_uuid, 'payload': payload}
        if start_command:
            body['start_command'] = start_command
        return self._call('POST', '/api/v1/dev/instance/pro/power_on', body)

    def power_off(self, instance_uuid: str) -> dict[str, Any]:
        return self._call('POST', '/api/v1/dev/instance/pro/power_off', {'instance_uuid': instance_uuid})

    def wallet_balance(self) -> dict[str, Any]:
        return self._call('POST', '/api/v1/dev/wallet/balance', {})

    def is_running(self, instance_uuid: str) -> bool:
        return self.status(instance_uuid) in ('running',)


def client() -> AutoDlClient:
    return AutoDlClient()


def configured() -> bool:
    return bool(AUTODL_API_TOKEN)


# ---------------- 管理路由所需的模块级封装 ----------------
def list_instances(page_index: int = 1, page_size: int = 50) -> list[dict]:
    return client().list_instances(page_index, page_size)


def instance_status(instance_uuid: str) -> str | None:
    for inst in client().list_instances():
        if inst.get('uuid') == instance_uuid:
            return inst.get('status')
    return None


def power_on(instance_uuid: str, payload: str = 'gpu', start_command: str | None = None) -> dict:
    return client().power_on(instance_uuid, start_command, payload)


def power_off(instance_uuid: str) -> dict:
    return client().power_off(instance_uuid)


def wallet_balance() -> dict:
    return client().wallet_balance()


class PowerOnBody(BaseModel):
    payload: str = 'gpu'
    start_command: str | None = None


@router.get('/instances')
def api_list_instances():
    try:
        return {'configured': configured(), 'instances': list_instances()}
    except RuntimeError as exc:
        raise HTTPException(503, str(exc))


@router.get('/balance')
def api_balance():
    try:
        return wallet_balance()
    except RuntimeError as exc:
        raise HTTPException(503, str(exc))


@router.post('/instances/{instance_uuid}/power-on')
def api_power_on(instance_uuid: str, body: PowerOnBody | None = None):
    try:
        return power_on(instance_uuid, (body.payload if body else 'gpu'), (body.start_command if body else None))
    except RuntimeError as exc:
        raise HTTPException(503, str(exc))


@router.post('/instances/{instance_uuid}/power-off')
def api_power_off(instance_uuid: str):
    try:
        return power_off(instance_uuid)
    except RuntimeError as exc:
        raise HTTPException(503, str(exc))
