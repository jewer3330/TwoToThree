from __future__ import annotations
import base64, json, os, shlex, shutil, subprocess, threading, time, uuid
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
REMOTE_OS=os.environ.get('PRINT3D_REMOTE_OS','windows')
REMOTE_PORT=int(os.environ.get('PRINT3D_REMOTE_PORT','22') or 22)
REMOTE_PASSWORD=os.environ.get('PRINT3D_REMOTE_PASSWORD','')

class BackendError(RuntimeError):pass
class CancelledError(RuntimeError):pass

def remote():
    """当前线程绑定的主机 Remote；否则退回 env 单机配置。"""
    bound=getattr(_local,'remote',None)
    if bound is not None:return bound
    if MODE=='remote' and REMOTE_HOST:
        return Remote(REMOTE_HOST,REMOTE_USER,Path(REMOTE_KEY) if REMOTE_KEY else None,
                      REMOTE_ROOT,REMOTE_EXT,REMOTE_WORK,os_type=REMOTE_OS,port=REMOTE_PORT,password=REMOTE_PASSWORD)
    return None

_local=threading.local()
def bind_host(cfg:dict|None):
    """绑定当前线程执行主机（worker 领取任务时调用）。cfg=None 解除绑定。"""
    if cfg is None:
        _local.remote=None;return
    _local.remote=remote_from_cfg(cfg)

def bind_job(job_id:str|None):
    """绑定当前线程的 job_id（用于传输状态持久化）。None 解除。"""
    _local.job_id=job_id
def current_job_id()->str:
    return getattr(_local,'job_id','') or ''

def remote_from_cfg(cfg:dict):
    """根据主机配置返回 Remote（SSH）或 SelfregRemote（WS 自注册节点）。

    返回对象附加 _host_cfg（注册表原始配置），供 capabilities() 在线程绑定
    主机时按主机 status.caps 判定能力（selfreg 由 agent 上报、SSH 由探针刷新）。
    """
    if not cfg or not cfg.get('id'):
        return None
    r=None
    if cfg.get('provider') == 'selfreg':
        from .gpu import selfreg as _sr
        from .gpu.selfreg_remote import SelfregRemote
        agent = _sr._agents.get(cfg['id'])
        node = agent.get('node') if agent else None
        r=SelfregRemote(cfg['id'], node)
    elif cfg.get('host'):
        r=Remote(
            cfg['host'],
            cfg.get('user') or 'root',
            Path(cfg['key']) if cfg.get('key') else None,
            cfg.get('root') or '',
            cfg.get('ext') or '',
            cfg.get('work') or '',
            os_type=cfg.get('os') or 'windows',
            port=int(cfg.get('port') or 22),
            password=cfg.get('password') or '',
        )
    if r is not None:
        r._host_cfg=dict(cfg)
    return r

def _host_cfg_snapshot(r:'Remote')->dict:
    """传输状态持久化所需的连接快照（含密码，仅存主控本地 transfer_state.db）。"""
    return {'host':r.host,'user':r.user,'key':str(r.key) if r.key else '',
            'root':r.root,'ext':r.ext,'work':r.work,
            'os':r.os_type,'port':r.port,'password':r.password}


class Remote:
    def __init__(self,host,user,key,root,ext,work,os_type='windows',port=22,password=''):
        self.host=host;self.user=user or 'root';self.key=key;self.root=root or '';self.ext=ext or '';self.work=work or ''
        self.os_type=(os_type or 'windows').lower();self.port=int(port or 22);self.password=password or ''
    @property
    def is_windows(self):return getattr(self,'os_type','windows')!='linux'
    @property
    def is_linux(self):return getattr(self,'os_type','')=='linux'
    @property
    def sep(self):return '\\' if self.is_windows else '/'
    def norm(self,p:str)->str:
        return str(p).replace('/','\\') if self.is_windows else str(p).replace('\\','/')
    def join(self,*parts)->str:
        out=[]
        for i,p in enumerate(parts):
            if p in (None,'','.'):continue
            s=self.norm(str(p))
            # 首段保留绝对路径的前导分隔符，只去尾；后续段去头尾。
            s=s.rstrip(self.sep) if i==0 else s.strip(self.sep)
            if s:out.append(s)
        return self.sep.join(out)
    def _split(self,p:str)->tuple[str,str]:
        p=self.norm(p).rstrip(self.sep)
        return p.rsplit(self.sep,1) if self.sep in p else ('',p)
    def _ssh_args(self,for_scp:bool=False)->list[str]:
        args=[]
        if self.port and self.port!=22:args+=['-P' if for_scp else '-p',str(self.port)]
        if self.key and Path(self.key).exists():
            args+=['-i',str(self.key),'-o','BatchMode=yes']
        else:
            args+=['-o','BatchMode=no','-o','PubkeyAuthentication=no']
        args+=['-o','ConnectTimeout=15','-o','StrictHostKeyChecking=accept-new']
        return args
    def _wrap(self,argv:list[str])->list[str]:
        return ['sshpass','-p',self.password]+list(argv) if self.password else list(argv)
    def _ssh(self)->list[str]:
        return self._wrap(['ssh']+self._ssh_args()+[f'{self.user}@{self.host}'])
    def _q(self,arg):
        if '"' in arg:arg=arg.replace('"','\\"')
        return f'"{arg}"'
    def _remote_cmd(self,command:list[str],cwd_remote:str|None=None)->str:
        if self.is_windows:
            cmd=' '.join(self._q(a) for a in command)
            cmd=f'set STUDIO_EXTERNAL_ROOT={self.ext} && '+cmd
            if cwd_remote:cmd=f'cd /d {self._q(cwd_remote)} && {cmd}'
            return cmd
        cmd=' '.join(shlex.quote(str(a)) for a in command)
        cmd=f'export STUDIO_EXTERNAL_ROOT={shlex.quote(self.ext)} && '+cmd
        if cwd_remote:cmd=f'cd {shlex.quote(cwd_remote)} && {cmd}'
        return cmd
    def run(self,command,log:Callable[[str],None],cancelled:Callable[[],bool],timeout:int=3600,cwd_remote:str|None=None,marker:str=''):
        remote_cmd=self._remote_cmd(command,cwd_remote)
        full=self._ssh()+[remote_cmd]
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
            if self.is_windows:
                clause=marker.replace("'","''")
                script=f"Get-CimInstance Win32_Process | Where-Object {{ $_.CommandLine -like '*{clause}*' }} | ForEach-Object {{ Stop-Process -Id $_.ProcessId -Force }}"
                subprocess.run(self._ssh()+self._ps(script),timeout=25,capture_output=True)
            else:
                script=f"pkill -9 -f '{marker}' 2>/dev/null; true"
                subprocess.run(self._ssh()+[script],timeout=25,capture_output=True)
        except Exception:pass
    def _ps(self,script:str):
        encoded=base64.b64encode(script.encode('utf-16-le')).decode('ascii')
        return ['powershell','-NoProfile','-EncodedCommand',encoded]
    def stage(self,marker:str):return self.join(self.work,marker)
    def _mkdir(self,path:str)->bool:
        if self.is_windows:
            out=self.cmd(['powershell','-NoProfile','-Command',f'New-Item -ItemType Directory -Force -Path {path} | Out-Null'])
        else:
            out=self.cmd(['mkdir','-p',path])
        return out.returncode==0
    def prepare(self,marker:str,locals_:list[Path]):
        stag=self.stage(marker)
        # 确保远端 staging 目录存在（重试，网络抖动时可能失败）
        for _ in range(3):
            try:
                if self._mkdir(stag):break
            except Exception:pass
            time.sleep(3)
        for p in locals_:
            if p.exists():
                target=self.join(stag,p.name)
                for attempt in range(3):
                    try:
                        self.upload(p,target);break
                    except Exception:
                        if attempt==2:raise
                        self._mkdir(stag)
                        time.sleep(4)
    def cmd(self,command,timeout:int=25):
        if self.is_windows:
            args=' '.join("'"+a.replace("'","''")+"'" for a in command)
            script=f'[Console]::OutputEncoding=[System.Text.Encoding]::UTF8; & {args}'
            return subprocess.run(self._ssh()+self._ps(script),capture_output=True,text=True,errors='replace',timeout=timeout)
        script=' '.join(shlex.quote(str(a)) for a in command)
        return subprocess.run(self._ssh()+[script],capture_output=True,text=True,errors='replace',timeout=timeout)
    def upload(self,local:Path,remote_abs:str):
        """scp 上传（P0：不经过任何 CDN/中转）。"""
        self._retry(lambda:subprocess.run(self._scp_cmd()+[str(local),f'{self.user}@{self.host}:{remote_abs.replace(chr(92),"/")}'],check=True,timeout=300))
    def _remote_exists(self,path:str)->bool:
        """远端存在性检查。无法确认（命令失败/异常/超时）必须抛异常，禁止返回 True。"""
        from .transfers import TransferError,TRANSFER_FAILED
        try:
            if self.is_windows:
                out=self.cmd(['powershell','-NoProfile','-Command',f"Test-Path '{path.replace(chr(92),'/')}'"],timeout=25)
                if out.returncode!=0:
                    raise TransferError(TRANSFER_FAILED,f'远端存在性检查命令失败（无法确认）: {path}')
                return out.stdout.strip().lower()=='true'
            out=self.cmd(['test','-e',path.replace(chr(92),'/')],timeout=25)
            return out.returncode==0
        except TransferError:
            raise
        except Exception as exc:
            raise TransferError(TRANSFER_FAILED,f'远端存在性检查失败（无法确认，禁止乐观通过）: {path}: {exc}')
    def remote_metadata(self,remote_file:str)->tuple[int|None,str|None]:
        """一次远端调用取得文件 size + SHA-256。

        返回 (size, sha256)。无法取得（文件缺失/命令失败）抛 TransferError。
        用于传输前持久化 expected_size/expected_sha256 并在下载后校验。
        """
        from .transfers import TransferError,TRANSFER_FAILED
        remote_file=self.norm(remote_file)
        try:
            if self.is_windows:
                script=(f"if(Test-Path '{remote_file}'){{$i=Get-Item '{remote_file}';"
                        f"$h=Get-FileHash '{remote_file}' -Algorithm SHA256;"
                        f"Write-Output ($i.Length.ToString()+'|'+$h.Hash.ToLower())}}else{{Write-Output 'MISSING'}}")
                out=self.cmd(['powershell','-NoProfile','-Command',script],timeout=60)
            else:
                script=(f"if [ -f '{remote_file}' ]; then echo \"$(stat -c%s '{remote_file}')|$(sha256sum '{remote_file}' | cut -d' ' -f1)\"; else echo MISSING; fi")
                out=self.cmd(['bash','-lc',script],timeout=60)
        except Exception as exc:
            raise TransferError(TRANSFER_FAILED,f'远端元数据获取失败: {remote_file}: {exc}')
        if out.returncode!=0:
            raise TransferError(TRANSFER_FAILED,f'远端元数据命令失败: {remote_file}')
        text=out.stdout.strip()
        if text=='MISSING' or '|' not in text:
            raise TransferError(TRANSFER_FAILED,f'远端产物缺失或无法取得元数据: {remote_file}')
        size_s,sha=text.split('|',1)
        try:return int(size_s),sha.strip()
        except Exception:
            raise TransferError(TRANSFER_FAILED,f'远端元数据格式异常: {remote_file}: {text!r}')

    def remote_archive_metadata(self,remote_dir:str)->tuple[str,int|None,str|None]:
        """对远端目录压缩归档，返回 (tgz_abs_path, size, sha256)。

        目录没有单一文件可校验，故先归档，再对归档文件取 size+sha256 作为校验基准。
        """
        from .transfers import TransferError,TRANSFER_FAILED
        remote_dir=self.norm(remote_dir)
        parent,name=self._split(remote_dir)
        tgz=f'{remote_dir}.tgz'
        if self.is_windows:
            out=self.cmd(['powershell','-NoProfile','-Command',
                          f"tar -czf '{tgz}' -C '{parent}' '{name}'; if(Test-Path '{tgz}'){{$true}}else{{exit 1}}"],timeout=120)
        else:
            out=self.cmd(['bash','-lc',f"tar -czf '{tgz}' -C '{parent}' '{name}' && test -f '{tgz}'"],timeout=120)
        if out.returncode!=0:raise TransferError(TRANSFER_FAILED,f'远端压缩失败: {remote_dir}')
        size,sha=self.remote_metadata(tgz)
        return tgz,size,sha

    def download(self,remote_file:str,local_file:Path,expected_size:int|None=None,expected_sha256:str|None=None,kind:str='file',legacy_scp:bool=True):
        """统一传输入口：scp 拉取 + 校验（长度/SHA-256/GLB）。

        legacy_scp=True 表示当前经 SCP（P0 保留旧路径，明确标记 legacy；不静默走 CDN/DERP
        中转）。后续 P1/P2 以 IPv6 原生直连替换。
        """
        from .transfers import TransferError,TRANSFER_FAILED,CHECKSUM_MISMATCH,verify_file
        local_file.parent.mkdir(parents=True,exist_ok=True)
        try:
            self._retry(lambda:subprocess.run(self._scp_cmd()+[f'{self.user}@{self.host}:{remote_file.replace(chr(92),"/")}',str(local_file)],check=True,timeout=600))
        except subprocess.CalledProcessError as exc:
            raise TransferError(TRANSFER_FAILED,f'传输失败（legacy_scp）: {remote_file}: {exc}')
        try:
            verify_file(local_file,expected_size,expected_sha256,kind)
        except TransferError:
            local_file.unlink(missing_ok=True)
            raise
    def download_dir(self,remote_dir:str,local_dir:Path,expected_size:int|None=None,expected_sha256:str|None=None):
        """远端目录压缩后回传并解压；归档取 size+sha256 作为校验基准。

        幂等：解压后上提目录内容时，若目标已有同名条目（重试/重复调用/残留），
        先删除再移动，避免 shutil.move 抛 "Destination path ... already exists"
        使已成功的远端渲染产物无法落库。
        """
        import tarfile
        from .transfers import TransferError,TRANSFER_FAILED
        remote_dir=self.norm(remote_dir)
        parent,name=self._split(remote_dir)
        local_dir.mkdir(parents=True,exist_ok=True)
        tmp=local_dir/f'{name}.tgz'
        try:
            tgz,size,sha=self.remote_archive_metadata(remote_dir)
            self.download(tgz,tmp,expected_size=size or expected_size,expected_sha256=sha or expected_sha256,kind='file')
            with tarfile.open(tmp,'r:gz') as t:t.extractall(str(local_dir))
            child=local_dir/name
            if child.is_dir() and child!=local_dir:
                for item in list(child.iterdir()):
                    target=local_dir/item.name
                    if target.exists():
                        if target.is_dir():shutil.rmtree(target,ignore_errors=True)
                        else:target.unlink()
                    shutil.move(str(item),str(target))
                shutil.rmtree(child,ignore_errors=True)
        finally:
            tmp.unlink(missing_ok=True)
    def download_file(self,remote_file:str,local_file:Path,expected_size:int|None=None,expected_sha256:str|None=None,kind:str='file'):
        """单文件传输（统一入口）。"""
        self.download(remote_file,local_file,expected_size,expected_sha256,kind)
    def download_compressed(self,remote_file:str,local_file:Path,expected_size:int|None=None,expected_sha256:str|None=None,kind:str='glb'):
        """远端 tar.gz 压缩后回传并解压（统一入口 + 校验）。"""
        import tarfile
        from .transfers import TransferError,TRANSFER_FAILED,verify_file
        remote_file=self.norm(remote_file)
        remote_dir,remote_name=self._split(remote_file)
        tmp=local_file.with_suffix(local_file.suffix+'.tgz')
        try:
            if self.is_windows:
                out=self.cmd(['powershell','-NoProfile','-Command',f"tar -czf '{remote_file}.tgz' -C '{remote_dir}' '{remote_name}'; if(Test-Path '{remote_file}.tgz'){{$true}}else{{exit 1}}"],timeout=120)
            else:
                out=self.cmd(['bash','-lc',f"tar -czf '{remote_file}.tgz' -C '{remote_dir}' '{remote_name}' && test -f '{remote_file}.tgz'"],timeout=120)
            if out.returncode!=0:raise TransferError(TRANSFER_FAILED,f'远端压缩失败: {remote_file}')
            self.download(f'{remote_file}.tgz',tmp,kind='file')
            with tarfile.open(tmp,'r:gz') as t:t.extract(local_file.name,str(local_file.parent))
            if not local_file.exists():raise TransferError(TRANSFER_FAILED,'压缩包解压未生成目标文件')
            verify_file(local_file,expected_size,expected_sha256,kind)
        finally:
            tmp.unlink(missing_ok=True)
    def _scp_cmd(self,extra:list[str]|None=None)->list[str]:
        args=['scp','-q',*(extra or [])]+self._ssh_args(for_scp=True)+['-o','ServerAliveInterval=15','-o','ServerAliveCountMax=4']
        return self._wrap(args)
    def _retry(self,fn,attempts=5):
        last=None
        for i in range(attempts):
            try:return fn()
            except subprocess.CalledProcessError as exc:
                last=exc;time.sleep(5*(i+1))
        raise last
    def cleanup(self,marker:str,committed:bool=False):
        """清理远端 staging。P0：只有主控确认 artifact_committed 后才真正删除；
        否则跳过（GPU 产物保留，等待定时清理）。"""
        if not committed:
            return
        try:
            if self.is_windows:
                self.cmd(['powershell','-NoProfile','-Command',f'Remove-Item -Recurse -Force {self.stage(marker)} -ErrorAction SilentlyContinue'])
            else:
                self.cmd(['rm','-rf',self.stage(marker)])
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

def _rc(r:'Remote|None'=None):
    r=r or remote()
    is_windows=r.is_windows if r else (os.name=='nt')
    ext=r.ext if r else REMOTE_EXT
    root=r.root if r else REMOTE_ROOT
    if is_windows:
        ext=ext.replace('/','\\');root=root.replace('/','\\')
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
    ext=ext.replace('\\','/').rstrip('/');root=root.replace('\\','/').rstrip('/')
    return {
        'python':f'{ext}/local/hunyuan-bootstrap/bin/python',
        'model':f'{ext}/local/Hunyuan3D-2.1-model',
        'runner':f'{root}/pipeline/run_hunyuan_yoyo.py',
        'mv_model':f'{ext}/local/Hunyuan3D-2mv-model-v2',
        'mv_runner':f'{root}/pipeline/run_hunyuan_multiview.py',
        'sf3d_py':f'{ext}/local/stable-fast-3d/.venv-runtime/bin/python',
        'sf3d_repo':f'{ext}/local/stable-fast-3d',
        'triposr_py':f'{ext}/local/TripoSR/.venv-runtime/bin/python',
        'triposr_repo':f'{ext}/local/TripoSR',
        'blender':f'{ext}/local/blender/blender',
        'renderer':f'{root}/pipeline/blender_render_job.py',
        'refiner':f'{root}/pipeline/blender_auto_refine.py',
        'stl_exporter':f'{root}/pipeline/blender_export_stl.py',
    }

def capabilities():
    """当前执行上下文可用能力。

    优先级：线程绑定主机（worker 被调度器派到某台 GPU）> env 远程主机 > 本机。
    绑定主机的能力取注册表 status.caps（selfreg=agent 上报、SSH=探针刷新），
    与调度器 _pick_host 的判定一致，避免控制面因本地无权重/Blender 而误判
    environment unavailable，导致任务永远不落 GPU。
    """
    bound=getattr(_local,'remote',None)
    hcfg=getattr(bound,'_host_cfg',None) if bound is not None else None
    if bound is not None and hcfg and hcfg.get('id'):
        try:
            from .gpu import hosts as gpu_hosts
            for h in gpu_hosts.list_hosts():
                if h.get('id')==hcfg['id']:
                    caps=h.get('status',{}).get('caps') or {}
                    return {k:bool(caps.get(k)) for k in _CAP_KEYS}
        except Exception:
            pass
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

def _test_paths(r:Remote,paths:list[str])->list[bool]:
    """一次 SSH 往返批量检测远端路径存在性。"""
    if r.is_windows:
        probe=';'.join(f"Write-Output (Test-Path '{p}')" for p in paths)
        out=r.cmd(['powershell','-NoProfile','-Command',probe],timeout=40)
    else:
        probe='; '.join(f"test -e '{p}' && echo True || echo False" for p in paths)
        out=r.cmd(['bash','-lc',probe],timeout=40)
    return [l.strip().lower()=='true' for l in out.stdout.splitlines() if l.strip()]

def _file_size(r:Remote,path:str)->int:
    if r.is_windows:
        out=r.cmd(['powershell','-NoProfile','-Command',f"if(Test-Path '{path}'){{(Get-Item '{path}').Length}}else{{0}}"])
    else:
        out=r.cmd(['bash','-lc',f"if [ -f '{path}' ]; then stat -c%s '{path}'; else echo 0; fi"])
    try:return int((out.stdout or '').strip() or 0)
    except Exception:return 0

def _remote_capabilities(r:Remote|None=None)->dict:
    global _caps_cache,_caps_at
    r=r or remote()
    if not r:return {k:False for k in ('hunyuan3d','hunyuan3dMultiview','sf3d','triposr','blender','blenderRefinement','blenderStlExport')}
    if _caps_cache and time.monotonic()-_caps_at<10:return _caps_cache
    rc=_rc(r)
    checks=[('hunyuan3d',rc['python']),('hunyuan3d',rc['model']),('hunyuan3d',rc['runner']),
            ('hunyuan3dMultiview',rc['python']),('hunyuan3dMultiview',rc['mv_runner']),('hunyuan3dMultiview',rc['mv_model']),
            ('sf3d',rc['sf3d_py']),('sf3d',rc['sf3d_repo']),
            ('triposr',rc['triposr_py']),('triposr',rc['triposr_repo']),
            ('blender',rc['blender']),('blender',rc['renderer']),
            ('blenderRefinement',rc['blender']),('blenderRefinement',rc['refiner']),
            ('blenderStlExport',rc['blender']),('blenderStlExport',rc['stl_exporter'])]
    wanted={c for c,_ in checks};got=set()
    try:
        flags=_test_paths(r,[p for _,p in checks])
        for (cap,_),ok in zip(checks,flags):
            if ok:got.add(cap)
    except Exception:pass
    caps={c:(c in got) for c in wanted}
    if caps.get('hunyuan3dMultiview'):
        try:
            mw=r.join(rc['mv_model'],'hunyuan3d-dit-v2-mv','model.fp16.safetensors')
            caps['hunyuan3dMultiview']=caps['hunyuan3dMultiview'] and _file_size(r,mw)==HUNYUAN_MV_EXPECTED_BYTES
        except Exception:pass
    _caps_cache=caps;_caps_at=time.monotonic();return caps

def _probe_autodl_state(cfg:dict)->dict:
    """查询 AutoDL 实例生命周期状态（开机/关机/运行中）。失败返回 unknown。"""
    try:
        from .autodl import AutoDlClient
        token=cfg.get('token') or ''
        client=AutoDlClient(token or None)
        state=client.status(cfg.get('instanceUuid') or '')
        return {'running':state=='running','state':state}
    except Exception as exc:
        return {'running':False,'state':'unknown','error':str(exc)[:120]}

_CAP_KEYS=('hunyuan3d','hunyuan3dMultiview','sf3d','triposr','blender','blenderRefinement','blenderStlExport')
# checks 顺序对应的能力（与 _rc 探测列表一致）：3×hunyuan3d, 3×mv, 2×sf3d, 2×triposr, 1×blender, 1×renderer, 1×refiner, 1×stl
_CAP_MAP=[('hunyuan3d',0),('hunyuan3d',1),('hunyuan3d',2),('sf3d',3),('sf3d',4),
          ('triposr',5),('triposr',6),('blender',7),('blender',8),
          ('blenderRefinement',7),('blenderRefinement',9),('blenderStlExport',7),('blenderStlExport',10)]

def probe_host(cfg:dict)->dict:
    """探测一台主机的完整健康状态（GPU/显存/磁盘/能力）。供 GPU 控制面板轮询。

    provider='autodl' 的节点先查 AutoDL 实例生命周期状态：非 running（关机/开机中）
    直接返回 offline + autodlState，不浪费 SSH 探测；running 时继续 SSH 探测。
    """
    if cfg.get('provider')=='autodl':
        autodl=_probe_autodl_state(cfg)
        if not autodl.get('running'):
            return {'online':False,'gpu':None,'memTotal':None,'memUsed':None,'diskFree':None,
                    'latencyMs':None,'route':'autodl','caps':{},'lastError':None,
                    'autodlState':autodl.get('state','unknown')}
    r=remote_from_cfg(cfg)
    if not r:return {'online':False,'gpu':None,'memTotal':None,'memUsed':None,'diskFree':None,'latencyMs':None,'route':None,'caps':{},'lastError':'no remote'}
    result={'online':False,'gpu':None,'memTotal':None,'memUsed':None,'diskFree':None,'latencyMs':None,'route':None,'caps':{},'lastError':None}
    try:
        rc=_rc(r)
        checks=[rc['python'],rc['model'],rc['runner'],rc['sf3d_py'],rc['sf3d_repo'],
                rc['triposr_py'],rc['triposr_repo'],rc['blender'],rc['renderer'],
                rc['refiner'],rc['stl_exporter']]
        t0=time.monotonic()
        if r.is_windows:
            probe_caps=';'.join(f"Write-Output (Test-Path '{p}')" for p in checks)
            disk_letter=cfg.get('work','D:')[0]
            script=(f"$g=(& nvidia-smi --query-gpu=name,memory.total,memory.used --format=csv,noheader,nounits) 2>$null; "
                    f"Write-Output ('GPU:'+$g); "
                    f"$f=(Get-PSDrive -Name {disk_letter} -ErrorAction SilentlyContinue).Free; "
                    f"Write-Output ('DISK:'+$f); {probe_caps}")
            out=r.cmd(['powershell','-NoProfile','-Command',script],timeout=40)
        else:
            probe_caps='; '.join(f"test -e '{p}' && echo True || echo False" for p in checks)
            disk_path=shlex.quote(r.work or '/root')
            script=(f"g=$(nvidia-smi --query-gpu=name,memory.total,memory.used --format=csv,noheader,nounits 2>/dev/null | head -1); "
                    f"echo \"GPU:$g\"; "
                    f"echo \"DISK:$(df -Pk {disk_path} | awk 'NR==2{{print int($4*1024)}}')\"; "
                    f"{probe_caps}")
            out=r.cmd(['bash','-lc',script],timeout=40)
        result['latencyMs']=round((time.monotonic()-t0)*1000)
        if out.returncode==0:
            gpu_line=next((l for l in out.stdout.splitlines() if l.startswith('GPU:')),'')
            gpu_data=gpu_line[4:].strip()
            if gpu_data:
                parts=[p.strip() for p in gpu_data.split(',')]
                if len(parts)>=3:
                    result['gpu']=parts[0]
                    try:result['memTotal']=int(float(parts[1]));result['memUsed']=int(float(parts[2]))
                    except Exception:pass
            result['online']=bool(result['gpu'])
            disk_line=next((l for l in out.stdout.splitlines() if l.startswith('DISK:')),'')
            free=disk_line[5:].strip()
            if free:
                try:result['diskFree']=round(float(free)/1073741824,1)
                except Exception:pass
            cap_lines=[l for l in out.stdout.splitlines() if l.strip() and not l.startswith('GPU:') and not l.startswith('DISK:')]
            flags=[l.strip().lower()=='true' for l in cap_lines]
            caps={c:False for c in _CAP_KEYS}
            for cap,idx in _CAP_MAP:
                if idx<len(flags) and flags[idx]:caps[cap]=True
            result['caps']=caps
    except Exception as exc:
        result['lastError']=str(exc)[:200]
    return result

def remote_gpu()->dict|None:
    if remote() is None:return None
    r=remote()
    try:
        if r.is_windows:
            out=r.cmd(['nvidia-smi','--query-gpu=name','--format=csv,noheader'])
        else:
            out=r.cmd(['bash','-lc','nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null'])
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
    if remote() is None:
        command=[str(HUNYUAN_PY),str(HUNYUAN_RUNNER),'--image',str(image),'--model',str(HUNYUAN_MODEL),'--output',str(output),'--processed-image-output',str(processed),'--steps',str(steps),'--resolution',str(resolution),'--seed',str(seed)]
        log(f'Hunyuan3D 2.1 启动：steps={steps}, octree={resolution}, seed={seed}')
        run_process(command,ROOT,log,cancelled,timeout=2400)
        if not output.exists():raise BackendError('Hunyuan3D 未生成 GLB')
        return {'backend':'hunyuan3d','modelVersion':'tencent/Hunyuan3D-2.1','steps':steps,'resolution':resolution,'seed':seed,'processedImage':str(processed),'command':[Path(x).name if i<2 else x for i,x in enumerate(command)]}
    r=remote();rc=_rc(r);marker=_marker();stag=r.stage(marker);r.prepare(marker,[image])
    rimg=r.join(stag,image.name);rout=r.join(stag,output.name);rproc=r.join(stag,'condition-front.png')
    command=[rc['python'],rc['runner'],'--image',rimg,'--model',rc['model'],'--output',rout,'--processed-image-output',rproc,'--steps',str(steps),'--resolution',str(resolution),'--seed',str(seed)]
    log(f'Hunyuan3D 2.1 远程启动（{r.host}）：steps={steps}, octree={resolution}, seed={seed}')
    # 4060 类节点 CPU-offload：加载+20步采样+网格导出实测可达 55 分钟，
    # 3000s 上限会误杀正常任务 → 放宽到 4500s（75 分钟）。
    r.run(command,log,cancelled,timeout=4500,marker=stag)
    from .transfers import record_pending,mark_downloaded,mark_verified
    cfg=_host_cfg_snapshot(r)
    # P0：传输前一次远端调用取得 size+SHA-256，持久化 expected 并在下载后校验
    size,sha=r.remote_metadata(rout)
    tid=record_pending(current_job_id(),r.host,marker,rout,str(output),kind='glb',expected_size=size,expected_sha256=sha,host_cfg=cfg)
    r.download_compressed(rout,output,expected_size=size,expected_sha256=sha,kind='glb')
    mark_downloaded(tid);mark_verified(tid)
    try:r.download_file(rproc,processed)
    except Exception:pass
    # 不 commit、不清理远端：等待调用方完成 Artifact 持久化注册后 commit_transfer(tid)
    if not output.exists():raise BackendError('Hunyuan3D 未生成 GLB')
    return {'backend':'hunyuan3d','modelVersion':'tencent/Hunyuan3D-2.1','steps':steps,'resolution':resolution,'seed':seed,'processedImage':str(processed),'command':[Path(x).name if i<2 else x for i,x in enumerate(command)],'transferTid':tid}

def generate_hunyuan_multiview(images:dict[str,Path],output:Path,seed:int,quality:str,view_weights:dict[str,float],log,cancelled,visual_conditioning:dict|None=None,style:str='realistic'):
    """Run a real multi-view backend; never concatenate views or silently use front only."""
    if not capabilities().get('hunyuan3dMultiview'):
        raise BackendError('检测到多视图素材，但本机未配置 Hunyuan3D-2mv。请安装多视图权重和推理脚本；系统不会静默退回单图生成。')
    required={'front','side','back'};missing=sorted(required-images.keys())
    if missing:raise BackendError(f'多视图生成缺少视角：{missing}')
    steps={'standard':20,'high':30,'ultra':40}.get(quality,20);resolution={'standard':256,'high':384,'ultra':512}.get(quality,256)
    processed=output.parent/'multiview-conditions'
    if remote() is None:
        command=[str(HUNYUAN_PY),str(HUNYUAN_MV_RUNNER),'--model',str(HUNYUAN_MV_MODEL),'--output',str(output),'--processed-dir',str(processed),'--steps',str(steps),'--resolution',str(resolution),'--seed',str(seed)]
        for role in ('front','side','back'):command.extend([f'--{role}',str(images[role])])
        weights={role:max(0.1,min(3.0,float(view_weights.get(role,1.0)))) for role in ('front','side','back')}
        for role in ('front','side','back'):command.extend([f'--{role}-weight',str(weights[role])])
        visual=visual_conditioning or {};mode=str(visual.get('mode','auto')) if visual.get('enabled',True) else 'original';depth_blend=max(0,min(.25,float(visual.get('depthBlend',.15))));command.extend(['--visual-conditioning',mode,'--style',style,'--depth-blend',str(depth_blend)])
        log(f'Hunyuan3D-2mv 启动：views=front,side,back, weights={weights}, steps={steps}, octree={resolution}, seed={seed}, memory=cpu-load/offload')
        run_process(command,ROOT,log,cancelled,timeout=2400)
        if not output.exists():raise BackendError('Hunyuan3D-2mv 未生成 GLB')
    else:
        r=remote();rc=_rc(r);marker=_marker();stag=r.stage(marker)
        r.prepare(marker,[images[role] for role in ('front','side','back')])
        rout=r.join(stag,output.name);rproc=r.join(stag,'multiview-conditions')
        command=[rc['python'],rc['mv_runner'],'--model',rc['mv_model'],'--output',rout,'--processed-dir',rproc,'--steps',str(steps),'--resolution',str(resolution),'--seed',str(seed)]
        for role in ('front','side','back'):command.extend([f'--{role}',r.join(stag,images[role].name)])
        weights={role:max(0.1,min(3.0,float(view_weights.get(role,1.0)))) for role in ('front','side','back')}
        for role in ('front','side','back'):command.extend([f'--{role}-weight',str(weights[role])])
        visual=visual_conditioning or {};mode=str(visual.get('mode','auto')) if visual.get('enabled',True) else 'original';depth_blend=max(0,min(.25,float(visual.get('depthBlend',.15))));command.extend(['--visual-conditioning',mode,'--style',style,'--depth-blend',str(depth_blend)])
        log(f'Hunyuan3D-2mv 远程启动（{r.host}）：views=front,side,back, weights={weights}, steps={steps}, octree={resolution}, seed={seed}')
        # 与单图一致：CPU-offload 节点全流程可能 >50 分钟，放宽上限避免误杀
        r.run(command,log,cancelled,timeout=4500,marker=stag)
        from .transfers import record_pending,mark_downloaded,mark_verified
        cfg=_host_cfg_snapshot(r)
        size,sha=r.remote_metadata(rout)
        tid=record_pending(current_job_id(),r.host,marker,rout,str(output),kind='glb',expected_size=size,expected_sha256=sha,host_cfg=cfg)
        r.download_file(rout,output,expected_size=size,expected_sha256=sha,kind='glb')
        mark_downloaded(tid);mark_verified(tid)
        try:r.download_dir(rproc,processed)
        except Exception:pass
        if not output.exists():raise BackendError('Hunyuan3D-2mv 未生成 GLB')
    visual_root=processed/'visual-candidates';report_path=visual_root/'visual-conditioning-report.json';report=json.loads(report_path.read_text(encoding='utf-8')) if report_path.exists() else {};candidates={role:{name:str(visual_root/role/f'{name}.png') for name in ('original','contour','rgb_depth','depth-cue-experimental')} for role in ('front','side','back')}
    selected_images={role:report.get('views',{}).get(role,{}).get('selected',str(processed/f'condition-{"left" if role=="side" else role}.png')) for role in ('front','side','back')}
    return {'backend':'hunyuan3d-2mv','modelVersion':'tencent/Hunyuan3D-2mv','steps':steps,'resolution':resolution,'seed':seed,'views':['front','side','back'],'viewWeights':weights,'processedImages':selected_images,'visualConditioning':report,'visualConditioningReport':str(report_path),'visualCandidates':candidates}

def generate_sf3d(image:Path,output:Path,texture_resolution:int,log,cancelled):
    staging=output.parent/'sf3d-output';staging.mkdir(parents=True,exist_ok=True)
    if remote() is None:
        command=[str(SF3D_PY),'run.py',str(image),'--output-dir',str(staging),'--texture-resolution',str(texture_resolution),'--remesh_option','none','--target_vertex_count','-1']
        log(f'Stable Fast 3D 启动：texture={texture_resolution}')
        run_process(command,SF3D_REPO,log,cancelled,timeout=1200)
    else:
        r=remote();rc=_rc(r);marker=_marker();stag=r.stage(marker);r.prepare(marker,[image])
        rimg=r.join(stag,image.name);rout_dir=r.join(stag,'sf3d-output')
        command=[rc['sf3d_py'],'run.py',rimg,'--output-dir',rout_dir,'--texture-resolution',str(texture_resolution),'--remesh_option','none','--target_vertex_count','-1']
        log(f'Stable Fast 3D 远程启动（{r.host}）：texture={texture_resolution}')
        r.run(command,log,cancelled,timeout=1500,cwd_remote=rc['sf3d_repo'],marker=stag)
        from .transfers import record_pending,mark_downloaded,mark_verified
        cfg=_host_cfg_snapshot(r)
        tid=record_pending(current_job_id(),r.host,marker,rout_dir,str(staging),kind='dir',host_cfg=cfg)
        r.download_dir(stag,staging)
        mark_downloaded(tid);mark_verified(tid)
    candidates=sorted(staging.rglob('mesh.glb'),key=lambda p:p.stat().st_mtime,reverse=True)
    if not candidates:raise BackendError('SF3D 未生成 mesh.glb')
    output.write_bytes(candidates[0].read_bytes())
    return {'backend':'sf3d','modelVersion':'stabilityai/stable-fast-3d','textureResolution':texture_resolution,'transferTid':tid}

def generate_triposr(image:Path,output:Path,log,cancelled):
    staging=output.parent/'triposr-output';staging.mkdir(parents=True,exist_ok=True)
    if remote() is None:
        command=[str(TRIPOSR_PY),'run.py',str(image),'--output-dir',str(staging),'--model-save-format','glb']
        log('TripoSR 启动')
        run_process(command,TRIPOSR_REPO,log,cancelled,timeout=1200)
    else:
        r=remote();rc=_rc(r);marker=_marker();stag=r.stage(marker);r.prepare(marker,[image])
        rimg=r.join(stag,image.name);rout_dir=r.join(stag,'triposr-output')
        command=[rc['triposr_py'],'run.py',rimg,'--output-dir',rout_dir,'--model-save-format','glb']
        log(f'TripoSR 远程启动（{r.host}）')
        r.run(command,log,cancelled,timeout=1500,cwd_remote=rc['triposr_repo'],marker=stag)
        from .transfers import record_pending,mark_downloaded,mark_verified
        cfg=_host_cfg_snapshot(r)
        tid=record_pending(current_job_id(),r.host,marker,rout_dir,str(staging),kind='dir',host_cfg=cfg)
        r.download_dir(stag,staging)
        mark_downloaded(tid);mark_verified(tid)
    candidates=sorted(staging.rglob('*.glb'),key=lambda p:p.stat().st_mtime,reverse=True)
    if not candidates:raise BackendError('TripoSR 未生成 GLB')
    output.write_bytes(candidates[0].read_bytes())
    return {'backend':'triposr','modelVersion':'stabilityai/TripoSR','transferTid':tid}

def render_blender(source:Path,output_dir:Path,web_glb:Path,log,cancelled,quality:str='standard',texture_resolution:int=0,references:dict[str,Path]|None=None,style_preset:dict|None=None):
    preset=style_preset or {};style_id=str(preset.get('id','realistic'));depth_scale=max(.35,min(1.0,float(preset.get('depthScale',1.0))))
    if remote() is None:
        command=[str(BLENDER),'--background','--factory-startup','--python',str(BLENDER_RENDERER),'--','--input',str(source),'--output-dir',str(output_dir),'--web-glb',str(web_glb),'--quality',quality,'--texture-resolution',str(texture_resolution),'--style',style_id,'--depth-scale',str(depth_scale)]
        for role,path in (references or {}).items():
            if role in ('front','side','back') and path.exists():command.extend([f'--{role}',str(path)])
        log(f'Blender 5.2 后台四视图渲染启动：style={style_id}, depthScale={depth_scale:.2f}')
        run_process(command,ROOT,log,cancelled,timeout=900)
    else:
        r=remote();rc=_rc(r);marker=_marker();stag=r.stage(marker)
        uploads=[source]+[p for role,p in (references or {}).items() if role in ('front','side','back') and p.exists()]
        r.prepare(marker,uploads)
        rsrc=r.join(stag,source.name);renders=r.join(stag,'renders');web_remote=r.join(stag,'web.glb')
        command=[rc['blender'],'--background','--factory-startup','--python',rc['renderer'],'--','--input',rsrc,'--output-dir',renders,'--web-glb',web_remote,'--quality',quality,'--texture-resolution',str(texture_resolution),'--style',style_id,'--depth-scale',str(depth_scale)]
        for role,path in (references or {}).items():
            if role in ('front','side','back') and path.exists():command.extend([f'--{role}',r.join(stag,path.name)])
        log(f'Blender 5.2 远程四视图渲染启动（{r.host}）：style={style_id}, depthScale={depth_scale:.2f}')
        r.run(command,log,cancelled,timeout=1200,marker=stag)
        from .transfers import record_pending,mark_downloaded,mark_verified
        cfg=_host_cfg_snapshot(r)
        size,sha=r.remote_metadata(web_remote)
        tid=record_pending(current_job_id(),r.host,marker,web_remote,str(web_glb),kind='glb',expected_size=size,expected_sha256=sha,host_cfg=cfg)
        r.download_dir(renders,output_dir)
        r.download_compressed(web_remote,web_glb,expected_size=size,expected_sha256=sha,kind='glb')
        mark_downloaded(tid);mark_verified(tid)
        _flatten(output_dir/'renders')
    expected={v:output_dir/f'{v}.png' for v in ('front','left-three-quarter','side','back')}
    missing=[v for v,p in expected.items() if not p.exists()]
    if missing or not web_glb.exists():raise BackendError(f'Blender 产物不完整：{missing}')
    return expected

def refine_blender(source:Path,output_dir:Path,config_path:Path,log,cancelled,reference_image:Path|None=None):
    if remote() is None:
        command=[str(BLENDER),'--background','--factory-startup','--python',str(BLENDER_REFINER),'--','--input',str(source),'--output-dir',str(output_dir),'--config',str(config_path)]
        if reference_image:command.extend(['--reference-image',str(reference_image)])
        log('启动真实 Blender 后台自动精修')
        run_process(command,ROOT,log,cancelled,timeout=1800)
    else:
        r=remote();rc=_rc(r);marker=_marker();stag=r.stage(marker)
        inputs=[source,config_path]+([reference_image] if reference_image else [])
        r.prepare(marker,inputs)
        rsrc=r.join(stag,source.name);rcfg=r.join(stag,config_path.name);rout_dir=r.join(stag,'out')
        command=[rc['blender'],'--background','--factory-startup','--python',rc['refiner'],'--','--input',rsrc,'--output-dir',rout_dir,'--config',rcfg]
        if reference_image:command.extend(['--reference-image',r.join(stag,reference_image.name)])
        log(f'启动远程 Blender 后台自动精修（{r.host}）')
        r.run(command,log,cancelled,timeout=2100,marker=stag)
        from .transfers import record_pending,mark_downloaded,mark_verified
        cfg=_host_cfg_snapshot(r)
        tid=record_pending(current_job_id(),r.host,marker,rout_dir,str(output_dir),kind='dir',host_cfg=cfg)
        r.download_dir(rout_dir,output_dir)
        mark_downloaded(tid);mark_verified(tid)
        _flatten(output_dir/'out')
    report=output_dir/'quality-report.json'
    if not report.exists():raise BackendError('Blender 未生成质量报告')
    result=json.loads(report.read_text(encoding='utf-8'))
    if not (output_dir/'refined.glb').exists():raise BackendError('Blender 未生成 refined.glb')
    return result

def export_stl_blender(source:Path,output:Path,scope:str,unit:str,apply_modifiers:bool,log,target_height_mm:float|None=None):
    if remote() is None:
        command=[str(BLENDER),'--background','--factory-startup','--python',str(BLENDER_STL_EXPORTER),'--','--input',str(source),'--output',str(output),'--scope',scope,'--unit',unit]
        if apply_modifiers:command.append('--apply-modifiers')
        if target_height_mm is not None:command.extend(['--target-height-mm',str(target_height_mm)])
        log(f'Blender STL 导出启动：scope={scope}, unit={unit}, applyModifiers={apply_modifiers}, targetHeightMm={target_height_mm}')
        run_process(command,ROOT,log,lambda:False,timeout=900)
    else:
        r=remote();rc=_rc(r);marker=_marker();stag=r.stage(marker);r.prepare(marker,[source])
        rsrc=r.join(stag,source.name);rout=r.join(stag,output.name)
        command=[rc['blender'],'--background','--factory-startup','--python',rc['stl_exporter'],'--','--input',rsrc,'--output',rout,'--scope',scope,'--unit',unit]
        if apply_modifiers:command.append('--apply-modifiers')
        if target_height_mm is not None:command.extend(['--target-height-mm',str(target_height_mm)])
        log(f'Blender STL 远程导出启动（{r.host}）：scope={scope}, unit={unit}')
        r.run(command,log,lambda:False,timeout=1200,marker=stag)
        from .transfers import record_pending,mark_downloaded,mark_verified
        cfg=_host_cfg_snapshot(r)
        size,sha=r.remote_metadata(rout)
        tid=record_pending(current_job_id(),r.host,marker,rout,str(output),kind='file',expected_size=size,expected_sha256=sha,host_cfg=cfg)
        r.download_file(rout,output,expected_size=size,expected_sha256=sha,kind='file')
        mark_downloaded(tid);mark_verified(tid)
    if not output.exists() or not output.stat().st_size:raise BackendError('Blender 未生成 STL 文件')
    return output
