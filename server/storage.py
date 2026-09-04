"""存储门面：本地缓存 + OSS 交换层和最终制品源。

约定：
  - STORAGE_BACKEND=oss 时，最终制品先按内容哈希上传 OSS，再允许任务完成。
  - 总控本地文件保留为缓存/故障兜底，不再是浏览器大文件的默认来源。
  - 未配置 OSS 时（默认单机模式），本模块不参与任何路径，现有行为不变。
"""
from __future__ import annotations

from pathlib import Path

from . import config


class StorageError(RuntimeError):
    pass


class OssStorage:
    """阿里云 OSS 的最小封装，惰性导入 oss2 以免强依赖。"""

    def __init__(self) -> None:
        try:
            import oss2
        except ImportError as exc:  # pragma: no cover - 环境相关
            raise StorageError("缺少 oss2 依赖，请先 `pip install oss2`") from exc
        self._oss2 = oss2
        auth = oss2.Auth(config.OSS_ACCESS_KEY_ID, config.OSS_ACCESS_KEY_SECRET)
        transfer_endpoint = config.OSS_INTERNAL_ENDPOINT or config.OSS_ENDPOINT
        self.bucket = oss2.Bucket(auth, transfer_endpoint, config.OSS_BUCKET)
        public_endpoint = config.OSS_PUBLIC_ENDPOINT or config.OSS_ENDPOINT
        self._public_bucket = oss2.Bucket(auth, public_endpoint, config.OSS_BUCKET,
                                          is_cname=bool(config.OSS_PUBLIC_ENDPOINT))

    def key(self, oss_path: str) -> str:
        path = oss_path.strip("/")
        return f"{config.OSS_PREFIX}/{path}" if config.OSS_PREFIX else path

    def upload(self, local_path: Path, oss_path: str, *, mime_type: str | None = None) -> str:
        key = self.key(oss_path)
        headers = {
            "Cache-Control": "public, max-age=31536000, immutable",
            "Content-Disposition": f'inline; filename="{local_path.name.replace(chr(34), "")}"',
        }
        if mime_type:
            headers["Content-Type"] = mime_type
        self.bucket.put_object_from_file(key, str(local_path), headers=headers)
        return key

    def download(self, oss_path: str, local_path: Path) -> Path:
        local_path.parent.mkdir(parents=True, exist_ok=True)
        self.bucket.get_object_to_file(self.key(oss_path), str(local_path))
        return local_path

    def exists(self, oss_path: str) -> bool:
        try:
            return bool(self.bucket.object_exists(self.key(oss_path)))
        except Exception:
            return False

    def size(self, oss_path: str) -> int | None:
        try:
            return int(self.bucket.head_object(self.key(oss_path)).content_length)
        except Exception:
            return None

    def sign_get(self, oss_path: str, expires: int | None = None) -> str:
        key = self.key(oss_path)
        expiry = expires or config.OSS_URL_EXPIRES
        try:
            return self._public_bucket.sign_url("GET", key, expiry, slash_safe=True)
        except TypeError:
            # 旧版 oss2 没有 slash_safe 参数。
            return self._public_bucket.sign_url("GET", key, expiry)

    def sign_put(self, oss_path: str, expires: int | None = None) -> str:
        """生成 PUT 签名 URL，供节点端 curl 直传产物到 OSS。"""
        key = self.key(oss_path)
        expiry = expires or config.OSS_URL_EXPIRES
        try:
            return self._public_bucket.sign_url("PUT", key, expiry, slash_safe=True)
        except TypeError:
            return self._public_bucket.sign_url("PUT", key, expiry)


def resolve_transfer_backend(node_cfg: dict | None = None) -> str:
    """决定文件传输后端：节点级 transfer 优先，其次全局 STORAGE_BACKEND。

    返回值：'oss'（对象存储，公网可达）或 'cdn'（CDN+scp，SSH 节点直传）。
    """
    node = ((node_cfg or {}).get("transfer") or "").strip().lower()
    if node in ("oss", "cdn"):
        return node
    backend = (config.STORAGE_BACKEND or "auto").strip().lower()
    if backend in ("oss", "cdn"):
        return backend
    # auto：有完整 OSS 凭据则用 OSS，否则 CDN+scp
    if config.OSS_BUCKET and config.OSS_ACCESS_KEY_ID and config.OSS_ACCESS_KEY_SECRET:
        return "oss"
    return "cdn"


class Storage:
    """门面：OSS 可用时提供对象存储操作，否则明确报错。"""

    def __init__(self) -> None:
        self._oss: OssStorage | None = None
        self._reason: str | None = None
        if config.OSS_BUCKET and config.OSS_ACCESS_KEY_ID and config.OSS_ACCESS_KEY_SECRET:
            try:
                self._oss = OssStorage()
            except Exception as exc:  # noqa: BLE001 - 记录原因，延迟到使用时报错
                self._reason = str(exc)

    @property
    def enabled(self) -> bool:
        return self._oss is not None

    @property
    def reason(self) -> str | None:
        return self._reason

    def oss(self) -> OssStorage:
        if self._oss is None:
            if self._reason:
                raise StorageError(f"OSS 初始化失败：{self._reason}")
            raise StorageError("OSS 未配置（缺少 OSS_BUCKET / OSS_ACCESS_KEY_ID / OSS_ACCESS_KEY_SECRET）")
        return self._oss

    def store_artifact(self, local_path: Path, digest: str, mime_type: str) -> str:
        """上传内容寻址的最终制品，返回不含全局 OSS_PREFIX 的逻辑对象键。"""
        suffix = local_path.suffix.lower()
        logical_key = f"{config.OSS_ARTIFACT_PREFIX}/{digest[:2]}/{digest}{suffix}"
        oss = self.oss()
        expected = local_path.stat().st_size
        if oss.size(logical_key) != expected:
            oss.upload(local_path, logical_key, mime_type=mime_type)
        actual = oss.size(logical_key)
        if actual != expected:
            raise StorageError(f"OSS 制品校验失败：expected={expected}, actual={actual}")
        return logical_key


storage = Storage()
