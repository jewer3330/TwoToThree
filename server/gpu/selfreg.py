"""GPU 节点自注册（WebSocket 长连接）。

GPU 节点（肉鸡 / AutoDL / 任意 NAT 后的算力机）主动 dial-out 到控制面，
注册自己的身份与能力；之后控制面通过同一条长连接下发任务、接收进度回传。

这解决了 SSH「推」模式在 CGNAT/动态 IP 下进不去的痛点——节点只需出站连接，
无需公网 IP、无需开入站端口、控制面无需持有每台节点的 SSH 凭据。

消息协议（JSON 文本帧）：

  agent → control
    {"type":"hello","token":"<WORKER_TOKEN>","node":{"id","name","caps":{...},"gpu":{...},"memTotal","memUsed","diskFree","maxConcurrentJobs","labels"}}
    {"type":"ping"}
    {"type":"probe_result","probeId":"...","caps":{...},"gpu":"...","memTotal":..,"memUsed":..,"diskFree":..}
    {"type":"job_event","jobId":"...","kind":"log|stage|status","payload":{...}}
    {"type":"job_result","jobId":"...","ok":true,"result":{...}} | {"ok":false,"error":"..."}

  control → agent
    {"type":"hello_ack","nodeId":"..."}
    {"type":"pong"}
    {"type":"probe","probeId":"..."}
    {"type":"run_job","jobId":"...","config":{...}}
"""
from __future__ import annotations
import asyncio, threading, time, uuid
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from . import hosts

router=APIRouter()
_lock=threading.RLock()
# node_id -> {"ws":WebSocket,"loop":asyncio.AbstractEventLoop,"node":dict,"lastSeenAt":float}
_agents:dict[str,dict]={}
_heartbeat_timeout=45.0
_stop=threading.Event()


def _register(node:dict):
    caps=node.get('caps') or {}
    with _lock:
        hosts.register_dynamic({
            'id':node['id'],'name':node.get('name') or node['id'],
            'provider':'selfreg','maxConcurrentJobs':int(node.get('maxConcurrentJobs',1) or 1),
            'labels':list(node.get('labels') or []),'os':node.get('os','linux'),
        }, {
            'online':True,'route':'selfreg',
            'gpu':node.get('gpu'),'memTotal':node.get('memTotal'),'memUsed':node.get('memUsed'),
            'diskFree':node.get('diskFree'),'caps':caps,
            'latencyMs':None,'lastError':None,'lastProbeAt':None,
        })


def _unregister(node_id:str):
    with _lock:
        hosts.unregister_dynamic(node_id)


def _stamp(agent:dict):
    agent['lastSeenAt']=time.monotonic()
    with _lock:
        hosts.set_state(agent['node']['id'],lastSeenAt=time.time())


def list_agents()->list[dict]:
    with _lock:
        out=[]
        for agent in _agents.values():
            node=dict(agent['node'])
            node['online']=True
            node['provider']='selfreg'
            node['lastSeenAgo']=round(time.monotonic()-agent.get('lastSeenAt',0),1)
            out.append(node)
        return out


def dispatch(node_id:str,message:dict)->bool:
    """从任意线程向某个在线 agent 下发一条消息。返回是否成功投递。"""
    with _lock:
        agent=_agents.get(node_id)
    if not agent:
        return False
    try:
        fut=asyncio.run_coroutine_threadsafe(agent['ws'].send_json(message),agent['loop'])
        fut.result(timeout=10)
        return True
    except Exception:
        return False


def probe(node_id:str)->bool:
    """请求 agent 立即回传能力快照（替代 SSH 探测）。"""
    return dispatch(node_id,{'type':'probe','probeId':f'probe-{uuid.uuid4().hex[:8]}'})


def _monitor_loop():
    while not _stop.wait(5):
        now=time.monotonic()
        stale=[]
        with _lock:
            for node_id,agent in _agents.items():
                if now-agent.get('lastSeenAt',0)>_heartbeat_timeout:
                    stale.append(node_id)
        for node_id in stale:
            _unregister(node_id)
            print(f'[selfreg] 节点 {node_id} 心跳超时，已标记离线')


def start_monitor():
    threading.Thread(target=_monitor_loop,daemon=True,name='selfreg-monitor').start()


@router.websocket('/api/gpu/ws')
async def ws_endpoint(ws:WebSocket):
    await ws.accept()
    node_id=None
    try:
        hello=await ws.receive_json()
        if hello.get('type')!='hello':
            await ws.send_json({'type':'error','error':'expected hello'})
            return
        from .. import config
        token=hello.get('token') or ''
        if config.WORKER_TOKEN and token!=config.WORKER_TOKEN:
            await ws.send_json({'type':'error','error':'invalid worker token'})
            await ws.close(code=4401)
            return
        node=hello.get('node') or {}
        node_id=node.get('id') or f'selfreg-{uuid.uuid4().hex[:8]}'
        node['id']=node_id
        agent={'ws':ws,'loop':asyncio.get_running_loop(),'node':node,'lastSeenAt':time.monotonic()}
        with _lock:
            _agents[node_id]=agent
        _register(node)
        _stamp(agent)
        await ws.send_json({'type':'hello_ack','nodeId':node_id})
        print(f'[selfreg] 节点上线：{node_id}（{node.get("name","")}），能力={sorted((node.get("caps") or {}).keys())}')

        while True:
            msg=await ws.receive_json()
            _stamp(agent)
            mtype=msg.get('type')
            if mtype=='ping':
                await ws.send_json({'type':'pong'})
            elif mtype=='probe_result':
                status={'online':True,'route':'selfreg','gpu':msg.get('gpu'),
                        'memTotal':msg.get('memTotal'),'memUsed':msg.get('memUsed'),
                        'diskFree':msg.get('diskFree'),'caps':msg.get('caps') or {},
                        'latencyMs':None,'lastError':None,'lastProbeAt':time.time()}
                with _lock:
                    hosts.set_state(node_id,**status)
            elif mtype=='job_event':
                _handle_job_event(node_id,msg)
            elif mtype=='job_result':
                _handle_job_result(node_id,msg)
            else:
                await ws.send_json({'type':'error','error':f'unknown message type: {mtype}'})
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        print(f'[selfreg] 节点 {node_id} 连接异常：{exc}')
    finally:
        if node_id:
            with _lock:
                _agents.pop(node_id,None)
            _unregister(node_id)
            print(f'[selfreg] 节点下线：{node_id}')


def _handle_job_event(node_id:str,msg:dict):
    """把 agent 回传的进度/日志事件写进控制面 DB（跨机时由这里落库）。

    v1 约定：agent 与控制面共享同一份 SQLite（同机 / NFS / 或后续 OSS 交换），
    agent 本地 worker.run 已直接写库，这里仅做日志记录；跨机事件回传在 v2 落地。
    """
    job_id=msg.get('jobId');kind=msg.get('kind');payload=msg.get('payload') or {}
    # 任务进入终态 → 释放节点运行计数，允许调度器继续派发
    if kind=='status' and str(payload.get('status')) in ('completed','failed','cancelled','transfer_pending'):
        hosts.set_running(node_id,-1)
    print(f'[selfreg] {node_id} job_event {job_id} {kind}: {str(payload)[:200]}')


def _handle_job_result(node_id:str,msg:dict):
    job_id=msg.get('jobId');ok=bool(msg.get('ok'))
    hosts.set_running(node_id,-1)
    if ok:
        print(f'[selfreg] {node_id} job_result {job_id}: ok')
    else:
        print(f'[selfreg] {node_id} job_result {job_id}: failed: {msg.get("error")}')
