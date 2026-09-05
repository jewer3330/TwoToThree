"""GPU 主机健康探测线程（独立模块）。

每台主机一个独立探测线程（互不阻塞），单次探测带硬超时；
结果写入 hosts._state，供控制面板与调度器读取。
"""
from __future__ import annotations
import threading, time
from ..backends import probe_host
from . import hosts

class _ProbeWorker(threading.Thread):
    def __init__(self,h:dict,deep:bool=False):
        super().__init__(daemon=True,name=f'gpu-probe-{h["id"][-6:]}')
        self.h=h;self.deep=deep
    def run(self):
        try:
            status=probe_host(self.h,deep=self.deep)
        except Exception as exc:
            status={'online':False,'lastError':str(exc)[:200]}
        status['_tick']=int(time.monotonic())
        # AutoDL 实例已运行 → 开机请求完成，允许下次调度触发新的开机
        if status.get('autodlState')=='running':
            status['bootRequestedAt']=None
            status['shutdownRequestedAt']=None
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
        pending_ids=hosts.pending_probes()   # 一次性取走全部待深检主机
        hosts_list=hosts.list_hosts()
        for h in hosts_list:
            if not h.get('enabled'):continue
            # 自注册节点走 WebSocket 心跳（selfreg.py），不适用 SSH 探测；
            # 探测会把 online/caps 覆盖成 offline/空，破坏调度器的能力匹配。
            if h.get('provider')=='selfreg':continue
            s=h.get('status',{})
            pending=h['id'] in pending_ids
            # pending（启用/新注册）→ 深检一次拿真实 health/caps；周期轮询浅探
            if pending or not s.get('lastProbeAt') or (now-int(s.get('_tick',0)))>=self.interval:
                _ProbeWorker(h,deep=pending).start()
