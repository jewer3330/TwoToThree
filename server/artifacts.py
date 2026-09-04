"""最终制品的持久化契约：先落 OSS，再入业务表。"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .core import dump, load, sha256, storage_path
from .storage import resolve_transfer_backend, storage


def prepare_artifact(path: Path, mime_type: str, metadata: dict[str, Any] | None = None) -> tuple[str, int, str, str]:
    """返回数据库字段；OSS 模式下上传/校验失败会抛错，阻止任务假完成。"""
    digest = sha256(path)
    meta = dict(metadata or {})
    backend = resolve_transfer_backend()
    if backend == "oss":
        object_key = storage.store_artifact(path, digest, mime_type)
        meta.update({"storageBackend": "oss", "objectKey": object_key})
    else:
        meta.setdefault("storageBackend", "local")
    return storage_path(path), path.stat().st_size, digest, dump(meta)


def delivery_info(row: Any) -> tuple[str, str | None]:
    metadata = load(row["metadata"], {})
    backend = str(metadata.get("storageBackend") or "local")
    key = metadata.get("objectKey")
    return backend, str(key) if key else None
