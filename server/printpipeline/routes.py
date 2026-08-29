"""打印流程 API 路由（独立模块）：导入模型 → 分模块 → AMS 上色 → (发送打印后续)。"""
from __future__ import annotations
import shutil
from pathlib import Path
from fastapi import APIRouter,File,HTTPException,UploadFile
from pydantic import BaseModel,Field
from . import jobs as jobs_mod
from . import pipeline as pipe

router=APIRouter(prefix='/api/print',tags=['print'])

ALLOWED={'.glb','.stl','.obj','.3mf'}

class CreateInput(BaseModel):
    name:str='打印任务'
class SplitInput(BaseModel):
    maxParts:int=Field(default=12,ge=1,le=64)
class ColorInput(BaseModel):
    assignments:dict[str,str]

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
        report=pipe.split_model(model,out_dir,max_parts=max_parts)
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
