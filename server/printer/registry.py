"""打印机注册表（独立模块）。

配置持久化在 <DATA>/printers.json，人类可编辑。新增打印机=加一条配置。
"""
from __future__ import annotations
import json, threading, uuid
from pathlib import Path
from ..core import DATA, now

PRINTERS_FILE=DATA/'printers.json'
_lock=threading.RLock()
_state:dict[str,dict]={}   # printer_id -> {ok,error,status,...}

def _read()->list[dict]:
    if not PRINTERS_FILE.exists():return []
    try:return json.loads(PRINTERS_FILE.read_text(encoding='utf-8')).get('printers',[])
    except Exception:return []

def _write(printers:list[dict]):
    PRINTERS_FILE.parent.mkdir(parents=True,exist_ok=True)
    PRINTERS_FILE.write_text(json.dumps({'schemaVersion':1,'printers':printers},ensure_ascii=False,indent=2),encoding='utf-8')

def list_printers()->list[dict]:
    with _lock:
        out=[]
        for p in _read():
            d=dict(p);d['status']=_state.get(p['id'],{});out.append(d)
        return out

def get_printer(printer_id:str)->dict|None:
    with _lock:
        for p in _read():
            if p['id']==printer_id:return p
        return None

def add_printer(cfg:dict)->dict:
    with _lock:
        printers=_read()
        if any(p['ip']==cfg.get('ip') for p in printers):raise ValueError(f"打印机 {cfg.get('ip')} 已存在")
        printer={'id':'prn_'+uuid.uuid4().hex[:12],'name':cfg.get('name') or cfg.get('ip'),
                 'model':cfg.get('model','A1'),'ip':cfg['ip'],'accessCode':cfg.get('accessCode',''),
                 'serial':cfg.get('serial',''),'enabled':bool(cfg.get('enabled',True)),
                 'createdAt':now()}
        printers.append(printer);_write(printers)
        return printer

def update_printer(printer_id:str,patch:dict)->dict:
    with _lock:
        printers=_read();p=next((x for x in printers if x['id']==printer_id),None)
        if not p:raise KeyError('打印机不存在')
        for k in ('name','model','ip','accessCode','serial'):
            if k in patch:p[k]=patch[k]
        if 'enabled' in patch:p['enabled']=bool(patch['enabled'])
        _write(printers);return p

def delete_printer(printer_id:str):
    with _lock:
        printers=_read();_write([p for p in printers if p['id']!=printer_id]);_state.pop(printer_id,None)

def set_state(printer_id:str,**kv):
    with _lock:_state.setdefault(printer_id,{}).update(kv);_state[printer_id]['probedAt']=now()

def printer_state(printer_id:str)->dict:
    with _lock:return dict(_state.get(printer_id,{}))

def summary()->dict:
    printers=list_printers()
    online=sum(1 for p in printers if p['status'].get('ok') and p['enabled'])
    printing=sum(1 for p in printers if p['status'].get('status',{}).get('state')=='running')
    return {'printerCount':len(printers),'online':online,'printing':printing}
