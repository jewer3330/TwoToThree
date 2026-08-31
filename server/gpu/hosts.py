"""GPU 主机注册表与状态管理（独立模块）。

主机配置持久化在 <DATA>/gpu_hosts.json（人类可编辑，新增机器=加一条配置）；
运行时状态（在线/GPU/能力/负载）保存在内存 _state，由 probe 线程周期刷新。
"""
from __future__ import annotations
import json, threading, time, uuid
from pathlib import Path
from ..core import DATA, dump, load, now

HOSTS_FILE=DATA/'gpu_hosts.json'
_lock=threading.RLock()
_state:dict[str,dict]={}   # host_id -> {online,gpu,memTotal,memUsed,diskFree,caps,lastProbeAt,lastError,runningJobs,queuedJobs}
_probe_pending:set[str]=set()

def _read()->list[dict]:
    if not HOSTS_FILE.exists():return []
    try:return json.loads(HOSTS_FILE.read_text(encoding='utf-8')).get('hosts',[])
    except Exception:return []

def _write(hosts:list[dict]):
    HOSTS_FILE.parent.mkdir(parents=True,exist_ok=True)
    HOSTS_FILE.write_text(json.dumps({'schemaVersion':1,'hosts':hosts},ensure_ascii=False,indent=2),encoding='utf-8')

def list_hosts()->list[dict]:
    with _lock:
        hosts=_read()
        for h in hosts: h['status']=_state.get(h['id'],{})
        return hosts

def get_host(host_id:str)->dict|None:
    with _lock:
        for h in _read():
            if h['id']==host_id:return h
        return None

def add_host(cfg:dict)->dict:
    with _lock:
        hosts=_read()
        if any(h['host']==cfg.get('host') for h in hosts):raise ValueError(f"主机 {cfg.get('host')} 已存在")
        host={'id':'gpu_'+uuid.uuid4().hex[:12],'name':cfg.get('name') or cfg.get('host'),'host':cfg['host'],
              'user':cfg.get('user','d0993'),'key':cfg.get('key',''),'root':cfg.get('root',''),
              'ext':cfg.get('ext',''),'work':cfg.get('work',''),'labels':cfg.get('labels') or [],
              'os':cfg.get('os') or 'windows','port':int(cfg.get('port') or 22),'password':cfg.get('password') or '',
              'maxConcurrentJobs':int(cfg.get('maxConcurrentJobs',1) or 1),'enabled':bool(cfg.get('enabled',True)),
              'createdAt':now()}
        hosts.append(host);_write(hosts)
        _probe_pending.add(host['id'])
        return host

def update_host(host_id:str,patch:dict)->dict:
    with _lock:
        hosts=_read();host=next((h for h in hosts if h['id']==host_id),None)
        if not host:raise KeyError('主机不存在')
        for k in ('name','user','key','root','ext','work','labels','maxConcurrentJobs','os','port','password'):
            if k in patch:host[k]=patch[k]
        if 'enabled' in patch:host['enabled']=bool(patch['enabled'])
        host.setdefault('createdAt',now())
        _write(hosts)
        if 'enabled' in patch:_probe_pending.add(host_id)
        return host

def delete_host(host_id:str):
    with _lock:
        hosts=_read();hosts=[h for h in hosts if h['id']!=host_id];_write(hosts)
        _state.pop(host_id,None)

def set_state(host_id:str,**kv):
    with _lock:
        s=_state.setdefault(host_id,{});s.update(kv);s['lastProbeAt']=now()

def set_running(host_id:str|None,delta:int):
    with _lock:
        if not host_id:return
        s=_state.setdefault(host_id,{});s['runningJobs']=max(0,int(s.get('runningJobs',0))+delta)

def set_queued(delta:int):
    with _lock:
        _state['_queue']={'queuedJobs':max(0,int(_state.get('_queue',{}).get('queuedJobs',0))+delta)}

def queue_state()->dict:
    with _lock:
        return dict(_state.get('_queue',{}))

def host_state(host_id:str)->dict:
    with _lock:return dict(_state.get(host_id,{}))

def request_probe(host_id:str):
    _probe_pending.add(host_id)

def pending_probes()->set[str]:
    with _lock:
        p=set(_probe_pending);_probe_pending.clear();return p

def summary()->dict:
    hosts=list_hosts();online=sum(1 for h in hosts if h['status'].get('online') and h['enabled'])
    gpu_total=0;gpu_used=0
    for h in hosts:
        s=h['status']
        if s.get('online'):
            gpu_total+=float(s.get('memTotal') or 0);gpu_used+=float(s.get('memUsed') or 0)
    return {'hostCount':len(hosts),'online':online,'enabled':sum(1 for h in hosts if h['enabled']),
            'gpuMemTotal':round(gpu_total),'gpuMemUsed':round(gpu_used),
            'runningJobs':sum(int(h['status'].get('runningJobs') or 0) for h in hosts)}
