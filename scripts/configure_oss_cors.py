#!/usr/bin/env python3
"""为私有制品下载配置最小化 OSS CORS 规则。"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from oss2.models import BucketCors, CorsRule

from server.storage import storage


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--origin', action='append', required=True, help='允许的完整 Origin，可重复')
    args = parser.parse_args()
    origins = sorted({x.rstrip('/') for x in args.origin})
    rule = CorsRule(
        allowed_origins=origins,
        allowed_methods=['GET', 'HEAD'],
        allowed_headers=['Range', 'If-None-Match', 'If-Modified-Since'],
        expose_headers=['Accept-Ranges', 'Content-Length', 'Content-Range', 'Content-Type', 'ETag', 'Last-Modified'],
        max_age_seconds=86400,
    )
    storage.oss().bucket.put_bucket_cors(BucketCors([rule], response_vary=True))
    print('OSS CORS configured for: ' + ', '.join(origins))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
