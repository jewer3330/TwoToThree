"""selfreg.py 同步桥可靠性回归测试（WS 通知可能丢失场景）。"""
import threading
import time
from pathlib import Path

import pytest


def _patch_waiter_table(monkeypatch, tmp_path):
    from server.gpu import selfreg as sr
    # 让 inbox 指向隔离临时目录
    monkeypatch.setattr(sr, 'DATA', tmp_path / 'data')
    (tmp_path / 'data' / 'selfreg' / 'inbox').mkdir(parents=True, exist_ok=True)
    return sr


def test_upload_succeeds_via_inbox_poll_even_without_done(monkeypatch, tmp_path):
    """upload_done WS 通知丢失时，只要文件已落 inbox 就必须返回成功（不再卡死）。"""
    sr = _patch_waiter_table(monkeypatch, tmp_path)
    dispatched = {}
    received = {}

    def fake_dispatch(node_id, message):
        dispatched['m'] = message
        upload_id = message['uploadId']
        # 模拟 agent：POST 文件到 inbox 成功，但 upload_done 通知丢失（不发）
        root = sr.inbox_root(upload_id)
        root.mkdir(parents=True, exist_ok=True)
        (root / 'out.glb').write_bytes(b'GLB')
        # 另起线程模拟后续才落盘（验证轮询等待，而非立即返回）
        def _later():
            time.sleep(0.3)
            (root / 'out.glb').write_bytes(b'GLB-DONE')
        threading.Thread(target=_later, daemon=True).start()
        return True

    monkeypatch.setattr(sr, 'dispatch', fake_dispatch)
    ok, err = sr.upload_file_sync('n1', r'D:\w\out.glb', timeout=30)
    assert ok is True and err is None
    assert dispatched['m']['type'] == 'upload_file'


def test_upload_times_out_when_no_file_and_no_done(monkeypatch, tmp_path):
    """文件既未到达也未回通知 → 超时返回失败（而不是无限等）。"""
    sr = _patch_waiter_table(monkeypatch, tmp_path)
    monkeypatch.setattr(sr, 'dispatch', lambda n, m: True)   # agent 无任何响应
    t0 = time.monotonic()
    ok, err = sr.upload_file_sync('n1', r'D:\w\out.glb', timeout=2)
    assert ok is False and '超时' in (err or '')
    # wait 下限 30s × 3 次重试 + 重试间隔 ≤ ~115s；确认不会无限等待
    assert time.monotonic() - t0 < 130


def test_upload_done_fast_path(monkeypatch, tmp_path):
    """正常路径：agent 回 upload_done → 直接成功。"""
    sr = _patch_waiter_table(monkeypatch, tmp_path)
    real_resolve = sr._resolve_upload

    def fake_dispatch(node_id, message):
        upload_id = message['uploadId']
        threading.Thread(target=lambda: (
            time.sleep(0.2), real_resolve(upload_id, True, None)), daemon=True).start()
        return True

    monkeypatch.setattr(sr, 'dispatch', fake_dispatch)
    ok, err = sr.upload_file_sync('n1', r'D:\w\out.glb', timeout=30)
    assert ok is True and err is None
