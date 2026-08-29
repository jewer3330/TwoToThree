"""打印机状态探测线程（独立模块）。"""
from __future__ import annotations
import threading, time
from .bambu import BambuClient, parse_print
from . import registry

class PrinterProbeThread(threading.Thread):
    def __init__(self,interval:int=20):
        super().__init__(daemon=True,name='printer-probe')
        self.interval=interval
        self._stop=threading.Event()
    def stop(self):self._stop.set()
    def run(self):
        while not self._stop.wait(1):
            try:self._tick()
            except Exception:pass
    def _tick(self):
        now_t=int(time.monotonic())
        for p in registry.list_printers():
            if not p.get('enabled'):continue
            last=registry.printer_state(p['id']).get('_tick',0)
            if now_t-last<self.interval:continue
            try:
                client=BambuClient(p['ip'],p['accessCode'],p.get('serial') or None)
                res=client.fetch()
                if res['ok']:
                    parsed=parse_print(res['data'])
                    registry.set_state(p['id'],ok=True,status=parsed,error=None,_tick=now_t)
                else:
                    registry.set_state(p['id'],ok=False,status={},error=res['error'],_tick=now_t)
            except Exception as exc:
                registry.set_state(p['id'],ok=False,status={},error=str(exc)[:200],_tick=now_t)
