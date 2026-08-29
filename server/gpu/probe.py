"""GPU 主机健康探测线程（独立模块）。

每台主机一个独立探测线程（互不阻塞），单次探测带硬超时；
结果写入 hosts._state，供控制面板与调度器读取。
"""
from __future__ import annotations
import threading, time
from ..backends import probe_host
from . import hosts

class _ProbeWorker(threading.Thread):
    def __init__(self,h:dict):
        super().__init__(daemon=True,name=f'gpu-probe-{h["id"][-6:]}')
        self.h=h
    def run(self):
        try:
            status=probe_host(self.h)
        except Exception as exc:
            status={'online':False,'lastError':str(exc)[:200]}
        status['_tick']=int(time.monotonic())
        hosts.set_state(self.h['id'],**status)

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
        for h in hosts_list:
            if not h.get('enabled'):continue
            s=h.get('status',{})
            if h['id'] in hosts.pending_probes() or not s.get('lastProbeAt') or (now-int(s.get('_tick',0)))>=self.interval:
                _ProbeWorker(h).start()
