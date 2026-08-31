"""AutoDL 容器实例 Pro API 客户端 + 管理路由（前缀 /api/autodl，仅管理员）。

用途：云算力按需开关机——任务排队时开机、空闲时关机以控制成本。
凭据（开发者 Token）走环境变量 AUTODL_API_TOKEN，不出现在代码或 Git 仓库。

API 服务端 HOST：https://api.autodl.com
鉴权：headers = {"Authorization": "<token>"}（原始 token，非 Bearer）
"""
from __future__ import annotations

import os

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

AUTODL_API_TOKEN = os.environ.get('AUTODL_API_TOKEN', '')
AUTODL_API_BASE = os.environ.get('AUTODL_API_BASE', 'https://api.autodl.com')

router = APIRouter(prefix='/api/autodl', tags=['autodl'])


def configured() -> bool:
    return bool(AUTODL_API_TOKEN)


def _headers() -> dict:
    return {'Authorization': AUTODL_API_TOKEN, 'Content-Type': 'application/json'}


def _call(method: str, path: str, body: dict | None = None) -> dict:
    if not configured():
        raise RuntimeError('AutoDL 未配置：缺少 AUTODL_API_TOKEN')
    r = httpx.request(method, f'{AUTODL_API_BASE}{path}', json=body or {}, headers=_headers(), timeout=30)
    r.raise_for_status()
    data = r.json()
    if data.get('code') != 'Success':
        raise RuntimeError(f'AutoDL API 错误: {data.get("msg") or data.get("code")}')
    return data


def list_instances(page_index: int = 1, page_size: int = 50) -> list[dict]:
    data = _call('POST', '/api/v1/dev/instance/pro/list', {'page_index': page_index, 'page_size': page_size})
    return (data.get('data') or {}).get('list', [])


def instance_status(instance_uuid: str) -> str | None:
    for inst in list_instances():
        if inst.get('uuid') == instance_uuid:
            return inst.get('status')
    return None


def power_on(instance_uuid: str, payload: str = 'gpu', start_command: str | None = None) -> dict:
    body: dict = {'instance_uuid': instance_uuid, 'payload': payload}
    if start_command:
        body['start_command'] = start_command
    return _call('POST', '/api/v1/dev/instance/pro/power_on', body)


def power_off(instance_uuid: str) -> dict:
    return _call('POST', '/api/v1/dev/instance/pro/power_off', {'instance_uuid': instance_uuid})


def wallet_balance() -> dict:
    return _call('POST', '/api/v1/dev/wallet/balance', {})


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
