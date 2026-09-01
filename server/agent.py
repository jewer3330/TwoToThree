"""GPU 节点自注册 Agent（常驻进程）。

启动即主动连出（dial-out）到控制面的 WebSocket 端点，注册本机身份与能力，
之后维持心跳、响应能力探测、接收并执行控制面下发的生成任务。

适用任意 NAT / CGNAT / 动态 IP 后的算力机（AutoDL、自有机等），无需公网 IP
或入站端口。运行方式：

    CONTROL_URL=http://127.0.0.1:8000 WORKER_TOKEN=xxx \
        .venv/bin/python -m server.agent

环境变量：
  CONTROL_URL       控制面 API 根地址（http/https），必填
  WORKER_TOKEN      控制面↔节点鉴权令牌（控制面未设置时可省略）
  AGENT_NAME        节点显示名（默认 hostname）
  AGENT_ID          节点稳定 id（默认 agent-<hostname>）
  AGENT_MAX_JOBS    并发任务上限（默认 1）
"""
from __future__ import annotations
import asyncio, json, os, socket, subprocess, sys, time
from pathlib import Path

try:
    import websockets
except ImportError:
    sys.stderr.write('缺少 websockets 依赖：pip install websockets\n')
    raise


def _env(name:str,default:str='')->str:
    v=os.environ.get(name)
    return v if v not in (None,'') else default


CONTROL_URL=_env('CONTROL_URL').rstrip('/')
WORKER_TOKEN=_env('WORKER_TOKEN')
AGENT_NAME=_env('AGENT_NAME',socket.gethostname())
AGENT_ID=_env('AGENT_ID',f'agent-{socket.gethostname()}')
AGENT_MAX_JOBS=int(_env('AGENT_MAX_JOBS','1') or '1')
# 逗号分隔的能力名，覆盖自动探测结果（测试/声明式能力；如 hunyuan3d,blender）
AGENT_CAPS_OVERRIDE=_env('AGENT_CAPS_OVERRIDE','')


def _ws_url()->str:
    if not CONTROL_URL:
        raise RuntimeError('缺少 CONTROL_URL（例如 http://8.153.36.240:8000）')
    scheme='wss' if CONTROL_URL.startswith('https://') else 'ws'
    rest=CONTROL_URL.split('://',1)[1]
    return f'{scheme}://{rest}/api/gpu/ws'


def _gpu_snapshot()->tuple[str|None,int|None,int|None]:
    """读取本机 GPU 型号与显存（无 nvidia-smi 时返回空）。"""
    try:
        out=subprocess.run(['nvidia-smi','--query-gpu=name,memory.total,memory.used',
                            '--format=csv,noheader,nounits'],
                           capture_output=True,text=True,timeout=5).stdout.strip()
        if not out:return None,None,None
        parts=[p.strip() for p in out.split(',')]
        if len(parts)>=3:
            return parts[0],int(float(parts[1])),int(float(parts[2]))
        return parts[0],None,None
    except Exception:
        return None,None,None


def _disk_free()->float|None:
    try:
        import shutil
        root=Path(os.environ.get('STUDIO_EXTERNAL_ROOT',Path.home()/'AIData'/'3d'))
        return round(shutil.disk_usage(root).free/1073741824,1)
    except Exception:
        return None


def _capabilities()->dict:
    """本机能力检测（OS 感知，基于 studio_paths 布局）。

    不能直接复用 backends.capabilities()：它在 local 模式硬编码 Windows 路径，
    在 Linux 节点（AutoDL 等）会全部误报 False。这里按当前 OS 探测实际路径。
    """
    caps={}
    try:
        from studio_paths import LOCAL_ROOT
        win=os.name=='nt'
        py=LOCAL_ROOT/'hunyuan-bootstrap'/('Scripts' if win else 'bin')/('python.exe' if win else 'python')
        blender=LOCAL_ROOT/('Blender52' if win else 'blender')/('blender.exe' if win else 'blender')
        model=LOCAL_ROOT/'Hunyuan3D-2.1-model'
        mv_model=LOCAL_ROOT/'Hunyuan3D-2mv-model-v2'
        repo=Path(__file__).resolve().parents[1]
        runner=repo/'pipeline'/'run_hunyuan_yoyo.py'
        mv_runner=repo/'pipeline'/'run_hunyuan_multiview.py'
        renderer=repo/'pipeline'/'blender_render_job.py'
        refiner=repo/'pipeline'/'blender_auto_refine.py'
        stl=repo/'pipeline'/'blender_export_stl.py'
        caps={
            'hunyuan3d':py.exists() and runner.exists() and (model/'hunyuan3d-dit-v2-1'/'model.fp16.ckpt').exists(),
            'hunyuan3dMultiview':py.exists() and mv_runner.exists() and (mv_model/'hunyuan3d-dit-v2-mv'/'model.fp16.safetensors').exists(),
            'sf3d':False,
            'triposr':False,
            'blender':blender.exists() and renderer.exists(),
            'blenderRefinement':blender.exists() and refiner.exists(),
            'blenderStlExport':blender.exists() and stl.exists(),
        }
    except Exception:
        caps={k:False for k in ('hunyuan3d','hunyuan3dMultiview','sf3d','triposr','blender','blenderRefinement','blenderStlExport')}
    if AGENT_CAPS_OVERRIDE:
        for name in AGENT_CAPS_OVERRIDE.split(','):
            name=name.strip()
            if name:
                caps[name]=True
    return caps


def hello_message()->dict:
    gpu,mem_total,mem_used=_gpu_snapshot()
    caps=_capabilities()
    return {
        'type':'hello',
        'token':WORKER_TOKEN,
        'node':{
            'id':AGENT_ID,'name':AGENT_NAME,
            'caps':caps,
            'gpu':gpu,'memTotal':mem_total,'memUsed':mem_used,
            'diskFree':_disk_free(),
            'maxConcurrentJobs':AGENT_MAX_JOBS,
            'labels':[],
            'os':'linux' if os.name!='nt' else 'windows',
        },
    }


def probe_result(probe_id:str)->dict:
    gpu,mem_total,mem_used=_gpu_snapshot()
    return {'type':'probe_result','probeId':probe_id,
            'caps':_capabilities(),'gpu':gpu,
            'memTotal':mem_total,'memUsed':mem_used,'diskFree':_disk_free()}


def _run_job(job_id:str,config:dict)->dict:
    """在独立线程执行流水线；同机共享 DB 时 worker.run 直接落库。

    v1：与控制面共享 SQLite（同机 / NFS）。跨机 OSS 交换 + 事件回传在 v2。
    """
    from .worker import run
    from .core import db
    try:
        run(job_id)
        with db() as con:
            row=con.execute('SELECT status FROM jobs WHERE id=?',(job_id,)).fetchone()
        status=row['status'] if row else 'unknown'
        return {'ok':status=='completed','result':{'jobId':job_id,'status':status}}
    except Exception as exc:
        return {'ok':False,'error':str(exc)[:500]}


class Agent:
    def __init__(self):
        self.loop:asyncio.AbstractEventLoop|None=None
        self.ws=None

    async def _send(self,msg:dict):
        await self.ws.send(json.dumps(msg,ensure_ascii=False))

    async def _recv_loop(self):
        async for raw in self.ws:
            try:
                msg=json.loads(raw)
            except Exception:
                continue
            mtype=msg.get('type')
            if mtype=='pong':
                continue
            if mtype=='probe':
                await self._send(probe_result(msg.get('probeId','')))
            elif mtype=='run_job':
                job_id=msg.get('jobId','')
                config=msg.get('config') or {}
                print(f'[agent] 收到任务 {job_id}')
                asyncio.create_task(self._execute(job_id,config))
            elif mtype=='hello_ack':
                print(f"[agent] 注册成功，nodeId={msg.get('nodeId')}")
            elif mtype=='error':
                print(f'[agent] 控制面错误：{msg.get("error")}')
            else:
                print(f'[agent] 未知消息：{mtype}')

    async def _execute(self,job_id:str,config:dict):
        result=await asyncio.to_thread(_run_job,job_id,config)
        result['type']='job_result'
        result['jobId']=job_id
        await self._send(result)

    async def _heartbeat_loop(self):
        while True:
            await asyncio.sleep(10)
            await self._send({'type':'ping'})

    async def session(self):
        url=_ws_url()
        print(f'[agent] 连接控制面 {url}（node={AGENT_ID}）')
        async with websockets.connect(url,max_size=10*1024*1024,ping_interval=None) as ws:
            self.ws=ws
            self.loop=asyncio.get_running_loop()
            await self._send(hello_message())
            recv=asyncio.create_task(self._recv_loop())
            hb=asyncio.create_task(self._heartbeat_loop())
            done,_=await asyncio.wait([recv,hb],return_when=asyncio.FIRST_COMPLETED)
            for t in done:
                t.cancel()
            for t in (recv,hb):
                try:await t
                except (asyncio.CancelledError,Exception):pass

    async def run_forever(self):
        backoff=1
        while True:
            try:
                await self.session()
                backoff=1
            except Exception as exc:
                print(f'[agent] 连接中断：{exc}；{backoff}s 后重连')
                await asyncio.sleep(backoff)
                backoff=min(backoff*2,30)


def main():
    if not CONTROL_URL:
        sys.stderr.write('缺少 CONTROL_URL\n')
        sys.exit(2)
    try:
        asyncio.run(Agent().run_forever())
    except KeyboardInterrupt:
        pass


if __name__=='__main__':
    main()
