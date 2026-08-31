"""任务队列调度器（独立模块）。

将 queued 任务按能力/并发/启用状态分配到可用 GPU 主机，
在独立线程中执行 worker.run(job_id, host_id)。新机器只需在 hosts 注册即可被调度。
"""
from __future__ import annotations
import json, threading, time
from ..core import db, dump, load, now, uid
from ..backends import bind_host
from . import hosts

_lock=threading.RLock()
_paused=False
_threads:dict[str,threading.Thread]={}

def set_paused(value:bool):global _paused;_paused=value

def any_online_host()->bool:
    return any(h.get('enabled') and h.get('status',{}).get('online') for h in hosts.list_hosts())

def _running_counts()->dict[str,int]:
    with db() as con:
        rows=con.execute("SELECT gpu_host_id,COUNT(*) c FROM jobs WHERE status='running' AND gpu_host_id IS NOT NULL GROUP BY gpu_host_id").fetchall()
        return {r['gpu_host_id']:r['c'] for r in rows}

def _queued_jobs():
    with db() as con:
        rows=con.execute("SELECT * FROM jobs WHERE status='queued' ORDER BY created_at").fetchall()
        return [dict(r) for r in rows]

def _pick_host(job:dict):
    config=load(job['config_snapshot'],{})
    requested=[config.get('primaryBackend','hunyuan3d'),*config.get('fallbackBackends',['sf3d','triposr'])]
    with db() as con:
        multi=con.execute('SELECT COUNT(*) c FROM assets WHERE project_id=? AND role IN (\'side\',\'back\') AND active=1',(job['project_id'],)).fetchone()['c']
    # 按延迟升序排序（低延迟优先，直连优于 relay）
    candidates=sorted(hosts.list_hosts(),key=lambda h:(
        h.get('status',{}).get('latencyMs') if h.get('status',{}).get('latencyMs') is not None else 10**6,
        h.get('name','')))
    for backend in dict.fromkeys(requested):
        for h in candidates:
            if not h.get('enabled'):continue
            s=h.get('status',{})
            if not s.get('online'):continue
            caps=s.get('caps',{})
            if not caps.get(backend):continue
            if backend=='hunyuan3d' and multi and not caps.get('hunyuan3dMultiview'):continue
            if s.get('runningJobs',0)>=int(h.get('maxConcurrentJobs',1)):continue
            return h,backend
    return None,None

def _dispatcher():
    while True:
        try:
            if not _paused:
                _autodl_lifecycle()
                for job in _queued_jobs():
                    host,backend=_pick_host(job)
                    if not host:break
                    if _claim(job,host):_spawn(job,host)
        except Exception:pass
        time.sleep(5)


# --------------------------------------------------------------------------- #
# AutoDL 算力节点生命周期（开机/空闲关机），替代原 autostart 独立线程
# --------------------------------------------------------------------------- #
def _has_queued_work()->bool:
    with db() as con:
        jobs=con.execute("SELECT COUNT(*) FROM jobs WHERE status='queued'").fetchone()[0]
        refine=con.execute("SELECT COUNT(*) FROM refinement_jobs WHERE status='queued'").fetchone()[0]
        revisions=con.execute("SELECT COUNT(*) FROM revision_requests WHERE status='queued'").fetchone()[0]
        details=con.execute("SELECT COUNT(*) FROM detail_generation_jobs WHERE status='queued'").fetchone()[0]
    return (jobs+refine+revisions+details)>0


def _power_on_autodl(host:dict):
    from ..autodl import AutoDlClient
    client=AutoDlClient(host.get('token') or None)
    client.power_on(host['instanceUuid'], None)
    hosts.set_state(host['id'],bootRequestedAt=time.time())
    print(f"[gpu-scheduler] AutoDL 开机：{host.get('name')} ({host['instanceUuid']})")


def _power_off_autodl(host:dict):
    from ..autodl import AutoDlClient
    client=AutoDlClient(host.get('token') or None)
    client.power_off(host['instanceUuid'])
    hosts.set_state(host['id'],shutdownRequestedAt=time.time())
    print(f"[gpu-scheduler] AutoDL 空闲关机：{host.get('name')} ({host['instanceUuid']})")


def _autodl_lifecycle():
    """AutoDL 节点生命周期：有 queued 任务且实例关机 → 开机（幂等）；
    在线但空闲超 AUTODL_IDLE_TIMEOUT → 关机。"""
    from .. import config
    autodl=[h for h in hosts.list_hosts() if h.get('provider')=='autodl' and h.get('enabled')]
    if not autodl:return
    has_work=_has_queued_work()
    idle_timeout=float(config.AUTODL_IDLE_TIMEOUT or 0)
    for h in autodl:
        s=h.get('status',{})
        try:
            state=s.get('autodlState','')
            if has_work and state!='running' and not s.get('bootRequestedAt'):
                _power_on_autodl(h)
                continue
            if idle_timeout>0 and state=='running' and s.get('runningJobs',0)==0:
                last_activity=s.get('lastActivityAt') or 0.0
                if last_activity and (time.time()-last_activity)>idle_timeout:
                    _power_off_autodl(h)
        except Exception as exc:
            print(f"[gpu-scheduler] AutoDL 生命周期异常：{exc}")

def _claim(job:dict,host:dict)->bool:
    with _lock:
        with db() as con:
            cur=con.execute("SELECT status FROM jobs WHERE id=?",(job['id'],)).fetchone()
            if not cur or cur['status']!='queued':return False
            con.execute("UPDATE jobs SET status='dispatched',gpu_host_id=? WHERE id=?",(host['id'],job['id']))
            con.execute("UPDATE projects SET status='queued',updated_at=? WHERE id=?",(now(),job['project_id']))
            con.execute("INSERT INTO events(job_id,event_type,payload,created_at) VALUES(?,?,?,?)",(job['id'],'job.dispatched',dump({'hostId':host['id'],'host':host.get('name'),'backend':backend_for(job)}),now()))
        hosts.set_running(host['id'],+1)
        hosts.set_state(host['id'],lastActivityAt=time.time())
        return True

def backend_for(job:dict)->str:
    config=load(job['config_snapshot'],{})
    return config.get('primaryBackend','hunyuan3d')

def _spawn(job:dict,host:dict):
    def run_wrapper():
        from ..worker import run as worker_run
        try:
            bind_host(host)
            worker_run(job['id'])
        except Exception:pass
        finally:
            bind_host(None)
            hosts.set_running(host['id'],-1)
    t=threading.Thread(target=run_wrapper,daemon=True,name=f'gpu-job-{job["id"][-6:]}-{host["id"][-6:]}')
    _threads[job['id']]=t
    t.start()

class SchedulerThread(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True,name='gpu-scheduler')
    def run(self):_dispatcher()

def queue_view():
    """控制面板队列视图：排队/运行/最近任务。"""
    with db() as con:
        queued=con.execute("SELECT id,project_id,status,created_at,current_stage,gpu_host_id FROM jobs WHERE status IN ('queued','dispatched') ORDER BY created_at").fetchall()
        running=con.execute("SELECT id,project_id,status,created_at,current_stage,gpu_host_id FROM jobs WHERE status IN ('running','awaiting_geometry_confirmation') ORDER BY created_at DESC").fetchall()
        recent=con.execute("SELECT id,project_id,status,created_at,completed_at,error_summary,gpu_host_id FROM jobs WHERE status IN ('completed','failed','cancelled') ORDER BY COALESCE(completed_at,created_at) DESC LIMIT 10").fetchall()
        host_names={h['id']:h.get('name') for h in hosts.list_hosts()}
    def decorate(rows):
        out=[]
        for r in rows:
            d=dict(r);d['hostName']=host_names.get(d.pop('gpu_host_id','')) or ''
            out.append(d)
        return out
    counts={'queued':len(queued),'running':len(running)}
    return {'paused':_paused,'counts':counts,'queued':decorate(queued),'running':decorate(running),'recent':decorate(recent)}
