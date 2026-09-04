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
_dynamic:dict[str,dict]={}  # 自注册节点（WebSocket dial-out，仅内存，不持久化到 gpu_hosts.json）
_probe_pending:set[str]=set()
# 网络类失败自动重试记簿：job_id -> 允许再次派发的最早时间（unix ts，进程内）
_net_retry:dict[str,float]={}
# 网络失败惩罚衰减窗口（秒）：一次失败后该主机在窗口内被调度降权/跳过
_FAIL_PENALTY_WINDOW=600
# 失败惩罚达到该值的主机在窗口内不再派发
_FAIL_MAX_STREAK=3

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
        for hid,h in _dynamic.items():
            h['status']=_state.get(hid,{})
            hosts.append(dict(h))
        return hosts

def register_dynamic(cfg:dict,status:dict|None=None)->dict:
    """登记一台自注册（WebSocket dial-out）节点，仅存内存、不写入 gpu_hosts.json。

    cfg 至少包含 id/name；可选 provider、maxConcurrentJobs、labels、caps、gpu 等。
    """
    with _lock:
        host={
            'id':cfg['id'],
            'name':cfg.get('name') or cfg['id'],
            'provider':cfg.get('provider','selfreg'),
            'enabled':bool(cfg.get('enabled',True)),
            'maxConcurrentJobs':int(cfg.get('maxConcurrentJobs',1) or 1),
            'labels':list(cfg.get('labels') or []),
            # 自注册节点无 SSH 字段，保留空值以兼容 probe/调度器数据结构
            'host':cfg.get('host',''),'user':cfg.get('user',''),'key':cfg.get('key',''),
            'root':cfg.get('root',''),'ext':cfg.get('ext',''),'work':cfg.get('work',''),
            'os':cfg.get('os','linux'),'port':int(cfg.get('port') or 22),'password':cfg.get('password',''),
            'createdAt':now(),
        }
        _dynamic[cfg['id']]=host
        if status is not None:_state[cfg['id']]=status
        return host

def unregister_dynamic(host_id:str):
    with _lock:
        _dynamic.pop(host_id,None)
        _state.pop(host_id,None)

def dynamic_host_ids()->list[str]:
    with _lock:return list(_dynamic.keys())

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
              'provider':cfg.get('provider','ssh'),
              'createdAt':now()}
        # AutoDL 节点附加字段（实例生命周期管理）
        if host['provider']=='autodl':
            host['instanceUuid']=cfg.get('instanceUuid','')
            host['token']=cfg.get('token','')
            host['transfer']=cfg.get('transfer','oss')  # 云实例无内网 CDN，默认 OSS 传输
        elif cfg.get('transfer'):
            host['transfer']=cfg.get('transfer')
        hosts.append(host);_write(hosts)
        _probe_pending.add(host['id'])
        return host

def update_host(host_id:str,patch:dict)->dict:
    with _lock:
        hosts=_read();host=next((h for h in hosts if h['id']==host_id),None)
        if not host:raise KeyError('主机不存在')
        for k in ('name','user','key','root','ext','work','labels','maxConcurrentJobs','os','port','password'):
            if k in patch:host[k]=patch[k]
        for k in ('provider','instanceUuid','token','transfer'):
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

def ensure_autodl_registered():
    """从 env 自动注册 AutoDL 算力节点（provider=autodl）。

    配了 AUTODL_TOKEN + AUTODL_INSTANCE_UUID 且没有对应节点时自动加入注册表，
    由调度器统一管理开机/空闲关机。幂等。
    """
    from .. import config
    if not (config.AUTODL_TOKEN and config.AUTODL_INSTANCE_UUID):
        return None
    with _lock:
        hosts=_read()
        for h in hosts:
            if h.get('provider')=='autodl' and h.get('instanceUuid')==config.AUTODL_INSTANCE_UUID:
                return h
        # 主机注册需要 host（SSH 地址）；env 未提供时给占位，探测会标记未就绪
        host=add_host({
            'name':config.AUTODL_NAME or 'AutoDL',
            'host':config.AUTODL_HOST or config.AUTODL_INSTANCE_UUID,
            'user':config.AUTODL_SSH_USER or 'root',
            'key':config.AUTODL_SSH_KEY or '',
            'root':config.AUTODL_REPO_ROOT or r'D:\print3d\TwoToThree',
            'ext':config.AUTODL_EXT_ROOT or r'D:\print3d',
            'work':config.AUTODL_WORK_DIR or r'D:\print3d\work',
            'provider':'autodl','instanceUuid':config.AUTODL_INSTANCE_UUID,
            'token':config.AUTODL_TOKEN,'transfer':'oss',
        })
        return host

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

# ---- 网络失败惩罚（调度按此降权/跳过不稳定节点）----
def record_host_failure(host_id:str):
    with _lock:
        s=_state.setdefault(host_id,{})
        s['failStreak']=int(s.get('failStreak',0))+1
        s['failStreakAt']=time.time()

def record_host_success(host_id:str):
    with _lock:
        s=_state.get(host_id)
        if s and s.get('failStreak'):
            s['failStreak']=0
            s.pop('failStreakAt',None)

def host_failure_streak(host_id:str)->int:
    """当前失败连击数；超过惩罚窗口自动按 0 处理（允许节点恢复后再次尝试）。"""
    with _lock:
        s=_state.get(host_id)
        if not s or not s.get('failStreak'):
            return 0
        if time.time()-(s.get('failStreakAt') or 0)>_FAIL_PENALTY_WINDOW:
            return 0
        return int(s['failStreak'])

# ---- 网络类任务自动重试记簿（job 级退避）----
def schedule_network_retry(job_id:str, delay_seconds:float=120.0):
    with _lock:
        _net_retry[job_id]=time.time()+max(10.0,float(delay_seconds))

def network_retry_ready(job_id:str)->bool:
    with _lock:
        due=_net_retry.get(job_id)
        if due is None:
            return True
        if time.time()>=due:
            _net_retry.pop(job_id,None)
            return True
        return False

def network_retry_delay(job_id:str)->float:
    """下次可派发还需等待的秒数（0=已就绪）。"""
    with _lock:
        due=_net_retry.get(job_id)
        if due is None:
            return 0.0
        return max(0.0,due-time.time())

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
