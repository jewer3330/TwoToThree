"""存储门面：本地磁盘（权威来源） + OSS（共享存储 / 交换层）。

约定：
  - 总控本地磁盘仍是数据权威来源与服务来源（URL 指向 /data/...）。
  - 配置 OSS 后，输入素材与产物经 OSS 中转：总控上传输入、显卡机下载输入，
    显卡机上传产物、总控下载产物落回本地缓存。
  - 未配置 OSS 时（默认单机模式），本模块不参与任何路径，现有行为不变。
"""
from __future__ import annotations

from pathlib import Path

from . import config


class StorageError(RuntimeError):
    pass


class OssStorage:
    """阿里云 OSS 最小封装，惰性导入 oss2 以免强依赖。"""

    def __init__(self) -> None:
        try:
            import oss2
        except ImportError as exc:
            raise StorageError("缺少 oss2 依赖，请先 `pip install oss2`") from exc
        self._oss2 = oss2
        auth = oss2.Auth(config.OSS_ACCESS_KEY_ID, config.OSS_ACCESS_KEY_SECRET)
        self.bucket = oss2.Bucket(auth, config.OSS_ENDPOINT, config.OSS_BUCKET)

    def key(self, oss_path: str) -> str:
        path = oss_path.strip("/")
        return f"{config.OSS_PREFIX}/{path}" if config.OSS_PREFIX else path

    def upload(self, local_path: Path, oss_path: str) -> str:
        key = self.key(oss_path)
        self.bucket.put_object_from_file(key, str(local_path))
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

    def sign_get(self, oss_path: str, expires: int | None = None) -> str:
        key = self.key(oss_path)
        expiry = expires or config.OSS_URL_EXPIRES
        try:
            return self.bucket.sign_url("GET", key, expiry, slash_safe=True)
        except TypeError:
            return self.bucket.sign_url("GET", key, expiry)


class Storage:
    """门面：OSS 可用时提供对象存储操作，否则明确报错。"""

    def __init__(self) -> None:
        self._oss: OssStorage | None = None
        self._reason: str | None = None
        if config.OSS_BUCKET and config.OSS_ACCESS_KEY_ID and config.OSS_ACCESS_KEY_SECRET:
            try:
                self._oss = OssStorage()
            except Exception as exc:  # noqa: BLE001
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


storage = Storage()
