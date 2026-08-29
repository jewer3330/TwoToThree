from __future__ import annotations
import base64, json, os, shutil, subprocess, threading, time, uuid
from pathlib import Path
from typing import Callable
from .core import ROOT
from studio_paths import LOCAL_ROOT

HUNYUAN_PY=LOCAL_ROOT/'hunyuan-bootstrap/Scripts/python.exe'
HUNYUAN_MODEL=LOCAL_ROOT/'Hunyuan3D-2.1-model'
HUNYUAN_RUNNER=ROOT/'pipeline/run_hunyuan_yoyo.py'
HUNYUAN_MV_MODEL=LOCAL_ROOT/'Hunyuan3D-2mv-model-v2'
HUNYUAN_MV_RUNNER=ROOT/'pipeline/run_hunyuan_multiview.py'
HUNYUAN_MV_WEIGHTS=HUNYUAN_MV_MODEL/'hunyuan3d-dit-v2-mv/model.fp16.safetensors'
HUNYUAN_MV_EXPECTED_BYTES=4_928_151_562
SF3D_PY=LOCAL_ROOT/'stable-fast-3d/.venv-runtime/Scripts/python.exe'
SF3D_REPO=LOCAL_ROOT/'stable-fast-3d'
TRIPOSR_PY=LOCAL_ROOT/'TripoSR/.venv-runtime/Scripts/python.exe'
TRIPOSR_REPO=LOCAL_ROOT/'TripoSR'
BLENDER=LOCAL_ROOT/'Blender52/blender.exe'
BLENDER_RENDERER=ROOT/'pipeline/blender_render_job.py'
BLENDER_REFINER=ROOT/'pipeline/blender_auto_refine.py'
BLENDER_STL_EXPORTER=ROOT/'pipeline/blender_export_stl.py'

# --- 远程执行配置（PRINT3D_MODE=remote 时生效） ---
MODE=os.environ.get('PRINT3D_MODE','local')
REMOTE_HOST=os.environ.get('PRINT3D_REMOTE_HOST','')
REMOTE_USER=os.environ.get('PRINT3D_REMOTE_USER','d0993')
REMOTE_KEY=os.environ.get('PRINT3D_REMOTE_KEY',str(Path.home()/'.ssh'/'id_ed25519_ai_video'))
REMOTE_ROOT=os.environ.get('PRINT3D_REMOTE_ROOT',r'D:\print3d\TwoToThree')
REMOTE_EXT=os.environ.get('PRINT3D_REMOTE_EXT',r'D:\print3d')
REMOTE_WORK=os.environ.get('PRINT3D_REMOTE_WORK',r'D:\print3d\work')

class BackendError(RuntimeError):pass
class CancelledError(RuntimeError):pass

def remote():
    """当前线程绑定的主机 Remote；否则退回 env 单机配置。"""
    bound=getattr(_local,'remote',None)
    if bound is not None:return bound
    if MODE=='remote' and REMOTE_HOST:
        return Remote(REMOTE_HOST,REMOTE_USER,Path(REMOTE_KEY),REMOTE_ROOT,REMOTE_EXT,REMOTE_WORK)
    return None

_local=threading.local()
def bind_host(cfg:dict|None):
    """绑定当前线程执行主机（worker 领取任务时调用）。cfg=None 解除绑定。"""
    if cfg is None:
        _local.remote=None;return
    _local.remote=Remote(cfg['host'],cfg['user'],Path(cfg['key']),cfg['root'],cfg['ext'],cfg['work'])

def remote_from_cfg(cfg:dict)->Remote|None:
    if not cfg or not cfg.get('host'):return None
    return Remote(cfg['host'],cfg['user'] or 'd0993',Path(cfg['key']),cfg['root'] or '',cfg['ext'] or '',cfg['work'] or '')

class Remote:
    def __init__(self,host,user,key,root,ext,work):
        self.host=host;self.user=user;self.key=key;self.root=root;self.ext=ext;self.work=work
        self.base=['ssh','-i',str(key),'-o','BatchMode=yes','-o','ConnectTimeout=15','-o','StrictHostKeyChecking=accept-new',f'{user}@{host}']
        # CDN 候选（GPU 节点从主控 CDN 下载，绕开 tailscale relay 慢路径）：局域网→tailscale→公网
        self.cdn_urls=[u for u in os.environ.get('PRINT3D_CDN_URLS','http://192.168.31.210:12080,https://cdn.lovesun.top').split(',') if u]
    def _q(self,arg):
        if '"' in arg:arg=arg.replace('"','\\"')
        return f'"{arg}"'
    def run(self,command,log:Callable[[str],None],cancelled:Callable[[],bool],timeout:int=3600,cwd_remote:str|None=None,marker:str=''):
        remote_cmd=' '.join(self._q(a) for a in command)
        remote_cmd=f'set STUDIO_EXTERNAL_ROOT={self.ext} && '+remote_cmd
        if cwd_remote:remote_cmd=f'cd /d {self._q(cwd_remote)} && {remote_cmd}'
        full=self.base+[remote_cmd]
        creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0)
        process=subprocess.Popen(full,cwd=str(ROOT),stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,encoding='utf-8',errors='replace',bufsize=1,creationflags=creationflags)
        deadline=time.monotonic()+timeout
        def pump():
            assert process.stdout
            for line in process.stdout:
                line=line.strip()
                if line and ('%|' not in line or '100%' in line):log(line[-1000:])
        reader=threading.Thread(target=pump,daemon=True);reader.start()
        while process.poll() is None:
            if cancelled():
                process.terminate()
                try:process.wait(10)
                except subprocess.TimeoutExpired:process.kill()
                self.kill_remote(marker);raise CancelledError('任务已取消，远程子进程已终止')
            if time.monotonic()>deadline:
                process.kill();self.kill_remote(marker);raise BackendError(f'命令超过 {timeout} 秒超时')
            time.sleep(.25)
        reader.join(timeout=2)
        if process.returncode:raise BackendError(f'远程命令退出码 {process.returncode}')
    def kill_remote(self,marker:str):
        if not marker:return
        try:
            clause=marker.replace("'","''")
            script=f"Get-CimInstance Win32_Process | Where-Object {{ $_.CommandLine -like '*{clause}*' }} | ForEach-Object {{ Stop-Process -Id $_.ProcessId -Force }}"
            subprocess.run(self.base+self._ps(script),timeout=25,capture_output=True)
        except Exception:pass
    def _ps(self,script:str):
        encoded=base64.b64encode(script.encode('utf-16-le')).decode('ascii')
        return ['powershell','-NoProfile','-EncodedCommand',encoded]
    def stage(self,marker:str):return f'{self.work}\\{marker}'
    def prepare(self,marker:str,locals_:list[Path]):
        stag=self.stage(marker)
        # 确保远端 staging 目录存在（重试，网络抖动时 EncodedCommand 可能失败）
        for _ in range(3):
            try:
                out=self.cmd(['powershell','-NoProfile','-Command',f'New-Item -ItemType Directory -Force -Path {stag} | Out-Null'])
                if out.returncode==0:break
            except Exception:pass
            time.sleep(3)
        for p in locals_:
            if p.exists():
                target=f'{stag}\\{p.name}'
                for attempt in range(3):
                    try:
                        self.upload(p,target);break
                    except Exception:
                        if attempt==2:raise
                        self.cmd(['powershell','-NoProfile','-Command',f'New-Item -ItemType Directory -Force -Path {stag} | Out-Null'])
                        time.sleep(4)
    def cmd(self,command,timeout:int=25):
        args=' '.join("'"+a.replace("'","''")+"'" for a in command)
        script=f'[Console]::OutputEncoding=[System.Text.Encoding]::UTF8; & {args}'
        return subprocess.run(self.base+self._ps(script),capture_output=True,text=True,errors='replace',timeout=timeout)
    def upload(self,local:Path,remote_abs:str):
        """优先走 CDN：文件在 DATA 下 → 远端 curl 从 CDN 拉（局域网/公网候选，快）。
        否则 scp 兜底。"""
        from .core import DATA
        try:
            rel=local.resolve().relative_to(DATA.resolve()).as_posix()
            if self.cdn_urls and rel:
                target=remote_abs.replace('/','\\')
                cmd='; '.join(f"curl.exe -fL --connect-timeout 5 -sS -o '{target}' '{u}/print3d/{rel}'" for u in self.cdn_urls)
                try:
                    out=self.cmd(['powershell','-NoProfile','-Command',f"{cmd}; if(Test-Path '{target}'){{$true}}else{{exit 1}}"],timeout=90)
                    if out.returncode==0 and self._remote_exists(target):
                        return
                except Exception:pass
        except Exception:pass
        self._retry(lambda:subprocess.run(self._scp_cmd()+[str(local),f'{self.user}@{self.host}:{remote_abs.replace(chr(92),"/")}'],check=True,timeout=300))
    def _remote_exists(self,path:str)->bool:
        try:
            out=self.cmd(['powershell','-NoProfile','-Command',f"Test-Path '{path.replace(chr(92),'/')}'"],timeout=25)
            return out.returncode==0 and out.stdout.strip().lower()=='true'
        except Exception:
            return True  # 无法确认时不阻断
    def download_dir(self,remote_dir:str,local_dir:Path):
        import tarfile
        remote_dir=remote_dir.replace('/','\\')
        parent=remote_dir.rsplit('\\',1)[0];name=remote_dir.rsplit('\\',1)[1]
        local_dir.mkdir(parents=True,exist_ok=True)
        tmp=local_dir/f'{name}.tgz'
        try:
            self.cmd(['powershell','-NoProfile','-Command',f"tar -czf '{remote_dir}.tgz' -C '{parent}' '{name}'"])
            self._retry(lambda:subprocess.run(self._scp_cmd()+[f'{self.user}@{self.host}:{remote_dir.replace(chr(92),"/")}.tgz',str(tmp)],check=True,timeout=600))
            with tarfile.open(tmp,'r:gz') as t:t.extractall(str(local_dir))
            # tar 解出的目录名可能与期望不同（如 renders -> local/renders），展平一层
            child=local_dir/name
            if child.is_dir() and child!=local_dir:
                for item in list(child.iterdir()):shutil.move(str(item),str(local_dir))
                shutil.rmtree(child,ignore_errors=True)
        finally:
            tmp.unlink(missing_ok=True)
    def download_file(self,remote_file:str,local_file:Path):
        local_file.parent.mkdir(parents=True,exist_ok=True)
        self._retry(lambda:subprocess.run(self._scp_cmd()+[f'{self.user}@{self.host}:{remote_file.replace(chr(92),"/")}',str(local_file)],check=True,timeout=300))
    def download_compressed(self,remote_file:str,local_file:Path):
        """远端 tar.gz 压缩后回传，本地解压（tailscale relay 带宽低，GLB 压缩率 ~65%）。"""
        import tarfile
        remote_file=remote_file.replace('/','\\')
        remote_dir=remote_file.rsplit('\\',1)[0];remote_name=remote_file.rsplit('\\',1)[1]
        tmp=local_file.with_suffix(local_file.suffix+'.tgz')
        try:
            self.cmd(['powershell','-NoProfile','-Command',f"tar -czf '{remote_file}.tgz' -C '{remote_dir}' '{remote_name}'"])
            self._retry(lambda:subprocess.run(self._scp_cmd()+[f'{self.user}@{self.host}:{remote_file.replace(chr(92),"/")}.tgz',str(tmp)],check=True,timeout=600))
            with tarfile.open(tmp,'r:gz') as t:t.extract(local_file.name,str(local_file.parent))
            if not local_file.exists():raise BackendError('压缩包解压未生成目标文件')
        finally:
            tmp.unlink(missing_ok=True)
    def _scp_cmd(self,extra:list[str]|None=None)->list[str]:
        return ['scp','-q',*(extra or []),'-i',str(self.key),'-o','BatchMode=yes','-o','StrictHostKeyChecking=accept-new','-o','ServerAliveInterval=15','-o','ServerAliveCountMax=4']
    def _retry(self,fn,attempts=5):
        last=None
        for i in range(attempts):
            try:return fn()
            except subprocess.CalledProcessError as exc:
                last=exc;time.sleep(5*(i+1))
        raise last
    def cleanup(self,marker:str):
        try:self.cmd(['powershell','-NoProfile','-Command',f'Remove-Item -Recurse -Force {self.stage(marker)} -ErrorAction SilentlyContinue'])
        except Exception:pass

def _flatten(dir_:Path):
    """scp -r 会把远端目录原样放进目标目录（多一层嵌套），这里把子目录内容上提。"""
    if not dir_.is_dir():return
    for child in list(dir_.iterdir()):
        target=dir_.parent/child.name
        if target.exists():
            if target.is_dir():shutil.rmtree(target,ignore_errors=True)
            else:target.unlink()
        shutil.move(str(child),str(target))

def _rc():
    ext=REMOTE_EXT.replace('/','\\')
    root=REMOTE_ROOT.replace('/','\\')
    return {
        'python':ext+r'\local\hunyuan-bootstrap\Scripts\python.exe',
        'model':ext+r'\local\Hunyuan3D-2.1-model',
        'runner':root+r'\pipeline\run_hunyuan_yoyo.py',
        'mv_model':ext+r'\local\Hunyuan3D-2mv-model-v2',
        'mv_runner':root+r'\pipeline\run_hunyuan_multiview.py',
        'sf3d_py':ext+r'\local\stable-fast-3d\.venv-runtime\Scripts\python.exe',
        'sf3d_repo':ext+r'\local\stable-fast-3d',
        'triposr_py':ext+r'\local\TripoSR\.venv-runtime\Scripts\python.exe',
        'triposr_repo':ext+r'\local\TripoSR',
        'blender':ext+r'\local\Blender52\blender.exe',
        'renderer':root+r'\pipeline\blender_render_job.py',
        'refiner':root+r'\pipeline\blender_auto_refine.py',
        'stl_exporter':root+r'\pipeline\blender_export_stl.py',
    }

def capabilities():
    if MODE=='remote' and REMOTE_HOST:
        return _remote_capabilities(remote())
    return {
        'hunyuan3d':HUNYUAN_PY.exists() and HUNYUAN_RUNNER.exists() and HUNYUAN_MODEL.exists(),
        'hunyuan3dMultiview':HUNYUAN_PY.exists() and HUNYUAN_MV_RUNNER.exists() and HUNYUAN_MV_WEIGHTS.exists() and HUNYUAN_MV_WEIGHTS.stat().st_size==HUNYUAN_MV_EXPECTED_BYTES,
        'sf3d':SF3D_PY.exists() and (SF3D_REPO/'run.py').exists(),
        'triposr':TRIPOSR_PY.exists() and (TRIPOSR_REPO/'run.py').exists(),
        'blender':BLENDER.exists() and BLENDER_RENDERER.exists(),
        'blenderRefinement':BLENDER.exists() and BLENDER_REFINER.exists(),
        'blenderStlExport':BLENDER.exists() and BLENDER_STL_EXPORTER.exists(),
    }

_caps_cache:dict|None=None
_caps_at=0.0
def _remote_capabilities(r:Remote|None=None)->dict:
    global _caps_cache,_caps_at
    r=r or remote()
    if not r:return {k:False for k in ('hunyuan3d','hunyuan3dMultiview','sf3d','triposr','blender','blenderRefinement','blenderStlExport')}
    if _caps_cache and time.monotonic()-_caps_at<10:return _caps_cache
    rc=_rc()
    checks=[('hunyuan3d',rc['python']),('hunyuan3d',rc['model']),('hunyuan3d',rc['runner']),
            ('hunyuan3dMultiview',rc['python']),('hunyuan3dMultiview',rc['mv_runner']),('hunyuan3dMultiview',rc['mv_model']),
            ('sf3d',rc['sf3d_py']),('sf3d',rc['sf3d_repo']),
            ('triposr',rc['triposr_py']),('triposr',rc['triposr_repo']),
            ('blender',rc['blender']),('blender',rc['renderer']),
            ('blenderRefinement',rc['blender']),('blenderRefinement',rc['refiner']),
            ('blenderStlExport',rc['blender']),('blenderStlExport',rc['stl_exporter'])]
    wanted={c for c,_ in checks};got=set()
    try:
        probe=';'.join(f"Write-Output (Test-Path '{p}')" for _,p in checks)
        out=r.cmd(['powershell','-NoProfile','-Command',probe])
        flags=[l.strip().lower()=='true' for l in out.stdout.splitlines() if l.strip()]
        for (cap,_),ok in zip(checks,flags):
            if ok:got.add(cap)
    except Exception:pass
    caps={c:(c in got) for c in wanted}
    if caps.get('hunyuan3dMultiview'):
        try:
            o=r.cmd(['powershell','-NoProfile','-Command',f"if(Test-Path '{rc['mv_model']}'\\hunyuan3d-dit-v2-mv\\model.fp16.safetensors){{(Get-Item '{rc['mv_model']}'\\hunyuan3d-dit-v2-mv\\model.fp16.safetensors).Length}}else{{0}}"])
            caps['hunyuan3dMultiview']=caps['hunyuan3dMultiview'] and o.stdout.strip()==str(HUNYUAN_MV_EXPECTED_BYTES)
        except Exception:pass
    _caps_cache=caps;_caps_at=time.monotonic();return caps

def probe_host(cfg:dict)->dict:
    """探测一台主机的完整健康状态（GPU/显存/磁盘/能力）。供 GPU 控制面板轮询。"""
    r=remote_from_cfg(cfg)
    if not r:return {'online':False,'gpu':None,'memTotal':None,'memUsed':None,'diskFree':None,'latencyMs':None,'route':None,'caps':{},'lastError':'no remote'}
    result={'online':False,'gpu':None,'memTotal':None,'memUsed':None,'diskFree':None,'latencyMs':None,'route':None,'caps':{},'lastError':None}
    try:
        t0=time.monotonic()
        out=r.cmd(['nvidia-smi','--query-gpu=name,memory.total,memory.used','--format=csv,noheader,nounits'])
        result['latencyMs']=round((time.monotonic()-t0)*1000)
        line=out.stdout.strip().splitlines()[0] if out.stdout.strip() else ''
        if line:
            parts=[p.strip() for p in line.split(',')]
            if len(parts)>=3:
                result['gpu']=parts[0];result['memTotal']=int(parts[1]);result['memUsed']=int(parts[2])
        result['online']=bool(result['gpu'])
        disk=r.cmd(['powershell','-NoProfile','-Command',f"Get-PSDrive -Name {cfg.get('work','D:')[0]} | Select-Object -ExpandProperty Free"])
        free=disk.stdout.strip()
        if free:result['diskFree']=round(float(free)/1073741824,1)
        result['caps']=_remote_capabilities(r)
    except Exception as exc:
        result['lastError']=str(exc)[:200]
    return result

def remote_gpu()->dict|None:
    if MODE!='remote' or not REMOTE_HOST:return None
    r=remote()
    try:
        out=r.cmd(['nvidia-smi','--query-gpu=name','--format=csv,noheader'])
        name=out.stdout.strip().splitlines()[0] if out.stdout.strip() else ''
        return {'status':'ready' if name else 'unavailable','name':name}
    except Exception:
        return {'status':'unavailable','name':None}

def run_process(command:list[str],cwd:Path,log:Callable[[str],None],cancelled:Callable[[],bool],env:dict|None=None,timeout:int=3600):
    creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0)
    process=subprocess.Popen(command,cwd=cwd,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,encoding='utf-8',errors='replace',bufsize=1,env=env or os.environ.copy(),creationflags=creationflags)
    deadline=time.monotonic()+timeout
    def pump():
        assert process.stdout
        for line in process.stdout:
            line=line.strip()
            if line and ('%|' not in line or '100%' in line):log(line[-1000:])
    reader=threading.Thread(target=pump,daemon=True);reader.start()
    while process.poll() is None:
        if cancelled():
            process.terminate()
            try:process.wait(10)
            except subprocess.TimeoutExpired:process.kill()
            raise CancelledError('任务已取消，推理子进程已终止')
        if time.monotonic()>deadline:
            process.kill();raise BackendError(f'命令超过 {timeout} 秒超时')
        time.sleep(.25)
    reader.join(timeout=2)
    if process.returncode:raise BackendError(f'命令退出码 {process.returncode}')

def _marker():return f'p3d-{uuid.uuid4().hex[:8]}'

def generate_hunyuan(image:Path,output:Path,seed:int,quality:str,log,cancelled):
    steps={'standard':20,'high':30,'ultra':40}.get(quality,20)
    resolution={'standard':256,'high':384,'ultra':512}.get(quality,256)
    processed=output.parent/'condition-front.png'
    if MODE!='remote' or not REMOTE_HOST:
        command=[str(HUNYUAN_PY),str(HUNYUAN_RUNNER),'--image',str(image),'--model',str(HUNYUAN_MODEL),'--output',str(output),'--processed-image-output',str(processed),'--steps',str(steps),'--resolution',str(resolution),'--seed',str(seed)]
        log(f'Hunyuan3D 2.1 启动：steps={steps}, octree={resolution}, seed={seed}')
        run_process(command,ROOT,log,cancelled,timeout=2400)
        if not output.exists():raise BackendError('Hunyuan3D 未生成 GLB')
        return {'backend':'hunyuan3d','modelVersion':'tencent/Hunyuan3D-2.1','steps':steps,'resolution':resolution,'seed':seed,'processedImage':str(processed),'command':[Path(x).name if i<2 else x for i,x in enumerate(command)]}
    rc=_rc();r=remote();marker=_marker();stag=r.stage(marker);r.prepare(marker,[image])
    rimg=f'{stag}\\{image.name}';rout=f'{stag}\\{output.name}';rproc=f'{stag}\\condition-front.png'
    command=[rc['python'],rc['runner'],'--image',rimg,'--model',rc['model'],'--output',rout,'--processed-image-output',rproc,'--steps',str(steps),'--resolution',str(resolution),'--seed',str(seed)]
    log(f'Hunyuan3D 2.1 远程启动（{r.host}）：steps={steps}, octree={resolution}, seed={seed}')
    r.run(command,log,cancelled,timeout=3000,marker=stag)
    r.download_compressed(rout,output)
    try:r.download_file(rproc,processed)
    except Exception:pass
    r.cleanup(marker)
    if not output.exists():raise BackendError('Hunyuan3D 未生成 GLB')
    return {'backend':'hunyuan3d','modelVersion':'tencent/Hunyuan3D-2.1','steps':steps,'resolution':resolution,'seed':seed,'processedImage':str(processed),'command':[Path(x).name if i<2 else x for i,x in enumerate(command)]}

def generate_hunyuan_multiview(images:dict[str,Path],output:Path,seed:int,quality:str,view_weights:dict[str,float],log,cancelled,visual_conditioning:dict|None=None,style:str='realistic'):
    """Run a real multi-view backend; never concatenate views or silently use front only."""
    if not capabilities().get('hunyuan3dMultiview'):
        raise BackendError('检测到多视图素材，但本机未配置 Hunyuan3D-2mv。请安装多视图权重和推理脚本；系统不会静默退回单图生成。')
    required={'front','side','back'};missing=sorted(required-images.keys())
    if missing:raise BackendError(f'多视图生成缺少视角：{missing}')
    steps={'standard':20,'high':30,'ultra':40}.get(quality,20);resolution={'standard':256,'high':384,'ultra':512}.get(quality,256)
    processed=output.parent/'multiview-conditions'
    if MODE!='remote' or not REMOTE_HOST:
        command=[str(HUNYUAN_PY),str(HUNYUAN_MV_RUNNER),'--model',str(HUNYUAN_MV_MODEL),'--output',str(output),'--processed-dir',str(processed),'--steps',str(steps),'--resolution',str(resolution),'--seed',str(seed)]
        for role in ('front','side','back'):command.extend([f'--{role}',str(images[role])])
        weights={role:max(0.1,min(3.0,float(view_weights.get(role,1.0)))) for role in ('front','side','back')}
        for role in ('front','side','back'):command.extend([f'--{role}-weight',str(weights[role])])
        visual=visual_conditioning or {};mode=str(visual.get('mode','auto')) if visual.get('enabled',True) else 'original';depth_blend=max(0,min(.25,float(visual.get('depthBlend',.15))));command.extend(['--visual-conditioning',mode,'--style',style,'--depth-blend',str(depth_blend)])
        log(f'Hunyuan3D-2mv 启动：views=front,side,back, weights={weights}, steps={steps}, octree={resolution}, seed={seed}, memory=cpu-load/offload')
        run_process(command,ROOT,log,cancelled,timeout=2400)
        if not output.exists():raise BackendError('Hunyuan3D-2mv 未生成 GLB')
    else:
        rc=_rc();r=remote();marker=_marker();stag=r.stage(marker)
        r.prepare(marker,[images[role] for role in ('front','side','back')])
        rout=f'{stag}\\{output.name}';rproc=f'{stag}\\multiview-conditions'
        command=[rc['python'],rc['mv_runner'],'--model',rc['mv_model'],'--output',rout,'--processed-dir',rproc,'--steps',str(steps),'--resolution',str(resolution),'--seed',str(seed)]
        for role in ('front','side','back'):command.extend([f'--{role}',f'{stag}\\{images[role].name}'])
        weights={role:max(0.1,min(3.0,float(view_weights.get(role,1.0)))) for role in ('front','side','back')}
        for role in ('front','side','back'):command.extend([f'--{role}-weight',str(weights[role])])
        visual=visual_conditioning or {};mode=str(visual.get('mode','auto')) if visual.get('enabled',True) else 'original';depth_blend=max(0,min(.25,float(visual.get('depthBlend',.15))));command.extend(['--visual-conditioning',mode,'--style',style,'--depth-blend',str(depth_blend)])
        log(f'Hunyuan3D-2mv 远程启动（{r.host}）：views=front,side,back, weights={weights}, steps={steps}, octree={resolution}, seed={seed}')
        r.run(command,log,cancelled,timeout=3000,marker=stag)
        r.download_file(rout,output)
        try:r.download_dir(rproc,processed)
        except Exception:pass
        r.cleanup(marker)
        if not output.exists():raise BackendError('Hunyuan3D-2mv 未生成 GLB')
    visual_root=processed/'visual-candidates';report_path=visual_root/'visual-conditioning-report.json';report=json.loads(report_path.read_text(encoding='utf-8')) if report_path.exists() else {};candidates={role:{name:str(visual_root/role/f'{name}.png') for name in ('original','contour','rgb_depth','depth-cue-experimental')} for role in ('front','side','back')}
    selected_images={role:report.get('views',{}).get(role,{}).get('selected',str(processed/f'condition-{"left" if role=="side" else role}.png')) for role in ('front','side','back')}
    return {'backend':'hunyuan3d-2mv','modelVersion':'tencent/Hunyuan3D-2mv','steps':steps,'resolution':resolution,'seed':seed,'views':['front','side','back'],'viewWeights':weights,'processedImages':selected_images,'visualConditioning':report,'visualConditioningReport':str(report_path),'visualCandidates':candidates}

def generate_sf3d(image:Path,output:Path,texture_resolution:int,log,cancelled):
    staging=output.parent/'sf3d-output';staging.mkdir(parents=True,exist_ok=True)
    if MODE!='remote' or not REMOTE_HOST:
        command=[str(SF3D_PY),'run.py',str(image),'--output-dir',str(staging),'--texture-resolution',str(texture_resolution),'--remesh_option','none','--target_vertex_count','-1']
        log(f'Stable Fast 3D 启动：texture={texture_resolution}')
        run_process(command,SF3D_REPO,log,cancelled,timeout=1200)
    else:
        rc=_rc();r=remote();marker=_marker();stag=r.stage(marker);r.prepare(marker,[image])
        rimg=f'{stag}\\{image.name}';rout_dir=f'{stag}\\sf3d-output'
        command=[rc['sf3d_py'],'run.py',rimg,'--output-dir',rout_dir,'--texture-resolution',str(texture_resolution),'--remesh_option','none','--target_vertex_count','-1']
        log(f'Stable Fast 3D 远程启动（{r.host}）：texture={texture_resolution}')
        r.run(command,log,cancelled,timeout=1500,cwd_remote=rc['sf3d_repo'],marker=stag)
        r.download_dir(stag,staging);r.cleanup(marker)
    candidates=sorted(staging.rglob('mesh.glb'),key=lambda p:p.stat().st_mtime,reverse=True)
    if not candidates:raise BackendError('SF3D 未生成 mesh.glb')
    output.write_bytes(candidates[0].read_bytes())
    return {'backend':'sf3d','modelVersion':'stabilityai/stable-fast-3d','textureResolution':texture_resolution}

def generate_triposr(image:Path,output:Path,log,cancelled):
    staging=output.parent/'triposr-output';staging.mkdir(parents=True,exist_ok=True)
    if MODE!='remote' or not REMOTE_HOST:
        command=[str(TRIPOSR_PY),'run.py',str(image),'--output-dir',str(staging),'--model-save-format','glb']
        log('TripoSR 启动')
        run_process(command,TRIPOSR_REPO,log,cancelled,timeout=1200)
    else:
        rc=_rc();r=remote();marker=_marker();stag=r.stage(marker);r.prepare(marker,[image])
        rimg=f'{stag}\\{image.name}';rout_dir=f'{stag}\\triposr-output'
        command=[rc['triposr_py'],'run.py',rimg,'--output-dir',rout_dir,'--model-save-format','glb']
        log(f'TripoSR 远程启动（{r.host}）')
        r.run(command,log,cancelled,timeout=1500,cwd_remote=rc['triposr_repo'],marker=stag)
        r.download_dir(stag,staging);r.cleanup(marker)
    candidates=sorted(staging.rglob('*.glb'),key=lambda p:p.stat().st_mtime,reverse=True)
    if not candidates:raise BackendError('TripoSR 未生成 GLB')
    output.write_bytes(candidates[0].read_bytes())
    return {'backend':'triposr','modelVersion':'stabilityai/TripoSR'}

def render_blender(source:Path,output_dir:Path,web_glb:Path,log,cancelled,quality:str='standard',texture_resolution:int=0,references:dict[str,Path]|None=None,style_preset:dict|None=None):
    preset=style_preset or {};style_id=str(preset.get('id','realistic'));depth_scale=max(.35,min(1.0,float(preset.get('depthScale',1.0))))
    if MODE!='remote' or not REMOTE_HOST:
        command=[str(BLENDER),'--background','--factory-startup','--python',str(BLENDER_RENDERER),'--','--input',str(source),'--output-dir',str(output_dir),'--web-glb',str(web_glb),'--quality',quality,'--texture-resolution',str(texture_resolution),'--style',style_id,'--depth-scale',str(depth_scale)]
        for role,path in (references or {}).items():
            if role in ('front','side','back') and path.exists():command.extend([f'--{role}',str(path)])
        log(f'Blender 5.2 后台四视图渲染启动：style={style_id}, depthScale={depth_scale:.2f}')
        run_process(command,ROOT,log,cancelled,timeout=900)
    else:
        rc=_rc();r=remote();marker=_marker();stag=r.stage(marker)
        uploads=[source]+[p for role,p in (references or {}).items() if role in ('front','side','back') and p.exists()]
        r.prepare(marker,uploads)
        rsrc=f'{stag}\\{source.name}';renders=f'{stag}\\renders';web_remote=f'{stag}\\web.glb'
        command=[rc['blender'],'--background','--factory-startup','--python',rc['renderer'],'--','--input',rsrc,'--output-dir',renders,'--web-glb',web_remote,'--quality',quality,'--texture-resolution',str(texture_resolution),'--style',style_id,'--depth-scale',str(depth_scale)]
        for role,path in (references or {}).items():
            if role in ('front','side','back') and path.exists():command.extend([f'--{role}',f'{stag}\\{path.name}'])
        log(f'Blender 5.2 远程四视图渲染启动（{r.host}）：style={style_id}, depthScale={depth_scale:.2f}')
        r.run(command,log,cancelled,timeout=1200,marker=stag)
        r.download_dir(renders,output_dir)
        r.download_compressed(web_remote,web_glb)
        r.cleanup(marker)
        _flatten(output_dir/'renders')
    expected={v:output_dir/f'{v}.png' for v in ('front','left-three-quarter','side','back')}
    missing=[v for v,p in expected.items() if not p.exists()]
    if missing or not web_glb.exists():raise BackendError(f'Blender 产物不完整：{missing}')
    return expected

def refine_blender(source:Path,output_dir:Path,config_path:Path,log,cancelled,reference_image:Path|None=None):
    if MODE!='remote' or not REMOTE_HOST:
        command=[str(BLENDER),'--background','--factory-startup','--python',str(BLENDER_REFINER),'--','--input',str(source),'--output-dir',str(output_dir),'--config',str(config_path)]
        if reference_image:command.extend(['--reference-image',str(reference_image)])
        log('启动真实 Blender 后台自动精修')
        run_process(command,ROOT,log,cancelled,timeout=1800)
    else:
        rc=_rc();r=remote();marker=_marker();stag=r.stage(marker)
        inputs=[source,config_path]+([reference_image] if reference_image else [])
        r.prepare(marker,inputs)
        rsrc=f'{stag}\\{source.name}';rcfg=f'{stag}\\{config_path.name}';rout_dir=f'{stag}\\out'
        command=[rc['blender'],'--background','--factory-startup','--python',rc['refiner'],'--','--input',rsrc,'--output-dir',rout_dir,'--config',rcfg]
        if reference_image:command.extend(['--reference-image',f'{stag}\\{reference_image.name}'])
        log(f'启动远程 Blender 后台自动精修（{r.host}）')
        r.run(command,log,cancelled,timeout=2100,marker=stag)
        r.download_dir(rout_dir,output_dir)
        r.cleanup(marker)
        _flatten(output_dir/'out')
    report=output_dir/'quality-report.json'
    if not report.exists():raise BackendError('Blender 未生成质量报告')
    result=json.loads(report.read_text(encoding='utf-8'))
    if not (output_dir/'refined.glb').exists():raise BackendError('Blender 未生成 refined.glb')
    return result

def export_stl_blender(source:Path,output:Path,scope:str,unit:str,apply_modifiers:bool,log,target_height_mm:float|None=None):
    if MODE!='remote' or not REMOTE_HOST:
        command=[str(BLENDER),'--background','--factory-startup','--python',str(BLENDER_STL_EXPORTER),'--','--input',str(source),'--output',str(output),'--scope',scope,'--unit',unit]
        if apply_modifiers:command.append('--apply-modifiers')
        if target_height_mm is not None:command.extend(['--target-height-mm',str(target_height_mm)])
        log(f'Blender STL 导出启动：scope={scope}, unit={unit}, applyModifiers={apply_modifiers}, targetHeightMm={target_height_mm}')
        run_process(command,ROOT,log,lambda:False,timeout=900)
    else:
        rc=_rc();r=remote();marker=_marker();stag=r.stage(marker);r.prepare(marker,[source])
        rsrc=f'{stag}\\{source.name}';rout=f'{stag}\\{output.name}'
        command=[rc['blender'],'--background','--factory-startup','--python',rc['stl_exporter'],'--','--input',rsrc,'--output',rout,'--scope',scope,'--unit',unit]
        if apply_modifiers:command.append('--apply-modifiers')
        if target_height_mm is not None:command.extend(['--target-height-mm',str(target_height_mm)])
        log(f'Blender STL 远程导出启动（{r.host}）：scope={scope}, unit={unit}')
        r.run(command,log,lambda:False,timeout=1200,marker=stag)
        r.download_file(rout,output);r.cleanup(marker)
    if not output.exists() or not output.stat().st_size:raise BackendError('Blender 未生成 STL 文件')
    return output
