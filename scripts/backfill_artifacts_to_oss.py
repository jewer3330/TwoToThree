#!/usr/bin/env python3
"""将已有本地制品内容寻址上传 OSS，并回写投递元数据。"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from server.artifacts import prepare_artifact
from server.core import db, load, resolve_storage


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    changed = missing = failed = 0
    for table in ('artifacts', 'refinement_artifacts'):
        with db() as con:
            rows = con.execute(f'SELECT id,storage_path,mime_type,metadata FROM {table} ORDER BY created_at').fetchall()
        for row in rows:
            meta = load(row['metadata'], {})
            if meta.get('storageBackend') == 'oss' and meta.get('objectKey'):
                continue
            path = resolve_storage(row['storage_path'])
            if not path.is_file():
                missing += 1
                print(f'MISSING {table}:{row["id"]} {row["storage_path"]}')
                continue
            if args.dry_run:
                print(f'WOULD_UPLOAD {table}:{row["id"]} {path.stat().st_size}')
                changed += 1
                continue
            try:
                _, _, _, packed = prepare_artifact(path, row['mime_type'], meta)
                with db() as con:
                    con.execute(f'UPDATE {table} SET metadata=? WHERE id=?', (packed, row['id']))
                changed += 1
                print(f'UPLOADED {table}:{row["id"]} {path.stat().st_size}')
            except Exception as exc:
                failed += 1
                print(f'FAILED {table}:{row["id"]} {exc}')
    print(f'SUMMARY changed={changed} missing={missing} failed={failed}')
    return 1 if failed else 0


if __name__ == '__main__':
    raise SystemExit(main())
