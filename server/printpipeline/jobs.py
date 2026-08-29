"""打印任务存储（独立模块）。

打印任务 = 导入模型 + 拆分(分模块) + 上色(AMS 分区) 的步骤链，配置持久化在 <DATA>/print_jobs/。
"""
from __future__ import annotations
import json, threading, uuid
from pathlib import Path
from ..core import DATA, now

JOBS_DIR=DATA/'print_jobs'
_lock=threading.RLock()

def _jid():return 'pj_'+uuid.uuid4().hex[:12]
def job_dir(job_id:str)->Path:
    if not job_id.startswith('pj_') or len(job_id)!=15:raise ValueError('Invalid print job id')
    return JOBS_DIR/job_id

def create_job(source:str,source_type:str='upload',name:str='打印任务')->dict:
    with _lock:
        jid=_jid();stamp=now()
        job={'id':jid,'name':name,'source':source,'sourceType':source_type,'status':'created',
             'step':'model','modelFile':None,'modelHash':None,
             'split':{'status':'pending','parts':[],'reportPath':None,'maxParts':12},
             'color':{'status':'pending','palette':[],'assignments':{},'preview3mf':None},
             'createdAt':stamp,'updatedAt':stamp}
        d=job_dir(jid);d.mkdir(parents=True,exist_ok=True)
        (d/'job.json').write_text(json.dumps(job,ensure_ascii=False,indent=2),encoding='utf-8')
        return job

def get_job(job_id:str)->dict|None:
    with _lock:
        f=job_dir(job_id)/'job.json'
        if not f.exists():return None
        return json.loads(f.read_text(encoding='utf-8'))

def save_job(job:dict):
    with _lock:
        job['updatedAt']=now()
        d=job_dir(job['id']);d.mkdir(parents=True,exist_ok=True)
        (d/'job.json').write_text(json.dumps(job,ensure_ascii=False,indent=2),encoding='utf-8')

def list_jobs()->list[dict]:
    with _lock:
        if not JOBS_DIR.exists():return []
        out=[]
        for d in sorted(JOBS_DIR.iterdir(),reverse=True):
            f=d/'job.json'
            if f.exists():
                j=json.loads(f.read_text(encoding='utf-8'))
                j['modelUrl']=model_url(j)
                out.append(j)
        return out

def delete_job(job_id:str):
    with _lock:
        import shutil
        shutil.rmtree(job_dir(job_id),ignore_errors=True)

def model_url(job:dict)->str|None:
    mf=job.get('modelFile')
    if not mf:return None
    if mf.startswith('print_jobs/'):return f'/data/{mf}'
    rel=Path(mf).relative_to(DATA).as_posix()
    return f'/data/{rel}'

def job_abs_path(job:dict,key:str)->Path|None:
    """把 job 里相对 data 的路径转绝对。支持 'a.b.c' 嵌套 key。"""
    v=job
    for part in key.split('.'):
        if not isinstance(v,dict) or part not in v:return None
        v=v[part]
    if not v:return None
    return (DATA/v).resolve() if v.startswith('print_jobs/') else Path(v)

def put_asset(job:dict,key:str,path:Path)->str:
    """复制文件到任务目录，返回相对 data 的路径。"""
    d=job_dir(job['id']);target=d/path.name
    import shutil
    shutil.copy2(path,target)
    rel=f'print_jobs/{job["id"]}/{target.name}'
    job[key]=rel;save_job(job)
    return rel
