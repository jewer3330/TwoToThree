"""总控侧 AutoDL 自动开机守护线程。

监控任务队列，当存在 queued 的 GPU 任务且显卡机（AutoDL Pro 实例）关机时，
调用 AutoDL API 开机；开机时可附带 start_command 让 worker 随实例启动。

闭环：
  总控 autostart 发现 queued 任务 → power_on（带 start_command 启动 worker）
  → 显卡机开机，worker 轮询认领任务 → 处理完空闲超时 → worker 自调 power_off
  → 回到第一步。
"""
from __future__ import annotations

import threading
import time

from . import config
from .autodl import AutoDlClient, AutoDlError
from .core import db, now

_check = threading.Lock()


def _has_pending_gpu_work() -> bool:
    with db() as con:
        jobs = con.execute("SELECT COUNT(*) FROM jobs WHERE status='queued'").fetchone()[0]
        refine = con.execute("SELECT COUNT(*) FROM refinement_jobs WHERE status='queued'").fetchone()[0]
        revisions = con.execute("SELECT COUNT(*) FROM revision_requests WHERE status='queued'").fetchone()[0]
        details = con.execute("SELECT COUNT(*) FROM detail_generation_jobs WHERE status='queued'").fetchone()[0]
    return (jobs + refine + revisions + details) > 0


def _autostart_loop() -> None:
    instance = config.AUTODL_INSTANCE_UUID
    poll = config.AUTOSTART_POLL_INTERVAL
    try:
        client = AutoDlClient()
    except AutoDlError as exc:
        print(f"[autostart] 未启用（{exc}）")
        return
    if not instance:
        print("[autostart] 未启用（缺少 AUTODL_INSTANCE_UUID）")
        return
    print(f"[autostart] 已启动：instance={instance}, poll={poll}s")
    while True:
        try:
            if _has_pending_gpu_work():
                if not client.is_running(instance):
                    print(f"[autostart] 发现待处理任务，开机 {instance}")
                    client.power_on(instance, config.AUTODL_START_COMMAND or None)
        except Exception as exc:  # noqa: BLE001
            print(f"[autostart] 轮询异常：{exc}")
        time.sleep(poll)


def start_autostart() -> None:
    if config.AUTODL_TOKEN and config.AUTODL_INSTANCE_UUID:
        t = threading.Thread(target=_autostart_loop, daemon=True, name="autodl-autostart")
        t.start()
