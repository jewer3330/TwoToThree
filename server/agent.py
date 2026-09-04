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
    # Windows 环境变量极易带尾随空格（cmd `set VAR=value && ...`），必须 strip
    return v.strip() if v not in (None,'') else default


CONTROL_URL=_env('CONTROL_URL').strip().rstrip('/')
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


def _work_root()->Path:
    """节点本地工作根：run_cmd 的默认 cwd 与 selfreg-stage 目录所在。

    优先 AGENT_WORK；其次 STUDIO_EXTERNAL_ROOT/work（与 GPU 节点约定布局
    D:\\print3d\\work 一致）；再退回用户目录/系统盘。目录不存在时创建。
    """
    default=Path.home()/'AIData'/'3d'/'work'
    ext=_env('STUDIO_EXTERNAL_ROOT','')
    if ext:
        default=Path(ext).expanduser()/'work'
    elif os.name=='nt':
        default=Path(os.environ.get('SYSTEMDRIVE','D:'))/'print3d'/'work'
    p=Path(_env('AGENT_WORK',str(default))).expanduser()
    p.mkdir(parents=True,exist_ok=True)
    return p


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
            'hunyuan3d':py.exists() and runner.exists() and (model/'hunyuan3d-dit-v2-1'/'model.fp16.ckpt').exists() and (model/'hunyuan3d-dit-v2-1'/'config.yaml').exists(),
            'hunyuan3dMultiview':py.exists() and mv_runner.exists() and (mv_model/'hunyuan3d-dit-v2-mv'/'model.fp16.safetensors').exists() and (mv_model/'hunyuan3d-dit-v2-mv'/'config.yaml').exists(),
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
    repo_root=str(Path(__file__).resolve().parents[1])
    try:
        from studio_paths import EXTERNAL_ROOT
        ext_root=str(EXTERNAL_ROOT)
    except Exception:
        ext_root=os.environ.get('STUDIO_EXTERNAL_ROOT','')
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
            'workDir':str(_work_root()),
            'repoRoot':repo_root,
            'extRoot':ext_root,
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


# --------------------------------------------------------------------------- #
# v2：命令执行（控制面经 WS 下发 argv，节点本地 subprocess 跑，逐行回传）
# --------------------------------------------------------------------------- #
def _run_command(argv:list[str], cwd:str|None, log_line, timeout:int):
    """同步执行 argv 并逐行 log。返回 (exit_code, error)。

    防孤儿要点：stdout 用独立线程泵读，主线程 proc.wait(timeout) 才能真实
    触发超时——若像旧版那样同步 for 读 stdout，进程持续输出时超时检查永远
    不可达，taskkill 形同虚设，控制面判死后节点进程仍白跑占 GPU。
    """
    import subprocess
    import threading
    proc=subprocess.Popen(argv,cwd=cwd,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,
                          text=True,encoding='utf-8',errors='replace',bufsize=1)
    def pump():
        assert proc.stdout
        for line in proc.stdout:
            line=line.rstrip('\n')
            if line and ('%|' not in line or '100%' in line):
                log_line(line)
    threading.Thread(target=pump,daemon=True).start()
    try:
        proc.wait(timeout=timeout)
        return proc.returncode, None
    except subprocess.TimeoutExpired:
        # 超时必须终止子进程树，避免孤儿进程继续占用 GPU/写产物
        # （控制面已判失败，遗留产物会造成下一次同路径脏数据）。
        try:
            if os.name == 'nt':
                subprocess.run(['taskkill', '/PID', str(proc.pid), '/T', '/F'],
                               capture_output=True, timeout=20)
            else:
                proc.terminate()
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    proc.kill()
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
        return -1, f'命令执行超时（{timeout}s）'


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
            elif mtype=='run_cmd':
                cmd_id=msg.get('cmdId','')
                argv=msg.get('argv') or []
                cwd=msg.get('cwd')
                timeout=int(msg.get('timeout') or 3600)
                print(f'[agent] run_cmd {cmd_id}: {" ".join(str(a) for a in argv)[:300]}')
                asyncio.create_task(self._run_cmd(cmd_id,argv,cwd,timeout))
            elif mtype=='fetch_files':
                fetch_id=msg.get('fetchId','')
                marker=msg.get('marker','')
                files=list(msg.get('files') or [])
                dest_dir=msg.get('destDir') or ''
                print(f'[agent] fetch_files {fetch_id}: {len(files)} 个 -> {dest_dir}')
                asyncio.create_task(self._fetch_files(fetch_id,marker,files,dest_dir))
            elif mtype=='upload_file':
                upload_id=msg.get('uploadId','')
                path=msg.get('path','')
                timeout=int(msg.get('timeout') or 600)
                print(f'[agent] upload_file {upload_id}: {path}')
                asyncio.create_task(self._upload_file(upload_id,path,timeout))
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

    async def _run_cmd(self,cmd_id:str,argv:list[str],cwd:str|None,timeout:int):
        def log_line(line:str):
            # 逐行回传，交给控制面线程的 log 回调
            asyncio.run_coroutine_threadsafe(
                self._send({'type':'cmd_log','cmdId':cmd_id,'line':line}),
                self.loop or asyncio.get_running_loop())
        try:
            exit_code,error=await asyncio.to_thread(_run_command,argv,cwd,log_line,timeout)
            await self._send({'type':'cmd_done','cmdId':cmd_id,'exitCode':exit_code,
                              'error':error})
        except Exception as exc:
            await self._send({'type':'cmd_done','cmdId':cmd_id,'exitCode':-1,
                              'error':str(exc)[:500]})

    async def _upload_file(self,upload_id:str,path:str,timeout:int):
        """把本地文件 POST 回控制面收件端点。"""
        def transfer()->tuple[bool,str|None]:
            try:
                import httpx
            except ImportError:
                return False,'节点缺少 httpx 依赖，无法回传产物'
            try:
                url=f'{CONTROL_URL}/api/gpu/selfreg/upload/{upload_id}'
                headers={'X-Worker-Token':WORKER_TOKEN} if WORKER_TOKEN else {}
                with open(path,'rb') as fh:
                    name=os.path.basename(path)
                    r=httpx.post(url,files={'file':(name,fh)},headers=headers,timeout=timeout)
                return r.status_code<300,None if r.status_code<300 else f'HTTP {r.status_code}'
            except Exception as exc:
                return False,str(exc)[:500]
        # httpx 的同步上传可能持续数分钟；必须放在线程里，否则会堵住 WS
        # 事件循环和 10 秒心跳，控制面会在 45 秒后把仍在传输的节点误判离线。
        ok,error=await asyncio.to_thread(transfer)
        if error:print(f'[agent] upload error: {error}')
        await self._send({'type':'upload_done','uploadId':upload_id,'ok':ok,'error':error})

    async def _fetch_files(self,fetch_id:str,marker:str,files:list[str],dest_dir:str):
        """从控制面 pullbox 拉取输入文件到节点本地 dest_dir。"""
        def transfer()->tuple[bool,str|None]:
            try:
                import httpx
            except ImportError:
                return False,'节点缺少 httpx 依赖，无法拉取输入'
            try:
                os.makedirs(dest_dir, exist_ok=True)
                headers={'X-Worker-Token':WORKER_TOKEN} if WORKER_TOKEN else {}
                for name in files:
                    url=f'{CONTROL_URL}/api/gpu/selfreg/pullbox/{marker}/{name}'
                    target=os.path.join(dest_dir,name)
                    partial=f'{target}.part-{fetch_id}'
                    size=0
                    try:
                        # 流式落盘，避免大 GLB 整体驻留内存；先写临时文件，成功后
                        # 原子替换，网络中断也不会留下被后续命令误用的半文件。
                        with httpx.stream('GET',url,headers=headers,timeout=300) as resp:
                            resp.raise_for_status()
                            with open(partial,'wb') as fh:
                                for chunk in resp.iter_bytes(1024*1024):
                                    fh.write(chunk)
                                    size+=len(chunk)
                        os.replace(partial,target)
                    finally:
                        if os.path.exists(partial):
                            os.unlink(partial)
                    print(f'[agent] fetch {name} ({size} bytes) -> {target}')
                return True,None
            except Exception as exc:
                return False,str(exc)[:500]
        # 下载同样不能占住 asyncio 事件循环；大 GLB 跨公网下载超过心跳窗口很常见。
        ok,error=await asyncio.to_thread(transfer)
        if error:print(f'[agent] fetch error: {error}')
        await self._send({'type':'fetch_done','fetchId':fetch_id,'ok':ok,'error':error})

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
