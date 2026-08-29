"""GPU 主机健康探测线程（独立模块）。

周期扫描所有启用主机，把探测结果写入 hosts._state，供控制面板与调度器读取。
"""
from __future__ import annotations
import threading, time
from ..backends import probe_host
from . import hosts

class ProbeThread(threading.Thread):
    def __init__(self,interval:int=30):
        super().__init__(daemon=True,name='gpu-probe')
        self.interval=interval
        self._stop=threading.Event()
    def stop(self):self._stop.set()
    def run(self):
        while not self._stop.wait(1):
            try:self._tick()
            except Exception:pass
    def _tick(self):
        now=int(time.monotonic())
        hosts_list=hosts.list_hosts()
        # 优先探测：新添加 / 明确请求 / 超时未探
        due=[h for h in hosts_list if h['id'] in hosts.pending_probes() or not h.get('status',{}).get('lastProbeAt') or (now-int(h.get('status',{}).get('_tick',0)))>=self.interval]
        for h in due:
            if not h.get('enabled'):continue
            try:
                status=probe_host(h)
            except Exception as exc:
                status={'online':False,'lastError':str(exc)[:200]}
            status['_tick']=now
            hosts.set_state(h['id'],**status)
