"""GPU 控制面板 API 路由（独立模块）。"""
from __future__ import annotations
import threading
from fastapi import APIRouter,HTTPException
from pydantic import BaseModel,Field
from . import hosts, scheduler
from ..backends import probe_host

router=APIRouter(prefix='/api/gpu',tags=['gpu'])

class HostInput(BaseModel):
    name:str|None=None;host:str=Field(min_length=3);user:str='d0993';key:str='';root:str='';ext:str='';work:str=''
    os:str='windows';port:int=22;password:str=''
    labels:list[str]=[];maxConcurrentJobs:int=1;enabled:bool=True
class HostPatch(BaseModel):
    name:str|None=None;user:str|None=None;key:str|None=None;root:str|None=None;ext:str|None=None;work:str|None=None
    os:str|None=None;port:int|None=None;password:str|None=None
    labels:list[str]|None=None;maxConcurrentJobs:int|None=None;enabled:bool|None=None

@router.get('/hosts')
def list_hosts():return hosts.list_hosts()

@router.post('/hosts',status_code=201)
def create_host(body:HostInput):
    try:return hosts.add_host(body.model_dump(exclude_none=True))
    except ValueError as exc:raise HTTPException(409,str(exc))

@router.patch('/hosts/{host_id}')
def patch_host(host_id:str,body:HostPatch):
    try:return hosts.update_host(host_id,body.model_dump(exclude_none=True))
    except KeyError:raise HTTPException(404,'主机不存在')

@router.delete('/hosts/{host_id}',status_code=204)
def remove_host(host_id:str):
    hosts.delete_host(host_id)

@router.post('/hosts/{host_id}/probe')
def probe(host_id:str):
    h=hosts.get_host(host_id)
    if not h:raise HTTPException(404,'主机不存在')
    status=probe_host(h)
    hosts.set_state(host_id,**status)
    return status

@router.post('/hosts/{host_id}/toggle')
def toggle(host_id:str):
    try:return hosts.update_host(host_id,{'enabled':not hosts.get_host(host_id)['enabled']})
    except KeyError:raise HTTPException(404,'主机不存在')

@router.get('/queue')
def queue():return scheduler.queue_view()

@router.post('/queue/pause')
def pause(body:dict|None=None):
    value=bool((body or {}).get('paused',not scheduler.queue_view()['paused']))
    scheduler.set_paused(value)
    return {'paused':value}

@router.get('/overview')
def overview():
    return {**hosts.summary(),'queue':scheduler.queue_view()['counts']}

def start_services():
    from .probe import ProbeThread
    ProbeThread(interval=30).start()
    scheduler.SchedulerThread().start()
