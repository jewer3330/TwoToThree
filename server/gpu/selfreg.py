"""GPU 节点自注册（WebSocket 长连接）。GPU 节点（肉鸡 / AutoDL / 任意 NAT 后的算力机）主动 dial-out 到控制面，
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
    {"type":"cmd_log","cmdId":"...","line":"..."}            # run_cmd 的 stdout 行
    {"type":"cmd_done","cmdId":"...","exitCode":0,"error":"..."}
    {"type":"upload_done","uploadId":"...","ok":true,"error":"..."}

  control → agent
    {"type":"hello_ack","nodeId":"..."}
    {"type":"pong"}
    {"type":"probe","probeId":"..."}
    {"type":"run_job","jobId":"...","config":{...}}
    {"type":"run_cmd","cmdId":"...","argv":[...],"cwd":"...","pull":[{"url","dest"}],"timeout":N}
    {"type":"upload_file","uploadId":"...","path":"...","pushUrl":"..."}   # 产物回传
"""
from __future__ import annotations
import asyncio, json, os, threading, time, uuid
from pathlib import Path
from fastapi import APIRouter, File, Request, UploadFile, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.responses import FileResponse, Response
from ..core import DATA
from . import hosts

router=APIRouter()
_lock=threading.RLock()
# node_id -> {"ws":WebSocket,"loop":asyncio.AbstractEventLoop,"node":dict,"lastSeenAt":float}
_agents:dict[str,dict]={}
_heartbeat_timeout=45.0
_stop=threading.Event()

# --------------------------------------------------------------------------- #
# run_cmd / upload_file 的同步桥（worker 线程阻塞等待 agent 结果）
# cmdId -> {"event":threading.Event, "exit_code":int, "error":str}
_cmd_waiters:dict[str,dict]={}
_upload_waiters:dict[str,dict]={}


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


# --------------------------------------------------------------------------- #
# v2 命令通道：worker 线程发 run_cmd，阻塞等 agent 的 cmd_done（同步桥）
# --------------------------------------------------------------------------- #
def _new_cmd_id() -> str:
    return f'cmd-{uuid.uuid4().hex[:12]}'


def _resolve_cmd(cmd_id:str, exit_code:int|None=None, error:str|None=None):
    """agent 回 cmd_done → 唤醒等待的 worker 线程。"""
    with _lock:
        waiter = _cmd_waiters.pop(cmd_id, None)
    if waiter:
        if exit_code is not None:
            waiter['exit_code'] = exit_code
        if error:
            waiter['error'] = error
        waiter['event'].set()


def run_command_sync(node_id:str, argv:list[str], *, cwd:str|None=None,
                     timeout:float=3600, log=None) -> tuple[int|None, str|None]:
    """向 agent 同步下发一条命令执行，阻塞直至完成或超时。

    worker 线程调用（与 WS 事件循环隔离）；agent stdout 逐行回传 cmd_log，
    通过 log 回调逐行转发（与 backends.Remote.run 的 log 语义对齐）。
    返回 (exit_code, error)。
    """
    cmd_id = _new_cmd_id()
    waiter = {'event': threading.Event(), 'exit_code': None, 'error': None, 'log_cb': log}
    with _lock:
        _cmd_waiters[cmd_id] = waiter
    ok = dispatch(node_id, {'type': 'run_cmd', 'cmdId': cmd_id, 'argv': list(argv),
                            'cwd': cwd, 'timeout': int(timeout)})
    if not ok:
        with _lock:
            _cmd_waiters.pop(cmd_id, None)
        return None, '节点离线或消息投递失败'
    # 等待完成（log 回调由 ws_endpoint 收到 cmd_log 时同步调用）
    if not waiter['event'].wait(timeout=max(30, timeout + 30)):
        with _lock:
            _cmd_waiters.pop(cmd_id, None)
        return None, f'命令执行超时（{timeout}s），节点可能卡死'
    return waiter['exit_code'], waiter['error']


def upload_file_sync(node_id:str, remote_path:str, timeout:float=600, upload_id:str|None=None) -> tuple[bool, str|None]:
    """请求 agent 把远端文件 POST 回控制面（产物回传）。

    worker 线程同步等待；成功后文件落在收件目录 inbox/<upload_id>/，由调用方取走。
    返回 (ok, error)。
    """
    upload_id = upload_id or f'up-{uuid.uuid4().hex[:12]}'
    waiter = {'event': threading.Event(), 'ok': False, 'error': None}
    with _lock:
        _upload_waiters[upload_id] = waiter
    ok = dispatch(node_id, {'type': 'upload_file', 'uploadId': upload_id,
                            'path': remote_path, 'timeout': int(timeout)})
    if not ok:
        with _lock:
            _upload_waiters.pop(upload_id, None)
        return False, '节点离线或消息投递失败'
    if not waiter['event'].wait(timeout=max(30, timeout + 30)):
        with _lock:
            _upload_waiters.pop(upload_id, None)
        return False, f'回传超时（{timeout}s）'
    return waiter['ok'], waiter['error']


def _resolve_upload(upload_id:str, ok:bool, error:str|None=None):
    with _lock:
        waiter = _upload_waiters.pop(upload_id, None)
    if waiter:
        waiter['ok'] = ok
        if error:
            waiter['error'] = error
        waiter['event'].set()


def fetch_files_sync(node_id:str, marker:str, dest_dir:str, timeout:float=120) -> tuple[bool, str|None]:
    """让 agent 把控制面 pullbox/<marker> 下的输入文件拉取到节点本地 dest_dir。

    返回 (ok, error)。agent 用 HTTP GET {control}/api/gpu/selfreg/pullbox/{marker}/{name}
    逐个下载；控制面 URL 由 agent 端自行拼接（它知道自己连的 CONTROL_URL）。
    """
    pullbox = DATA / 'selfreg' / 'pullbox' / marker
    if not pullbox.exists():
        return False, f'pullbox 不存在：{marker}'
    names = sorted(p.name for p in pullbox.iterdir() if p.name != '.manifest' and p.is_file())
    if not names:
        return True, None
    waiter = {'event': threading.Event(), 'ok': False, 'error': None}
    fid = f'fetch-{uuid.uuid4().hex[:12]}'
    with _lock:
        _upload_waiters[fid] = waiter   # 复用 waiters 机制等待 fetch_done
    ok = dispatch(node_id, {'type': 'fetch_files', 'fetchId': fid, 'marker': marker,
                            'files': names, 'destDir': dest_dir})
    if not ok:
        with _lock:
            _upload_waiters.pop(fid, None)
        return False, '节点离线或消息投递失败'
    if not waiter['event'].wait(timeout=timeout):
        with _lock:
            _upload_waiters.pop(fid, None)
        return False, '输入下发超时'
    return waiter['ok'], waiter['error']


# --------------------------------------------------------------------------- #
# 文件收发（产物回传收件 / 输入下发）
# --------------------------------------------------------------------------- #
def inbox_root(upload_id:str) -> Path:
    """agent 回传文件的收件目录。worker 用 upload_file_sync 等它到达后取文件。"""
    return DATA / 'selfreg' / 'inbox' / upload_id


def _require_worker_token(request: Request):
    """机器通道鉴权：与 /api/gpu/ws 握手一致，校验 X-Worker-Token。

    控制面设置了 WORKER_TOKEN 时必须匹配，否则 401（fail-closed）；
    未设置（本地开发/测试）时放行。供 pullbox/inbox 数据面端点使用。
    """
    from .. import config
    if not config.WORKER_TOKEN:
        return
    if (request.headers.get('x-worker-token') or '') != config.WORKER_TOKEN:
        raise HTTPException(401, 'invalid or missing worker token')


@router.post('/api/gpu/selfreg/upload/{upload_id}')
async def selfreg_upload(upload_id:str, request:Request, file:UploadFile=File(...)):
    """agent 回传产物：POST multipart 到 /api/gpu/selfreg/upload/<uploadId>。
    落盘到收件目录，随后 worker 的 upload_file_sync 唤醒取走。"""
    _require_worker_token(request)
    root = inbox_root(upload_id)
    root.mkdir(parents=True, exist_ok=True)
    safe = Path(file.filename or 'payload.bin').name
    if safe != (file.filename or ''):
        raise HTTPException(400, '非法文件名')
    dest = root / safe
    with dest.open('wb') as out:
        while chunk := await file.read(1024 * 1024):
            out.write(chunk)
    return {'ok': True, 'stored': dest.name, 'size': dest.stat().st_size}


@router.get('/api/gpu/selfreg/upload/{upload_id}')
def selfreg_upload_status(upload_id:str, request:Request):
    _require_worker_token(request)
    root = inbox_root(upload_id)
    return {'exists': root.exists() and any(root.iterdir()) if root.exists() else False,
            'files': [p.name for p in root.iterdir()] if root.exists() else []}


@router.get('/api/gpu/selfreg/pullbox/{marker}/{filename}')
def selfreg_pullbox(marker:str, filename:str, request:Request):
    """agent 下载控制面下发的输入文件（对应 SelfregRemote.prepare 的 pullbox）。"""
    _require_worker_token(request)
    root = DATA / 'selfreg' / 'pullbox' / marker
    safe = Path(filename).name
    if safe != filename:
        raise HTTPException(400, '非法文件名')
    path = root / safe
    if not path.exists():
        raise HTTPException(404, 'pullbox 文件不存在')
    return FileResponse(path, filename=safe)



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
            elif mtype=='cmd_log':
                # stdout 行 → 触发注册在该 cmdId 上的 log 回调（worker 线程等待中）
                cmd_id=msg.get('cmdId');line=msg.get('line','')
                with _lock:
                    waiter=_cmd_waiters.get(cmd_id)
                    log_cb = waiter.get('log_cb') if waiter else None
                if log_cb:
                    try: log_cb(line)
                    except Exception: pass
            elif mtype=='cmd_done':
                _resolve_cmd(msg.get('cmdId'), exit_code=msg.get('exitCode'),
                             error=msg.get('error'))
            elif mtype=='upload_done':
                _resolve_upload(msg.get('uploadId'), bool(msg.get('ok')),
                                error=msg.get('error'))
            elif mtype=='fetch_done':
                _resolve_upload(msg.get('fetchId'), bool(msg.get('ok')),
                                error=msg.get('error'))
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
