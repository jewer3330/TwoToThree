"""阿里云 OSS 对象存储客户端（V1 签名，无第三方 SDK 依赖）。

用途：大文件 CDN 中转——主控预签名上传/下载 URL，GPU 节点用 curl 直传，
绕开 tailscale relay 慢路径；scp 仅作兜底。

配置全部走环境变量，凭据不出现在代码或 Git 仓库：
  OSS_ACCESS_KEY_ID / OSS_ACCESS_KEY_SECRET / OSS_BUCKET
  OSS_ENDPOINT（默认 oss-cn-shanghai.aliyuncs.com）
  OSS_PUBLIC_ENDPOINT（可选 CNAME/自定义域名；默认 <bucket>.<endpoint>）
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import time
import urllib.parse
from pathlib import Path

import httpx

OSS_ACCESS_KEY_ID = os.environ.get('OSS_ACCESS_KEY_ID', '')
OSS_ACCESS_KEY_SECRET = os.environ.get('OSS_ACCESS_KEY_SECRET', '')
OSS_BUCKET = os.environ.get('OSS_BUCKET', 'print-3d')
OSS_ENDPOINT = os.environ.get('OSS_ENDPOINT', 'oss-cn-shanghai.aliyuncs.com')
OSS_PUBLIC_ENDPOINT = os.environ.get('OSS_PUBLIC_ENDPOINT', '')

_CONTENT_TYPES = {
    '.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg',
    '.webp': 'image/webp', '.glb': 'model/gltf-binary', '.gltf': 'model/gltf+json',
    '.stl': 'model/stl', '.obj': 'model/obj', '.3mf': 'model/3mf',
    '.zip': 'application/zip', '.tgz': 'application/gzip', '.json': 'application/json',
}


def configured() -> bool:
    return bool(OSS_ACCESS_KEY_ID and OSS_ACCESS_KEY_SECRET and OSS_BUCKET)


def _host() -> str:
    return OSS_PUBLIC_ENDPOINT or f'{OSS_BUCKET}.{OSS_ENDPOINT}'


def _resource(key: str) -> str:
    return f'/{OSS_BUCKET}/{key.lstrip("/")}'


def _sign(method: str, key: str, expires: int) -> str:
    """OSS V1 预签名：Content-MD5/Content-Type 均为空，客户端不携带 Content-Type。"""
    string_to_sign = f'{method.upper()}\n\n\n{expires}\n{_resource(key)}'
    mac = hmac.new(OSS_ACCESS_KEY_SECRET.encode('utf-8'), string_to_sign.encode('utf-8'), hashlib.sha1)
    return base64.b64encode(mac.digest()).decode('ascii')


def _signed_url(method: str, key: str, expires: int) -> str:
    sig = _sign(method, key, expires)
    params = {'OSSAccessKeyId': OSS_ACCESS_KEY_ID, 'Expires': str(expires), 'Signature': sig}
    return f'https://{_host()}/{key.lstrip("/")}?' + urllib.parse.urlencode(params)


def presign_get(key: str, expires: int = 3600) -> str:
    """生成带签名的下载 URL（GET）。"""
    if not configured():
        raise RuntimeError('OSS 未配置：缺少 OSS_ACCESS_KEY_ID/SECRET/BUCKET')
    return _signed_url('GET', key, expires)


def presign_put(key: str, expires: int = 3600) -> str:
    """生成带签名的上传 URL（PUT）。客户端 curl 上传时不要携带 Content-Type 头。"""
    if not configured():
        raise RuntimeError('OSS 未配置：缺少 OSS_ACCESS_KEY_ID/SECRET/BUCKET')
    return _signed_url('PUT', key, expires)


def public_url(key: str) -> str:
    """公开可访问 URL（桶需为公共读，或走 CDN/CNAME）。"""
    return f'https://{_host()}/{key.lstrip("/")}'


def _guess_content_type(name: str) -> str:
    return _CONTENT_TYPES.get(Path(name).suffix.lower(), 'application/octet-stream')


def upload_bytes(key: str, data: bytes) -> str:
    """直接上传字节到 OSS（主控侧使用），返回公开 URL。"""
    if not configured():
        raise RuntimeError('OSS 未配置：缺少 OSS_ACCESS_KEY_ID/SECRET/BUCKET')
    expires = int(time.time()) + 3600
    url = _signed_url('PUT', key, expires)
    r = httpx.put(url, content=data, timeout=300)
    r.raise_for_status()
    return public_url(key)


def upload_file(local: str | Path, key: str) -> str:
    return upload_bytes(key, Path(local).read_bytes())
