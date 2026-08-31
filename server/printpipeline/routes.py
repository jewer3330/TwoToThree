"""打印流程 API 路由（独立模块）：导入模型 → 分模块 → AMS 上色 → 发送打印。"""
from __future__ import annotations
import shutil
from pathlib import Path
from fastapi import APIRouter,File,HTTPException,UploadFile
from pydantic import BaseModel,Field
from . import jobs as jobs_mod
from . import pipeline as pipe
from . import send as send_mod
from ..printer import registry as printer_registry

router=APIRouter(prefix='/api/print',tags=['print'])

ALLOWED={'.glb','.stl','.obj','.3mf'}

class CreateInput(BaseModel):
    name:str='打印任务'
class SplitInput(BaseModel):
    maxParts:int=Field(default=12,ge=1,le=64)
class ColorInput(BaseModel):
    assignments:dict[str,str]
class SendInput(BaseModel):
    printerId:str
    startPrint:bool=False   # 是否在上传后直接发送打印命令（需已切片 3MF）

@router.get('/jobs')
def list_jobs():return jobs_mod.list_jobs()

@router.post('/jobs',status_code=201)
def create_job(body:CreateInput):
    return jobs_mod.create_job('',source_type='pending',name=body.name)

@router.get('/jobs/{job_id}')
def get_job(job_id:str):
    j=jobs_mod.get_job(job_id)
    if not j:raise HTTPException(404,'打印任务不存在')
    return j

@router.delete('/jobs/{job_id}',status_code=204)
def delete_job(job_id:str):jobs_mod.delete_job(job_id)

@router.post('/jobs/{job_id}/model',status_code=201)
async def upload_model(job_id:str,file:UploadFile=File(...)):
    j=jobs_mod.get_job(job_id)
    if not j:raise HTTPException(404,'打印任务不存在')
    safe=Path(file.filename or 'model.glb').name
    ext=Path(safe).suffix.lower()
    if ext not in ALLOWED:raise HTTPException(415,'仅支持 GLB/STL/OBJ/3MF')
    d=jobs_mod.job_dir(job_id);d.mkdir(parents=True,exist_ok=True)
    tmp=d/'upload.tmp'
    size=0
    with tmp.open('wb') as out:
        while chunk:=await file.read(1024*1024):
            size+=len(chunk)
            if size>100*1024*1024:raise HTTPException(413,'模型超过 100 MB')
            out.write(chunk)
    from ..core import sha256
    final=d/f'model{ext}';tmp.replace(final)
    rel=f'print_jobs/{job_id}/model{ext}'
    j['modelFile']=rel;j['modelHash']=sha256(final);j['status']='model_ready';j['step']='split'
    jobs_mod.save_job(j)
    return {'modelUrl':f'/data/{rel}','hash':j['modelHash'],'size':size}

@router.post('/jobs/{job_id}/split')
def split_job(job_id:str,body:SplitInput|None=None):
    j=jobs_mod.get_job(job_id)
    if not j:raise HTTPException(404,'打印任务不存在')
    if not j.get('modelFile'):raise HTTPException(409,'请先上传模型')
    model=jobs_mod.job_abs_path(j,'modelFile')
    out_dir=jobs_mod.job_dir(job_id)/'split'
    shutil.rmtree(out_dir,ignore_errors=True)
    max_parts=(body.maxParts if body else None) or j.get('split',{}).get('maxParts',12)
    try:
        report=pipe.split_model(model,out_dir,max_parts=max_parts,timeout_seconds=600)
    except Exception as exc:
        j['split']['status']='failed';j['split']['error']=str(exc)[:300];jobs_mod.save_job(j)
        raise HTTPException(502,f'拆分失败: {exc}')
    parts=[]
    for p in report.get('parts',[]):
        parts.append({
            'index':p['index'],'name':p['name'],
            'stl':f'/data/print_jobs/{job_id}/split/parts/{p["stl"]}',
            'preview':f'/data/print_jobs/{job_id}/split/parts/{p["preview"]}',
            'dims':p['dims'],'volume':p['volume'],
        })
    j['split']={'status':'done','parts':parts,'maxParts':max_parts,'partCount':len(parts)}
    j['color']['palette']=[{'id':f'c{i}','name':n,'hex':h} for i,(n,h) in enumerate([
        ('白','#FFFFFF'),('黑','#1F1F1F'),('红','#E53935'),('橙','#FB8C00'),('黄','#FDD835'),
        ('绿','#43A047'),('蓝','#1E88E5'),('紫','#8E24AA'),('粉','#EC407A'),('青','#00ACC1'),
        ('棕','#6D4C41'),('灰','#9E9E9E')])]
    j['step']='color';jobs_mod.save_job(j)
    return j

@router.post('/jobs/{job_id}/color')
def color_job(job_id:str,body:ColorInput):
    j=jobs_mod.get_job(job_id)
    if not j:raise HTTPException(404,'打印任务不存在')
    if j.get('split',{}).get('status')!='done':raise HTTPException(409,'请先完成分模块')
    pipe.assign_colors(j,body.assignments)
    j['step']='ready'
    # 为预览生成多色 GLB（Blender 给部件上色，简版：仅存分配表；3MF 生成后续）
    jobs_mod.save_job(j)
    return j

@router.get('/jobs/{job_id}/preview')
def preview(job_id:str):
    j=jobs_mod.get_job(job_id)
    if not j:raise HTTPException(404,'打印任务不存在')
    parts=j.get('split',{}).get('parts',[])
    assignments=j.get('color',{}).get('assignments',{})
    out=[]
    for p in parts:
        stl=Path(p['stl']).name
        out.append({'index':p['index'],'name':p['name'],'preview':p['preview'],
                    'color':assignments.get(stl) or assignments.get(p['stl'],'#9E9E9E')})
    return {'jobId':job_id,'parts':out,'palette':j.get('color',{}).get('palette',[])}

@router.post('/jobs/{job_id}/export3mf')
def export_3mf(job_id:str,body:dict|None=None):
    j=jobs_mod.get_job(job_id)
    if not j:raise HTTPException(404,'打印任务不存在')
    if j.get('split',{}).get('status')!='done':raise HTTPException(409,'请先完成分模块')
    parts_dir=jobs_mod.job_dir(job_id)/'split'/'parts'
    colors={Path(p['stl']).name:(j.get('color',{}).get('assignments',{}).get(Path(p['stl']).name) or '#9E9E9E') for p in j['split']['parts']}
    out=jobs_mod.job_dir(job_id)/'multicolor.3mf'
    add_base=bool((body or {}).get('addBase',True))
    try:
        stls=[(p,p.name) for p in sorted(parts_dir.glob('*.stl'))]
        # 网格修复：生成的 3D 模型底部常开口/非流形，切片会报空层 fatal。
        # 每个部件经 pymeshlab 补洞 + Blender 布尔加底座（默认），变成封闭可打印 mesh。
        from .mesh_repair import repair_mesh_remote
        repaired=[]
        for stl,name in stls:
            fixed=jobs_mod.job_dir(job_id)/'split'/'parts'/name
            try:
                if add_base and stl.stat().st_size>1000000:
                    repair_mesh_remote(stl,fixed,add_base=True,base_thickness=3.0,pad=2.0)
            except Exception as exc:
                print(f'mesh repair skip {name}: {exc}')
            repaired.append((fixed,name))
        from .three_mf import build_3mf
        build_3mf(repaired,colors,out)
    except Exception as exc:
        raise HTTPException(502,f'导出 3MF 失败: {exc}')
    from ..core import sha256
    j['color']['preview3mf']=f'print_jobs/{job_id}/multicolor.3mf'
    j['color']['preview3mfHash']=sha256(out)
    j['step']='send';jobs_mod.save_job(j)
    return {'ok':True,'url':f'/data/{j["color"]["preview3mf"]}','size':out.stat().st_size}

@router.post('/jobs/{job_id}/send')
def send_to_printer(job_id:str,body:SendInput):
    j=jobs_mod.get_job(job_id)
    if not j:raise HTTPException(404,'打印任务不存在')
    if not j.get('color',{}).get('preview3mf'):raise HTTPException(409,'请先导出 3MF')
    printer=printer_registry.get_printer(body.printerId)
    if not printer:raise HTTPException(404,'打印机不存在')
    local=jobs_mod.job_abs_path(j,'color.preview3mf') or (jobs_mod.job_dir(job_id)/'multicolor.3mf')
    # 1) FTP 上传
    try:
        remote_name=send_mod.BambuFTP(printer['ip'],printer['accessCode']).upload(local)
    except Exception as exc:
        raise HTTPException(502,f'FTP 上传失败: {exc}')
    result={'ok':True,'uploaded':remote_name,'size':local.stat().st_size}
    # 2) 可选 MQTT 启动
    if body.startPrint and printer.get('serial'):
        md5=send_mod.file_md5(local)
        res=send_mod.mqtt_send_print(printer['serial'],printer['ip'],printer['accessCode'],
                                     j['name'],md5)
        result['printCommand']=res
    return result

@router.post('/printers/{printer_id}/print')
def start_print(printer_id:str,body:dict):
    """对已上传到打印机的已切片 3MF 直接发送打印命令。body: {file, md5, gcode_param?}"""
    printer=printer_registry.get_printer(printer_id)
    if not printer:raise HTTPException(404,'打印机不存在')
    if not printer.get('serial'):raise HTTPException(409,'打印机缺少序列号')
    res=send_mod.mqtt_send_print(printer['serial'],printer['ip'],printer['accessCode'],
                                 body.get('subtaskName','打印任务'),body.get('md5',''),
                                 body.get('gcodeParam','Metadata/plate_1.gcode'))
    if not res.get('ok'):raise HTTPException(502,res.get('error','命令发送失败'))
    return {'ok':True}
