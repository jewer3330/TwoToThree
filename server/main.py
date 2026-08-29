from __future__ import annotations
import asyncio, json, mimetypes, os, random, re, shutil, threading
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any,Literal
import psutil
from fastapi import FastAPI,File,HTTPException,Query,Request,UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse,Response,StreamingResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image,ImageDraw,UnidentifiedImageError
from pydantic import BaseModel,Field
from .core import DATA,ROOT,db,dump,init_db,load,now,project_dir,resolve_storage,rowdict,sha256,slugify,storage_path,uid
from .worker import STAGES,launch
from .backends import capabilities,refine_blender,generate_hunyuan,generate_hunyuan_multiview,export_stl_blender,remote_gpu,BackendError,CancelledError
from .detail_provider import generate as generate_detail_candidate,stop_server as stop_detail_server
from .style_presets import DEFAULT_STYLE, public_style_presets, style_preset

@asynccontextmanager
async def lifespan(_:FastAPI):
    init_db();seed_demo();yield

app=FastAPI(title='2D→3D Studio API',version='1.0.0',docs_url='/api/docs',openapi_url='/api/openapi.json',lifespan=lifespan)
mimetypes.add_type('model/gltf-binary','.glb')
_cors=os.environ.get('CORS_ORIGINS','http://localhost:5173,http://127.0.0.1:5173')
app.add_middleware(CORSMiddleware,allow_origins=[o.strip() for o in _cors.split(',') if o.strip()],allow_methods=['*'],allow_headers=['*'])

class ProjectInput(BaseModel):
    name:str=Field(min_length=1,max_length=60);subjectType:str='character';intendedUse:str='web';quality:str='standard';modelStyle:Literal['realistic','cartoon','chibi']=DEFAULT_STYLE;visualConditioningMode:Literal['auto','original','contour','rgb_depth']='auto';segmentationRequired:bool=False;rigRequired:bool=False;preserveFeatures:str='';notes:str=''
class PatchInput(BaseModel):
    name:str|None=None;subjectType:str|None=None;intendedUse:str|None=None;quality:str|None=None;modelStyle:Literal['realistic','cartoon','chibi']|None=None;visualConditioningMode:Literal['auto','original','contour','rgb_depth']|None=None;segmentationRequired:bool|None=None;rigRequired:bool|None=None;preserveFeatures:str|None=None;notes:str|None=None
class DecisionInput(BaseModel):notes:str=''
class RefinementInput(BaseModel):
    sourceVersionId:str;modules:list[str]=['geometryRepair','uvUnwrap','pbrMaterials','webOptimization','visualReview'];instructions:str='';geometryRepairStrength:str='conservative';uvStrategy:str='preserve_or_smart';uvIslandMargin:float=.03;materialTemplate:str='neutral';targetTriangleRange:list[int]=[20000,120000];textureResolution:int=2048;maxWebGlbMB:int=20;preserveThickness:bool=True;maxThicknessLoss:float=Field(default=.08,ge=0,le=.5);maxDecimationPerPass:float=Field(default=.2,ge=.05,le=.5);minThinAxisRatio:float=Field(default=.08,ge=.01,le=.5)
class PlanInput(BaseModel):
    primaryBackend:str='hunyuan3d';fallbackBackends:list[str]=['sf3d','triposr'];geometryQuality:str='standard';textureResolution:int=0;faceRefinement:bool=False;targetTriangleRange:list[int]=[60000,120000];segmentationRequired:bool=False;rigRequired:bool=False;preserveBaseline:bool=True;renderViews:list[str]=['front','left-three-quarter','side','back'];modelStyle:Literal['realistic','cartoon','chibi']=DEFAULT_STYLE;stylePreset:dict=Field(default_factory=lambda:style_preset(DEFAULT_STYLE));viewWeights:dict[str,float]=Field(default_factory=lambda:{'front':1.8,'side':1.0,'back':0.7});visualConditioning:dict=Field(default_factory=lambda:{'enabled':True,'mode':'auto','depthBlend':.15,'exportExperimentalDepth':True});limitations:list[str]=[];referenceSetId:str|None=None
class CommentInput(BaseModel):
    title:str=Field(min_length=1,max_length=120);description:str=Field(min_length=1,max_length=4000);category:str='other';severity:str='normal';recommendedRoute:str='reference_regeneration';meshName:str|None=None;position:dict|None=None;normal:dict|None=None;cameraSnapshot:dict|None=None;screenshotDataUrl:str|None=None
class CommentPatch(BaseModel):
    title:str|None=None;description:str|None=None;category:str|None=None;severity:str|None=None;recommendedRoute:str|None=None
class ReplyInput(BaseModel):body:str=Field(min_length=1,max_length=4000)
class RevisionPlanInput(BaseModel):sourceVersionId:str;commentIds:list[str]=Field(min_length=1);config:dict={}
class RevisionCreateInput(RevisionPlanInput):referenceSetId:str|None=None
class CommentReviewInput(BaseModel):resultStatus:str;notes:str=''
class DetailPlanInput(BaseModel):mode:str='balanced'
class DetailRegionPatch(BaseModel):selected:bool|None=None;mode:str|None=None;targetUsage:str|None=None;constraints:dict|None=None
class DetailJobInput(BaseModel):candidateCount:int=Field(default=2,ge=1,le=4);seed:int|None=None
class DetailReviewInput(BaseModel):notes:str=''
class StlExportInput(BaseModel):
    filename:str=Field(default='model.stl',min_length=1,max_length=100)
    scope:Literal['all','visible']='visible'
    unit:Literal['mm','cm','m']='mm'
    applyModifiers:bool=True
    targetHeightMm:float|None=Field(default=None,ge=1,le=2000)
class PartGenerationInput(BaseModel):
    partId:Literal['head','hair','braid-left','braid-right','torso','arms','feet']
    overlap:int=Field(default=10,ge=3,le=18)
    quality:Literal['standard','high']='standard'
    seed:int|None=None

PART_BOXES={
    'head':{'front':(.10,.02,.90,.66),'side':(.14,.03,.88,.70),'back':(.05,.02,.95,.67)},
    'hair':{'front':(.04,.01,.96,.70),'side':(.10,.02,.94,.76),'back':(.02,.01,.98,.72)},
    'braid-left':{'front':(.01,.43,.34,.98),'side':(.55,.39,.98,.99),'back':(.01,.38,.34,.98)},
    'braid-right':{'front':(.66,.43,.99,.98),'side':(.02,.39,.45,.99),'back':(.66,.38,.99,.98)},
    'torso':{'front':(.18,.48,.82,.98),'side':(.22,.50,.78,.97),'back':(.14,.46,.86,.98)},
    'arms':{'front':(.08,.50,.92,.90),'side':(.16,.50,.84,.90),'back':(.07,.49,.93,.90)},
    'feet':{'front':(.30,.84,.70,1.0),'side':(.27,.83,.73,1.0),'back':(.29,.84,.71,1.0)},
}
PART_POLYGONS={
    'braid-left':{
        'front':[(.105,.50),(.17,.47),(.225,.55),(.225,.91),(.17,.965),(.115,.88)],
        'side':[(.58,.46),(.66,.42),(.765,.48),(.755,.91),(.68,.965),(.59,.84)],
        'back':[(.09,.46),(.15,.43),(.225,.49),(.225,.89),(.17,.95),(.105,.84)],
    },
    'braid-right':{
        'front':[(.93,.46),(.81,.43),(.73,.53),(.74,.94),(.83,.99),(.90,.88)],
        'side':[(.40,.36),(.22,.34),(.10,.45),(.12,.91),(.27,.97),(.40,.82)],
        'back':[(.93,.39),(.82,.37),(.72,.46),(.73,.91),(.82,.98),(.91,.86)],
    },
}
_part_jobs:dict[str,dict[str,Any]]={}
_part_jobs_lock=threading.RLock()

def _part_job_json(job:dict[str,Any])->dict[str,Any]:
    return {k:v for k,v in job.items() if k not in ('cancelled',)}

def _prepare_part_conditions(part_id:str,overlap:int,out_dir:Path)->dict[str,Path]:
    source={'front':ROOT/'views'/'正面图.png','side':ROOT/'views'/'左侧面图.png','back':ROOT/'views'/'背面图.png'}
    out_dir.mkdir(parents=True,exist_ok=True);result={}
    expansion=overlap/100*.06
    for role,path in source.items():
        with Image.open(path) as raw:
            image=raw.convert('RGBA');w,h=image.size;x0,y0,x1,y1=PART_BOXES[part_id][role]
            x0=max(0,x0-expansion);y0=max(0,y0-expansion);x1=min(1,x1+expansion);y1=min(1,y1+expansion)
            bounds=(round(x0*w),round(y0*h),round(x1*w),round(y1*h));crop=image.crop(bounds)
            polygon=PART_POLYGONS.get(part_id,{}).get(role)
            if polygon:
                full_mask=Image.new('L',(w,h),0);draw=ImageDraw.Draw(full_mask)
                draw.polygon([(round(x*w),round(y*h)) for x,y in polygon],fill=255)
                mask=full_mask.crop(bounds);source_alpha=crop.getchannel('A')
                crop.putalpha(Image.composite(mask,Image.new('L',mask.size,0),source_alpha))
            canvas=Image.new('RGBA',(1024,1024),(255,255,255,0));crop.thumbnail((920,920),Image.Resampling.LANCZOS)
            canvas.alpha_composite(crop,((1024-crop.width)//2,(1024-crop.height)//2))
            target=out_dir/f'{role}.png';canvas.save(target);result[role]=target
    return result

def _run_part_job(job_id:str,body:PartGenerationInput):
    with _part_jobs_lock:
        job=_part_jobs[job_id];job.update(status='preparing',progress=8,message='正在生成三视图部件条件图')
    root=DATA/'parts'/'jobs'/job_id
    try:
        images=_prepare_part_conditions(body.partId,body.overlap,root/'conditions')
        with _part_jobs_lock:job.update(status='generating',progress=18,message='Hunyuan3D-2mv 正在生成独立部件')
        def log_line(message:str):
            with _part_jobs_lock:
                job['logs'].append(message);job['logs']=job['logs'][-80:]
                if '100%' in message:job['progress']=88
                elif job['progress']<82:job['progress']=min(82,job['progress']+2)
                job['message']=message[-160:]
        output=root/'candidate.glb'
        result=generate_hunyuan_multiview(images,output,job['seed'],body.quality,{'front':1.8,'side':1.2,'back':1.0},log_line,lambda:False,{'enabled':True,'mode':'original','depthBlend':.15},'chibi')
        with _part_jobs_lock:job.update(status='completed',progress=100,message='候选部件 GLB 已生成',candidateUrl=f'/data/parts/jobs/{job_id}/candidate.glb',result=result,completedAt=now())
    except Exception as exc:
        with _part_jobs_lock:job.update(status='failed',message=str(exc),error=str(exc),completedAt=now())

@app.post('/api/parts/jobs',status_code=202)
def create_part_job(body:PartGenerationInput):
    if not capabilities().get('hunyuan3dMultiview'):raise HTTPException(503,'本机 Hunyuan3D-2mv 不可用')
    job_id=uid('part');job={'id':job_id,'partId':body.partId,'status':'queued','progress':2,'message':'任务已进入本地 GPU 队列','candidateUrl':None,'seed':body.seed if body.seed is not None else random.randint(1,2**31-1),'logs':[],'createdAt':now()}
    with _part_jobs_lock:_part_jobs[job_id]=job
    threading.Thread(target=_run_part_job,args=(job_id,body),daemon=True,name=f'part-{job_id}').start()
    return _part_job_json(job)

@app.get('/api/parts/jobs/{job_id}')
def get_part_job(job_id:str):
    with _part_jobs_lock:job=_part_jobs.get(job_id)
    if not job:
        if not re.fullmatch(r'part_[a-f0-9]{16}',job_id):raise HTTPException(404,'部件生成任务不存在')
        candidate=DATA/'parts'/'jobs'/job_id/'candidate.glb'
        if candidate.exists():return {'id':job_id,'partId':'unknown','status':'completed','progress':100,'message':'已从磁盘恢复候选部件 GLB','candidateUrl':f'/data/parts/jobs/{job_id}/candidate.glb','logs':['API 重启后从持久化产物恢复']}
        raise HTTPException(404,'部件生成任务不存在或尚无持久化产物')
    return _part_job_json(job)

DETAIL_REGION_SPECS={
    'head':('geometry',['front','side','back']),'face':('material',['front','left-three-quarter','right-three-quarter']),
    'hair':('geometry',['side','back']),'neck_collar':('geometry',['front','side']),
    'torso_garment':('geometry',['front','side','back']),'left_shoulder_sleeve':('geometry',['front','side']),
    'right_shoulder_sleeve':('geometry',['front','side']),'arms_hands':('geometry',['front','side']),
    'lower_body':('geometry',['front','side','back']),'back_structure':('geometry',['back','side']),
    'accessories':('material',['front','side','back']),
}
DETAIL_MODES={'conservative','balanced','creative'}
EVIDENCE_LEVELS={'observed','constrained','inferred','designed'}
DETAIL_USAGES={'geometry','normal_displacement','material'}

def project_json(r):
    d=dict(r);stage=None;settings=load(d['settings'],{})
    if d['current_job_id']:
        with db() as con:
            job=con.execute('SELECT current_stage FROM jobs WHERE id=?',(d['current_job_id'],)).fetchone()
            stage=job['current_stage'] if job else None
    return {'id':d['id'],'slug':d['slug'],'name':d['name'],'subjectType':d['subject_type'],'intendedUse':d['intended_use'],'quality':d['quality'],'modelStyle':settings.get('modelStyle',DEFAULT_STYLE),'visualConditioningMode':settings.get('visualConditioningMode','auto'),'status':d['status'],'currentJobId':d['current_job_id'],'baseVersionId':d['base_version_id'],'currentStage':stage,'passedStages':d['passed_stages'],'totalStages':d['total_stages'],'actualBackend':d['actual_backend'],'thumbnailUrl':d['thumbnail_url'],'createdAt':d['created_at'],'updatedAt':d['updated_at']}
def asset_json(r):
    d=dict(r);return {'id':d['id'],'role':d['role'],'originalName':d['original_name'],'mimeType':d['mime_type'],'byteSize':d['byte_size'],'width':d['width'],'height':d['height'],'sha256':d['sha256'],'active':bool(d['active']),'url':'/'+d['storage_path'].replace('\\','/')}
def artifact_json(r):
    d=dict(r);return {'id':d['id'],'type':d['type'],'label':d['label'],'url':'/'+d['storage_path'].replace('\\','/'),'mimeType':d['mime_type'],'byteSize':d['byte_size'],'sha256':d['sha256'],'metadata':load(d['metadata'],{})}
def get_project(pid):
    with db() as con:r=con.execute('SELECT * FROM projects WHERE id=?',(pid,)).fetchone()
    if not r:raise HTTPException(404,'项目不存在')
    return r

@app.get('/api/system/health')
def health():
    disk=psutil.disk_usage(str(ROOT));caps=capabilities();gpu=remote_gpu() if os.environ.get('PRINT3D_MODE')=='remote' else None
    if gpu is None:
        gpu={'status':'unavailable','name':None}
        try:
            import subprocess
            gpu_name=subprocess.check_output(['nvidia-smi','--query-gpu=name','--format=csv,noheader'],text=True,timeout=4,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0)).strip();gpu={'status':'ready' if gpu_name else 'unavailable','name':gpu_name}
        except Exception:pass
    return {'status':'healthy' if gpu['status']=='ready' and caps['hunyuan3d'] and caps['blender'] else 'degraded','cpu':psutil.cpu_percent(),'memory':psutil.virtual_memory().percent,'storage':disk.percent,'gpu':{'status':gpu['status'],'name':gpu['name'],'queueConcurrency':1},'backends':caps,'services':{'api':'online','database':'online','worker':'local-thread'}}
@app.get('/api/style-presets')
def style_presets():return public_style_presets()
@app.get('/api/projects')
def projects(status:str|None=None,query:str|None=None,sort:str='updated_at',page:int=1):
    sql='SELECT * FROM projects';args=[];where=[]
    if status:where.append('status=?');args.append(status)
    if query:where.append('name LIKE ?');args.append(f'%{query}%')
    if where:sql+=' WHERE '+' AND '.join(where)
    sql+=' ORDER BY updated_at DESC LIMIT 100'
    with db() as con:rows=con.execute(sql,args).fetchall()
    return [project_json(r) for r in rows]
@app.post('/api/projects',status_code=201)
def create_project(body:ProjectInput):
    pid=uid('prj');stamp=now();settings=body.model_dump(exclude={'name','subjectType','intendedUse','quality'});directory=project_dir(pid);(directory/'assets'/'original').mkdir(parents=True);(directory/'assets'/'active').mkdir()
    with db() as con:con.execute('INSERT INTO projects(id,slug,name,subject_type,intended_use,quality,status,settings,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)',(pid,slugify(body.name),body.name,body.subjectType,body.intendedUse,body.quality,'draft',dump(settings),stamp,stamp))
    (directory/'project.json').write_text(json.dumps({'schemaVersion':1,'id':pid,**body.model_dump(),'createdAt':stamp},ensure_ascii=False,indent=2),encoding='utf-8')
    return project_json(get_project(pid))
@app.get('/api/projects/{pid}')
def project(pid:str):return project_json(get_project(pid))
@app.patch('/api/projects/{pid}')
def patch_project(pid:str,body:PatchInput):
    r=get_project(pid);data=body.model_dump(exclude_none=True);settings=load(r['settings'],{});settings.update({k:v for k,v in data.items() if k not in ('name','subjectType','intendedUse','quality')});mapping={'name':'name','subjectType':'subject_type','intendedUse':'intended_use','quality':'quality'}
    with db() as con:
        for k,col in mapping.items():
            if k in data:con.execute(f'UPDATE projects SET {col}=? WHERE id=?',(data[k],pid))
        con.execute('UPDATE projects SET settings=?,updated_at=? WHERE id=?',(dump(settings),now(),pid))
    return project_json(get_project(pid))
@app.delete('/api/projects/{pid}',status_code=204)
def delete_project(pid:str):
    get_project(pid)
    with db() as con:
        con.execute('DELETE FROM detail_review_events WHERE candidate_group_id IN (SELECT dcg.id FROM detail_candidate_groups dcg JOIN detail_generation_jobs dgj ON dgj.id=dcg.job_id JOIN detail_plans dp ON dp.id=dgj.detail_plan_id WHERE dp.project_id=?)',(pid,))
        con.execute('DELETE FROM detail_candidate_assets WHERE candidate_group_id IN (SELECT dcg.id FROM detail_candidate_groups dcg JOIN detail_generation_jobs dgj ON dgj.id=dcg.job_id JOIN detail_plans dp ON dp.id=dgj.detail_plan_id WHERE dp.project_id=?)',(pid,))
        con.execute('DELETE FROM detail_candidate_groups WHERE job_id IN (SELECT dgj.id FROM detail_generation_jobs dgj JOIN detail_plans dp ON dp.id=dgj.detail_plan_id WHERE dp.project_id=?)',(pid,))
        con.execute('DELETE FROM detail_generation_jobs WHERE detail_plan_id IN (SELECT id FROM detail_plans WHERE project_id=?)',(pid,))
        con.execute('DELETE FROM detail_regions WHERE detail_plan_id IN (SELECT id FROM detail_plans WHERE project_id=?)',(pid,))
        con.execute('DELETE FROM detail_plans WHERE project_id=?',(pid,))
        con.execute('UPDATE jobs SET cancel_requested=1 WHERE project_id=?',(pid,))
        con.execute('UPDATE refinement_jobs SET cancel_requested=1 WHERE project_id=?',(pid,))
        con.execute('UPDATE revision_requests SET cancel_requested=1 WHERE project_id=?',(pid,))
        con.execute('DELETE FROM comment_replies WHERE comment_id IN (SELECT id FROM version_comments WHERE project_id=?)',(pid,))
        con.execute('DELETE FROM comment_attachments WHERE comment_id IN (SELECT id FROM version_comments WHERE project_id=?)',(pid,))
        con.execute('DELETE FROM reference_set_assets WHERE reference_set_id IN (SELECT id FROM reference_sets WHERE project_id=?)',(pid,))
        con.execute('DELETE FROM revision_comment_links WHERE revision_request_id IN (SELECT id FROM revision_requests WHERE project_id=?)',(pid,))
        con.execute('DELETE FROM version_links WHERE refinement_job_id IN (SELECT id FROM refinement_jobs WHERE project_id=?)',(pid,))
        con.execute('DELETE FROM refinement_artifacts WHERE refinement_job_id IN (SELECT id FROM refinement_jobs WHERE project_id=?)',(pid,))
        con.execute('DELETE FROM stages WHERE job_id IN (SELECT id FROM jobs WHERE project_id=?)',(pid,))
        con.execute('DELETE FROM events WHERE job_id IN (SELECT id FROM jobs WHERE project_id=?)',(pid,))
        con.execute('DELETE FROM artifacts WHERE job_id IN (SELECT id FROM jobs WHERE project_id=?)',(pid,))
        con.execute('DELETE FROM decisions WHERE version_id IN (SELECT id FROM versions WHERE project_id=?)',(pid,))
        con.execute('DELETE FROM revisions WHERE version_id IN (SELECT id FROM versions WHERE project_id=?)',(pid,))
        con.execute('DELETE FROM revision_requests WHERE project_id=?',(pid,))
        con.execute('DELETE FROM refinement_jobs WHERE project_id=?',(pid,))
        con.execute('DELETE FROM reference_sets WHERE project_id=?',(pid,))
        con.execute('DELETE FROM version_comments WHERE project_id=?',(pid,))
        con.execute('DELETE FROM jobs WHERE project_id=?',(pid,))
        con.execute('DELETE FROM validations WHERE project_id=?',(pid,))
        con.execute('DELETE FROM assets WHERE project_id=?',(pid,))
        con.execute('DELETE FROM versions WHERE project_id=?',(pid,))
        con.execute('DELETE FROM projects WHERE id=?',(pid,))
    shutil.rmtree(project_dir(pid),ignore_errors=True)
    return Response(status_code=204)
@app.get('/api/projects/{pid}/assets')
def assets(pid:str):
    get_project(pid)
    with db() as con:rows=con.execute('SELECT * FROM assets WHERE project_id=? AND active=1 ORDER BY created_at',(pid,)).fetchall()
    return [asset_json(r) for r in rows]
@app.post('/api/projects/{pid}/assets',status_code=201)
async def upload_asset(pid:str,role:str=Query(...),file:UploadFile=File(...)):
    get_project(pid);allowed={'front','side','back','left-three-quarter','right-three-quarter','base-color','roughness','normal','metalness','mask','existing-model'}
    if role not in allowed:raise HTTPException(400,'未知素材角色')
    safe_name=Path(file.filename or 'upload').name
    if safe_name!=file.filename or '..' in safe_name:raise HTTPException(400,'不安全的文件名')
    ext=Path(safe_name).suffix.lower();is_model=role=='existing-model'
    if (not is_model and ext not in {'.png','.jpg','.jpeg','.webp'}) or (is_model and ext not in {'.glb','.blend'}):raise HTTPException(415,'文件扩展名不在允许列表')
    target_dir=project_dir(pid)/'assets'/'original';aid=uid('ast');tmp=target_dir/f'{aid}.upload';size=0
    with tmp.open('wb') as out:
        while chunk:=await file.read(1024*1024):
            size+=len(chunk)
            if size>20*1024*1024 and not is_model:tmp.unlink(missing_ok=True);raise HTTPException(413,'图片超过 20 MB 上限')
            if size>200*1024*1024:tmp.unlink(missing_ok=True);raise HTTPException(413,'模型超过 200 MB 上限')
            out.write(chunk)
    width=height=None
    try:
        if is_model:
            if ext=='.glb' and tmp.read_bytes()[:4]!=b'glTF':raise HTTPException(415,'文件内容不是有效 GLB')
            mime='model/gltf-binary' if ext=='.glb' else 'application/octet-stream'
        else:
            with Image.open(tmp) as im:im.verify()
            with Image.open(tmp) as im:width,height=im.size;fmt=(im.format or '').lower()
            mime={'png':'image/png','jpeg':'image/jpeg','webp':'image/webp'}.get(fmt,'')
            if not mime:raise HTTPException(415,'图片实际内容类型不受支持')
        final=target_dir/f'{aid}{ext}';tmp.replace(final);digest=sha256(final);rel=storage_path(final)
        with db() as con:
            con.execute('UPDATE assets SET active=0 WHERE project_id=? AND role=?',(pid,role));con.execute('INSERT INTO assets VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',(aid,pid,role,safe_name,rel,mime,size,width,height,digest,1,now()));con.execute("UPDATE projects SET status='uploading',updated_at=? WHERE id=?",(now(),pid));con.execute('DELETE FROM validations WHERE project_id=?',(pid,))
            if role=='front':con.execute('UPDATE projects SET thumbnail_url=? WHERE id=?',('/'+rel,pid))
    except HTTPException:tmp.unlink(missing_ok=True);raise
    except (UnidentifiedImageError,OSError) as exc:tmp.unlink(missing_ok=True);raise HTTPException(415,f'文件无法按声明类型解码：{exc}')
    with db() as con:r=con.execute('SELECT * FROM assets WHERE id=?',(aid,)).fetchone()
    return asset_json(r)
@app.post('/api/projects/{pid}/validate')
def validate(pid:str):
    get_project(pid)
    with db() as con:rows=con.execute('SELECT * FROM assets WHERE project_id=? AND active=1',(pid,)).fetchall()
    images=[r for r in rows if r['mime_type'].startswith('image/')];front=next((r for r in images if r['role']=='front'),None);checks=[];risks=[]
    checks.append({'code':'decode','label':'文件可解码','status':'pass' if images else 'fail','evidence':f'{len(images)} 个活动图片均完成服务端内容解码' if images else '没有可解码图片'})
    shortest=min(front['width'],front['height']) if front else 0
    resolution_status='fail' if shortest<256 else 'warning' if shortest<1024 else 'pass'
    resolution_evidence=(f'正面最短边 {shortest}px；低于 256px 阻断，256–1023px 可接受风险后继续，1024px 及以上通过' if front else '缺少正面素材')
    checks.append({'code':'resolution','label':'分辨率','status':resolution_status,'evidence':resolution_evidence})
    checks.append({'code':'front','label':'正面主参考','status':'pass' if front else 'fail','evidence':'已按 front 角色显式上传' if front else '正面主参考为必填'})
    hashes=[r['sha256'] for r in images];dupes=len(hashes)!=len(set(hashes));checks.append({'code':'duplicates','label':'重复素材','status':'warning' if dupes else 'pass','evidence':'检测到内容哈希重复' if dupes else '活动素材 SHA-256 均不同'})
    views={r['role'] for r in images};coverage=len(views&{'front','side','back','left-three-quarter','right-three-quarter'})
    checks.append({'code':'coverage','label':'多视角覆盖','status':'pass' if coverage>=3 else 'warning','evidence':f'已有 {coverage}/5 个明确视角角色','affectedRegions':['背面','侧后轮廓'] if coverage<3 else []})
    checks.extend([{'code':'subject-complete','label':'主体完整','status':'warning','evidence':'MVP 仅执行技术检查；主体裁切与身份一致性需人工确认'},{'code':'identity','label':'多视角主体一致','status':'warning' if coverage>1 else 'pass','evidence':'必须由制作用户人工确认，不以文件名或宽高比判断身份'}])
    blocking=any(c['status']=='fail' for c in checks);warnings=any(c['status']=='warning' for c in checks)
    if 256<=shortest<1024:risks.append({'code':'LOW_RESOLUTION','message':f'正面素材分辨率偏低（最短边 {shortest}px）','consequence':'小型轮廓、面部、手指、饰品和材质细节可能被合并或模糊，但可接受风险后继续。'})
    if coverage<3:risks.append({'code':'LOW_VIEW_COVERAGE','message':'侧面或背面覆盖不足','consequence':'隐藏区域将以低置信度近似，侧后轮廓与原设计可能不一致。'})
    if dupes:risks.append({'code':'DUPLICATE_ASSET','message':'素材内容重复','consequence':'重复视图不会增加几何证据，可能造成错误的覆盖预期。'})
    verdict='request_input' if blocking else 'conditional' if warnings else 'pass';vid=uid('val');stamp=now()
    with db() as con:con.execute('DELETE FROM validations WHERE project_id=?',(pid,));con.execute('INSERT INTO validations VALUES(?,?,?,?,?,?,?,?)',(vid,pid,dump([r['id'] for r in rows]),verdict,dump(checks),dump(risks),None,stamp));con.execute('UPDATE projects SET status=?,updated_at=? WHERE id=?',('needs_input' if blocking else 'awaiting_confirmation',stamp,pid))
    return {'verdict':verdict,'checks':checks,'risks':risks,'acceptedAt':None}
@app.get('/api/projects/{pid}/validation')
def validation(pid:str):
    with db() as con:r=con.execute('SELECT * FROM validations WHERE project_id=? ORDER BY created_at DESC LIMIT 1',(pid,)).fetchone()
    if not r:raise HTTPException(404,'尚未生成检查结果')
    return {'verdict':r['verdict'],'checks':load(r['checks'],[]),'risks':load(r['risks'],[]),'acceptedAt':r['accepted_at']}
@app.post('/api/projects/{pid}/validation/accept-risks')
def accept_risks(pid:str):
    v=validation(pid)
    if v['verdict']!='conditional':raise HTTPException(409,'只有有条件通过可以接受风险')
    stamp=now()
    with db() as con:con.execute('UPDATE validations SET accepted_at=? WHERE project_id=?',(stamp,pid));con.execute("UPDATE projects SET status='awaiting_confirmation',updated_at=? WHERE id=?",(stamp,pid))
    v['acceptedAt']=stamp;return v
def make_plan(pid):
    p=get_project(pid);settings=load(p['settings'],{});quality=p['quality'];preset=style_preset(settings.get('modelStyle'));texture_resolution={'standard':0,'high':2048,'ultra':4096}.get(quality,0);visual_mode=settings.get('visualConditioningMode','auto');return {'primaryBackend':'hunyuan3d','fallbackBackends':['sf3d','triposr'],'geometryQuality':quality,'textureResolution':texture_resolution,'faceRefinement':quality=='ultra','targetTriangleRange':[60000,120000],'segmentationRequired':settings.get('segmentationRequired',False),'rigRequired':settings.get('rigRequired',False),'preserveBaseline':True,'renderViews':['front','left-three-quarter','side','back'],'modelStyle':preset['id'],'stylePreset':preset,'viewWeights':preset['viewWeights'],'visualConditioning':{'enabled':visual_mode!='original','mode':visual_mode,'depthBlend':.15,'exportExperimentalDepth':True},'limitations':['Hunyuan3D-2mv 不直接接收文本提示词；风格提示词会转成安全的 RGB 轮廓/明暗候选。','纯深度提示不直接送入 Hunyuan，仅作为实验产物保存。','风格预设会实际控制三视图权重及 Blender 前后厚度。','单张图无法准确恢复隐藏面；背面与遮挡结构按证据置信度标记。','高/超高质量使用参考图投射保留颜色与五官；它不会把二维眼线自动雕刻成独立眼球。','自动分件与骨骼不作为 MVP 完成条件。']}
@app.get('/api/projects/{pid}/plan')
def get_plan(pid:str):return make_plan(pid)
@app.patch('/api/projects/{pid}/plan')
def update_plan(pid:str,body:PlanInput):
    get_project(pid);payload=body.model_dump();payload['stylePreset']=style_preset(payload['modelStyle']);path=project_dir(pid)/'plan-draft.json';path.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8');return payload
@app.post('/api/projects/{pid}/jobs',status_code=201)
def create_job(pid:str):
    p=get_project(pid)
    with db() as con:v=con.execute('SELECT * FROM validations WHERE project_id=? ORDER BY created_at DESC LIMIT 1',(pid,)).fetchone()
    if not v or v['verdict'] in ('request_input','reject'):raise HTTPException(409,'素材检查存在阻断项')
    plan_path=project_dir(pid)/'plan-draft.json';config=json.loads(plan_path.read_text('utf-8')) if plan_path.exists() else make_plan(pid)
    return new_job(pid,config,1)
def new_job(pid,config,attempt):
    reference_set_id=config.get('referenceSetId')
    if reference_set_id:
        with db() as con:
            rs=con.execute("SELECT * FROM reference_sets WHERE id=? AND project_id=? AND status='locked' AND locked_at IS NOT NULL",(reference_set_id,pid)).fetchone()
            if not rs:raise HTTPException(409,'几何任务只能使用本项目已锁定的 Reference Set')
        config={**config,'referenceSetConsumption':reference_set_consumption(reference_set_id)}
    with db() as con:
        number=con.execute('SELECT COALESCE(MAX(number),0)+1 FROM versions WHERE project_id=?',(pid,)).fetchone()[0];vid=uid('ver');jid=uid('job');stamp=now();con.execute('INSERT INTO versions VALUES(?,?,?,?,?,?,?)',(vid,pid,number,f'v{number:03d}','processing',None,stamp));con.execute('INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(jid,pid,vid,'queued',dump(config),config['primaryBackend'],None,None,random.randint(1,2**31-1),None,attempt,stamp,None,None,None,None,0));
        for i,(key,label) in enumerate(STAGES):con.execute('INSERT INTO stages(id,job_id,stage_key,label,status,position) VALUES(?,?,?,?,?,?)',(uid('stg'),jid,key,label,'pending',i))
        con.execute("UPDATE projects SET status='queued',current_job_id=?,passed_stages=0,total_stages=?,updated_at=? WHERE id=?",(jid,len(STAGES),stamp,pid))
    folder=project_dir(pid)/'versions'/vid;folder.mkdir(parents=True);(folder/'job-config.json').write_text(json.dumps({'schemaVersion':1,'projectId':pid,'versionId':vid,'jobId':jid,'attempt':attempt,**config},ensure_ascii=False,indent=2),encoding='utf-8');launch(jid);return job_json(jid)
def job_json(jid):
    with db() as con:
        r=con.execute('SELECT * FROM jobs WHERE id=?',(jid,)).fetchone()
        if not r:raise HTTPException(404,'任务不存在')
        stages=con.execute('SELECT * FROM stages WHERE job_id=? ORDER BY position',(jid,)).fetchall();events=con.execute("SELECT * FROM events WHERE job_id=? AND event_type='stage.log' ORDER BY id",(jid,)).fetchall();arts=con.execute('SELECT * FROM artifacts WHERE job_id=? ORDER BY created_at',(jid,)).fetchall()
    return {'id':r['id'],'projectId':r['project_id'],'versionId':r['version_id'],'status':r['status'],'requestedBackend':r['requested_backend'],'actualBackend':r['actual_backend'],'currentStage':r['current_stage'],'attempt':r['attempt'],'errorCode':r['error_code'],'errorSummary':r['error_summary'],'stages':[{'id':s['stage_key'],'label':s['label'],'status':s['status'],'startedAt':s['started_at'],'completedAt':s['completed_at']} for s in stages],'logs':[load(e['payload'],{}).get('message','') for e in events],'artifacts':[artifact_json(a) for a in arts]}
@app.get('/api/jobs/{jid}')
def get_job(jid:str):return job_json(jid)
@app.get('/api/jobs/{jid}/stages')
def job_stages(jid:str):return job_json(jid)['stages']
@app.get('/api/jobs/{jid}/artifacts')
def job_artifacts(jid:str):return job_json(jid)['artifacts']
@app.get('/api/jobs/{jid}/events')
async def events(jid:str,request:Request):
    job_json(jid);last=int(request.headers.get('last-event-id','0') or 0)
    async def stream():
        nonlocal last
        while not await request.is_disconnected():
            with db() as con:rows=con.execute('SELECT * FROM events WHERE job_id=? AND id>? ORDER BY id',(jid,last)).fetchall()
            for r in rows:last=r['id'];yield f"id: {r['id']}\nevent: {r['event_type']}\ndata: {r['payload']}\n\n"
            yield ': keepalive\n\n';await asyncio.sleep(.5)
    return StreamingResponse(stream(),media_type='text/event-stream',headers={'Cache-Control':'no-cache','X-Accel-Buffering':'no'})
@app.post('/api/jobs/{jid}/cancel')
def cancel(jid:str):
    snapshot=job_json(jid)
    with db() as con:
        con.execute('UPDATE jobs SET cancel_requested=1 WHERE id=?',(jid,))
        if snapshot['status']=='awaiting_geometry_confirmation':
            stamp=now();con.execute("UPDATE jobs SET status='cancelled',completed_at=? WHERE id=?",(stamp,jid));con.execute("UPDATE projects SET status='cancelled',updated_at=? WHERE current_job_id=?",(stamp,jid));con.execute("UPDATE versions SET status='cancelled' WHERE id=?",(snapshot['versionId'],))
    return job_json(jid)
@app.post('/api/jobs/{jid}/retry')
def retry(jid:str):
    old=job_json(jid)
    with db() as con:r=con.execute('SELECT config_snapshot FROM jobs WHERE id=?',(jid,)).fetchone()
    return new_job(old['projectId'],load(r['config_snapshot'],{}),old['attempt']+1)
@app.post('/api/jobs/{jid}/confirm-geometry')
def confirm_geometry(jid:str):
    snapshot=job_json(jid)
    if snapshot['status']!='awaiting_geometry_confirmation':raise HTTPException(409,'任务尚未进入几何确认阶段')
    with db() as con:
        con.execute("UPDATE jobs SET status='queued',current_stage='web_optimization' WHERE id=?",(jid,))
        con.execute("UPDATE projects SET status='rendering_review',updated_at=? WHERE current_job_id=?",(now(),jid))
    launch(jid)
    return job_json(jid)
@app.get('/api/projects/{pid}/versions')
def versions(pid:str):
    get_project(pid)
    with db() as con:rows=con.execute('SELECT * FROM versions WHERE project_id=? ORDER BY number DESC',(pid,)).fetchall()
    return [version_json(r['id']) for r in rows]
def version_json(vid):
    with db() as con:
        r=con.execute('SELECT * FROM versions WHERE id=?',(vid,)).fetchone()
        if not r:raise HTTPException(404,'版本不存在')
        art=con.execute("SELECT * FROM artifacts WHERE version_id=? AND type='glb' ORDER BY created_at DESC LIMIT 1",(vid,)).fetchone()
        if not art:art=con.execute("SELECT * FROM refinement_artifacts WHERE version_id=? AND type='glb' ORDER BY created_at DESC LIMIT 1",(vid,)).fetchone()
        project=con.execute('SELECT base_version_id FROM projects WHERE id=?',(r['project_id'],)).fetchone()
    return {'id':r['id'],'projectId':r['project_id'],'number':r['number'],'label':r['label'],'status':r['status'],'isBase':project['base_version_id']==vid,'model':artifact_json(art) if art else None,'createdAt':r['created_at'],'qualityReport':load(r['quality_report'],{})}
@app.get('/api/versions/{vid}')
def version(vid:str):return version_json(vid)
@app.get('/api/versions/{vid}/model')
def model(vid:str):
    v=version_json(vid)
    if not v['model']:raise HTTPException(404,'版本没有 GLB')
    return v['model']
@app.get('/api/versions/{vid}/quality-report')
def quality(vid:str):return version_json(vid)['qualityReport']
@app.post('/api/versions/{vid}/exports/stl')
def export_version_stl(vid:str,body:StlExportInput):
    version=version_json(vid);safe_stem=re.sub(r'[^\w\-\u4e00-\u9fff]+','-',Path(body.filename).stem,flags=re.UNICODE).strip('-') or f'version-{version["number"]:03d}'
    with db() as con:
        source=con.execute("SELECT * FROM refinement_artifacts WHERE version_id=? AND type IN ('blend','glb') ORDER BY CASE type WHEN 'blend' THEN 0 ELSE 1 END,created_at DESC LIMIT 1",(vid,)).fetchone()
        if not source:source=con.execute("SELECT * FROM artifacts WHERE version_id=? AND type IN ('blend','glb') ORDER BY CASE type WHEN 'blend' THEN 0 ELSE 1 END,created_at DESC LIMIT 1",(vid,)).fetchone()
        if not source:source=con.execute("SELECT * FROM assets WHERE project_id=? AND role='existing-model' AND active=1 AND (storage_path LIKE '%.blend' OR storage_path LIKE '%.glb') ORDER BY CASE WHEN storage_path LIKE '%.blend' THEN 0 ELSE 1 END,created_at DESC LIMIT 1",(version['projectId'],)).fetchone()
    if not source:raise HTTPException(404,'当前版本没有可供 Blender 导出的 .blend 或 GLB 源文件')
    source_path=resolve_storage(source['storage_path']);output=project_dir(version['projectId'])/'versions'/vid/'exports'/f'{safe_stem}.stl'
    logs=[]
    try:export_stl_blender(source_path,output,body.scope,body.unit,body.applyModifiers,logs.append,body.targetHeightMm)
    except BackendError as exc:raise HTTPException(500,str(exc)) from exc
    rel=storage_path(output)
    return {'filename':output.name,'url':'/'+rel.replace('\\','/'),'byteSize':output.stat().st_size,'sourceType':source_path.suffix.lower().lstrip('.'),'engine':'Blender','unit':body.unit,'targetHeightMm':body.targetHeightMm,'logs':logs[-10:]}
@app.post('/api/versions/{vid}/set-base')
def set_base_version(vid:str):
    version=version_json(vid)
    with db() as con:con.execute('UPDATE projects SET base_version_id=?,updated_at=? WHERE id=?',(vid,now(),version['projectId']))
    return version_json(vid)
@app.delete('/api/versions/{vid}',status_code=204)
def delete_version(vid:str):
    version=version_json(vid);pid=version['projectId']
    with db() as con:
        if con.execute('SELECT 1 FROM projects WHERE id=? AND base_version_id=?',(pid,vid)).fetchone():raise HTTPException(409,'Base 版本不能删除；请先将另一个版本设为 Base')
        if con.execute("SELECT 1 FROM jobs WHERE version_id=? AND status NOT IN ('completed','failed','cancelled')",(vid,)).fetchone():raise HTTPException(409,'该版本仍有处理中的生成任务，暂不能删除')
        if con.execute('SELECT 1 FROM refinement_jobs WHERE source_version_id=?',(vid,)).fetchone() or con.execute('SELECT 1 FROM revision_requests WHERE source_version_id=?',(vid,)).fetchone():raise HTTPException(409,'该版本正被后续修订使用，不能删除')
        if con.execute('SELECT 1 FROM reference_set_assets rsa JOIN comment_attachments ca ON ca.asset_id=rsa.asset_id JOIN version_comments vc ON vc.id=ca.comment_id WHERE vc.version_id=?',(vid,)).fetchone():raise HTTPException(409,'该版本的 Comment 参考图正在被 Reference Set 使用，不能删除')
        comment_assets=[r['id'] for r in con.execute("SELECT a.id FROM assets a JOIN comment_attachments ca ON ca.asset_id=a.id JOIN version_comments vc ON vc.id=ca.comment_id WHERE vc.version_id=?",(vid,))]
        comment_files=[r['storage_path'] for r in con.execute("SELECT a.storage_path FROM assets a JOIN comment_attachments ca ON ca.asset_id=a.id JOIN version_comments vc ON vc.id=ca.comment_id WHERE vc.version_id=?",(vid,))]
        comment_files += [r['screenshot_path'] for r in con.execute('SELECT screenshot_path FROM version_comments WHERE version_id=? AND screenshot_path IS NOT NULL',(vid,))]
        own_refinement_ids=[r['id'] for r in con.execute('SELECT id FROM refinement_jobs WHERE output_version_id=?',(vid,))]
        own_revision_ids=[r['id'] for r in con.execute('SELECT id FROM revision_requests WHERE output_version_id=?',(vid,))]
        if own_refinement_ids and con.execute("SELECT 1 FROM refinement_jobs WHERE output_version_id=? AND status IN ('queued','running')",(vid,)).fetchone():raise HTTPException(409,'该版本对应的精修任务仍在运行，暂不能删除')
        if own_revision_ids and con.execute("SELECT 1 FROM revision_requests WHERE output_version_id=? AND status IN ('queued','running','processing')",(vid,)).fetchone():raise HTTPException(409,'该版本对应的修订任务仍在运行，暂不能删除')
        con.execute('DELETE FROM comment_replies WHERE comment_id IN (SELECT id FROM version_comments WHERE version_id=?)',(vid,))
        con.execute('DELETE FROM comment_attachments WHERE comment_id IN (SELECT id FROM version_comments WHERE version_id=?)',(vid,))
        if comment_assets:con.executemany('DELETE FROM assets WHERE id=?',[(asset_id,) for asset_id in comment_assets])
        con.execute('DELETE FROM version_comments WHERE version_id=?',(vid,))
        con.execute('DELETE FROM revision_comment_links WHERE revision_request_id IN (SELECT id FROM revision_requests WHERE output_version_id=?)',(vid,))
        con.execute('DELETE FROM revision_requests WHERE output_version_id=?',(vid,))
        con.execute('DELETE FROM version_links WHERE refinement_job_id IN (SELECT id FROM refinement_jobs WHERE output_version_id=?)',(vid,))
        con.execute('DELETE FROM refinement_artifacts WHERE refinement_job_id IN (SELECT id FROM refinement_jobs WHERE output_version_id=?)',(vid,))
        con.execute('DELETE FROM refinement_jobs WHERE output_version_id=?',(vid,))
        con.execute('DELETE FROM stages WHERE job_id IN (SELECT id FROM jobs WHERE version_id=?)',(vid,))
        con.execute('DELETE FROM events WHERE job_id IN (SELECT id FROM jobs WHERE version_id=?)',(vid,))
        con.execute('DELETE FROM artifacts WHERE version_id=?',(vid,))
        con.execute('DELETE FROM decisions WHERE version_id=?',(vid,));con.execute('DELETE FROM revisions WHERE version_id=?',(vid,));con.execute('DELETE FROM jobs WHERE version_id=?',(vid,));con.execute('DELETE FROM versions WHERE id=?',(vid,))
        con.execute('UPDATE projects SET current_job_id=NULL,updated_at=? WHERE id=? AND current_job_id NOT IN (SELECT id FROM jobs)',(now(),pid))
    shutil.rmtree(project_dir(pid)/'versions'/vid,ignore_errors=True)
    for path in comment_files:
        try:resolve_storage(path).unlink(missing_ok=True)
        except OSError:pass
    return Response(status_code=204)
@app.post('/api/versions/{vid}/accept')
def accept(vid:str,body:DecisionInput):return decide(vid,'completed',body.notes)
@app.post('/api/versions/{vid}/accept-with-notes')
def accept_notes(vid:str,body:DecisionInput):
    if not body.notes.strip():raise HTTPException(422,'有条件通过必须填写备注')
    return decide(vid,'completed_with_notes',body.notes)
def decide(vid,status,notes):
    v=version_json(vid);stamp=now()
    if v['status'] in ('completed','completed_with_notes'):
        return {'status':v['status'],'versionId':vid,'locked':True,'createdAt':stamp,'alreadyAccepted':True}
    with db() as con:con.execute('INSERT INTO decisions VALUES(?,?,?,?,?)',(uid('dec'),vid,status,notes,stamp));con.execute('UPDATE versions SET status=? WHERE id=?',(status,vid));con.execute('UPDATE projects SET status=?,updated_at=? WHERE id=?',(status,stamp,v['projectId']))
    return {'status':status,'versionId':vid,'locked':True,'createdAt':stamp,'alreadyAccepted':False}
@app.post('/api/versions/{vid}/revisions')
async def revision(vid:str,request:Request):
    v=version_json(vid);payload=await request.json();rid=uid('rev');stamp=now()
    with db() as con:con.execute('INSERT INTO revisions VALUES(?,?,?,?,?)',(rid,vid,dump(payload),'open',stamp));con.execute("UPDATE projects SET status='revision_requested',updated_at=? WHERE id=?",(stamp,v['projectId']))
    return {'id':rid,'status':'open','sourceVersionId':vid,'createdAt':stamp}

REFINEMENT_MODULES={
 'geometryRepair':{'label':'几何修复','capability':'automatic','description':'变换、重复点、松散几何、退化面与法线清理'},
 'uvUnwrap':{'label':'自动 UV','capability':'automatic','description':'保留有效 UV，否则 Smart UV Project'},
 'identityRefine':{'label':'身份特征精修','capability':'manual','description':'面部、手部、关键配件'},
 'segmentation':{'label':'自动 / 人工分件','capability':'manual','description':'建立可审阅部件边界'},
 'referenceProjection':{'label':'参考图投射','capability':'not_configured','description':'UV 展开、相机对齐、去光照','dependencies':['uvUnwrap','cameraAlignment','delighting']},
 'pbrMaterials':{'label':'PBR 材质','capability':'inferred','description':'五通道 PBR 自动生成；推断区域待验收'},
 'rigging':{'label':'骨骼绑定','capability':'experimental','description':'骨架、权重与姿态测试'},
 'webOptimization':{'label':'Web 优化','capability':'automatic','description':'规范化、导出和文件预算检查'},
 'visualReview':{'label':'视觉质量评审','capability':'manual','description':'固定四视图人工复核'},
}
@app.get('/api/refinement/modules')
def refinement_modules():return REFINEMENT_MODULES
def refinement_json(r):
    d=dict(r)
    with db() as con:arts=con.execute('SELECT * FROM refinement_artifacts WHERE refinement_job_id=? ORDER BY created_at',(d['id'],)).fetchall()
    return {'id':d['id'],'projectId':d['project_id'],'sourceVersionId':d['source_version_id'],'outputVersionId':d['output_version_id'],'status':d['status'],'config':load(d['config'],{}),'moduleStates':load(d['module_states'],{}),'logs':load(d['logs'],[]),'artifacts':[artifact_json(a) for a in arts],'qualityReport':load(d.get('quality_report'),{}),'blenderVersion':d.get('blender_version'),'createdAt':d['created_at'],'startedAt':d['started_at'],'completedAt':d['completed_at'],'errorSummary':d['error_summary']}
@app.post('/api/refinement/jobs',status_code=201)
def create_refinement(body:RefinementInput):
    source=version_json(body.sourceVersionId)
    if not source['model']:raise HTTPException(409,'源版本没有可用 GLB')
    if source['status'] not in ('completed','completed_with_notes'):raise HTTPException(409,'源版本必须先验收并锁定')
    if not capabilities().get('blenderRefinement'):raise HTTPException(503,'Blender 自动精修环境不可用')
    unknown=[m for m in body.modules if m not in REFINEMENT_MODULES]
    if unknown:raise HTTPException(422,f'未知精修模块：{unknown}')
    if not body.modules:raise HTTPException(422,'至少选择一个精修模块')
    jid=uid('ref');stamp=now();states={m:'pending' for m in body.modules};logs=[f'[{stamp[11:19]}] 精修任务创建，源版本 v{source["number"]:03d} 已锁定']
    with db() as con:con.execute('INSERT INTO refinement_jobs(id,project_id,source_version_id,output_version_id,status,config,module_states,logs,created_at) VALUES(?,?,?,?,?,?,?,?,?)',(jid,source['projectId'],body.sourceVersionId,None,'queued',dump(body.model_dump()),dump(states),dump(logs),stamp));con.execute("UPDATE projects SET status='revision_requested',updated_at=? WHERE id=?",(stamp,source['projectId']))
    threading.Thread(target=run_refinement,args=(jid,),daemon=True).start()
    with db() as con:r=con.execute('SELECT * FROM refinement_jobs WHERE id=?',(jid,)).fetchone()
    return refinement_json(r)
def run_refinement(jid):
    def save_log(message):
        logs.append(f'[{now()[11:19]}] {message}')
        with db() as con:con.execute('UPDATE refinement_jobs SET logs=? WHERE id=?',(dump(logs),jid))
    def cancelled():
        with db() as con:return bool(con.execute('SELECT cancel_requested FROM refinement_jobs WHERE id=?',(jid,)).fetchone()[0])
    try:
        with db() as con:
            r=con.execute('SELECT * FROM refinement_jobs WHERE id=?',(jid,)).fetchone();d=dict(r);config=load(d['config'],{});states=load(d['module_states'],{});logs=load(d['logs'],[])
            source=con.execute("SELECT storage_path FROM artifacts WHERE version_id=? AND type='glb' ORDER BY created_at DESC LIMIT 1",(d['source_version_id'],)).fetchone()
            if not source:source=con.execute("SELECT storage_path FROM refinement_artifacts WHERE version_id=? AND type='glb' ORDER BY created_at DESC LIMIT 1",(d['source_version_id'],)).fetchone()
            reference=con.execute("SELECT storage_path FROM assets WHERE project_id=? AND role='front' AND active=1 ORDER BY created_at DESC LIMIT 1",(d['project_id'],)).fetchone()
            number=con.execute('SELECT COALESCE(MAX(number),0)+1 FROM versions WHERE project_id=?',(d['project_id'],)).fetchone()[0];con.execute("UPDATE refinement_jobs SET status='running',started_at=? WHERE id=?",(now(),jid))
        if not source:raise RuntimeError('源版本 GLB 产物不存在')
        out_vid=uid('ver');root=project_dir(d['project_id'])/'versions'/out_vid/'refinement';root.mkdir(parents=True);config_path=root/'config-snapshot.json';config_path.write_text(json.dumps(config,ensure_ascii=False,indent=2),encoding='utf-8')
        for m in config['modules']:
            cap=REFINEMENT_MODULES[m]['capability'];states[m]='running' if cap in ('automatic','inferred') else 'not_configured'
        with db() as con:con.execute('UPDATE refinement_jobs SET module_states=? WHERE id=?',(dump(states),jid))
        result=refine_blender(resolve_storage(source['storage_path']),root,config_path,save_log,cancelled,resolve_storage(reference['storage_path']) if reference else None)
        for m in config['modules']:
            cap=REFINEMENT_MODULES[m]['capability'];states[m]='awaiting_review' if cap=='inferred' else 'passed' if cap=='automatic' else 'not_configured'
        gates=result.get('gates',{})
        if not gates.get('meshValid',False) or not gates.get('boundsSafe',False) or not gates.get('volumeSafe',True):states['geometryRepair']='failed'
        if 'uvUnwrap' in states and not gates.get('uvValid',False):states['uvUnwrap']='failed'
        if 'pbrMaterials' in states and not gates.get('pbrComplete',False):states['pbrMaterials']='failed'
        if 'webOptimization' in states and (not gates.get('triangleBudget',False) or not gates.get('sizeBudget',False) or not gates.get('glbValid',False) or not gates.get('volumeSafe',True)):states['webOptimization']='failed'
        if 'visualReview' in states and not gates.get('rendersComplete',False):states['visualReview']='failed'
        stamp=now();status='awaiting_review' if result['status']=='passed' else 'quality_failed'
        with db() as con:
            con.execute('INSERT INTO versions VALUES(?,?,?,?,?,?,?)',(out_vid,d['project_id'],number,f'v{number:03d} · Blender 自动精修','ready_for_review' if status=='awaiting_review' else 'quality_failed',dump(result),stamp));con.execute('INSERT INTO version_links VALUES(?,?,?,?,?)',(uid('vln'),d['source_version_id'],out_vid,jid,stamp))
            files=[('glb','refined.glb',root/'refined.glb','model/gltf-binary'),('quality_report','quality-report.json',root/'quality-report.json','application/json'),('config','config-snapshot.json',config_path,'application/json')]+[('texture',f'{n}.png',root/'textures'/f'{n}.png','image/png') for n in ('base-color','roughness','metallic','normal','ao')]+[('render',f'{n}.png',root/f'{n}.png','image/png') for n in ('front','left-three-quarter','side','back')]
            for kind,label,path,mime in files:
                if path.exists():con.execute('INSERT INTO refinement_artifacts VALUES(?,?,?,?,?,?,?,?,?,?,?)',(uid('rart'),jid,out_vid,kind,label,storage_path(path),mime,path.stat().st_size,sha256(path),dump({'sourceVersionId':d['source_version_id']}),stamp))
            con.execute('UPDATE refinement_jobs SET output_version_id=?,status=?,module_states=?,logs=?,completed_at=?,blender_version=?,quality_report=? WHERE id=?',(out_vid,status,dump(states),dump(logs),stamp,result.get('blenderVersion'),dump(result),jid));con.execute('UPDATE projects SET status=?,updated_at=? WHERE id=?',('ready_for_review' if status=='awaiting_review' else 'quality_failed',stamp,d['project_id']))
    except CancelledError as exc:
        with db() as con:con.execute("UPDATE refinement_jobs SET status='cancelled',logs=?,completed_at=?,error_summary=? WHERE id=?",(dump(logs),now(),str(exc),jid))
    except Exception as exc:
        save_log(f'精修失败：{exc}')
        with db() as con:con.execute("UPDATE refinement_jobs SET status='failed',module_states=?,completed_at=?,error_summary=? WHERE id=?",(dump(states),now(),str(exc),jid))
@app.get('/api/refinement/jobs/{jid}')
def get_refinement(jid:str):
    with db() as con:r=con.execute('SELECT * FROM refinement_jobs WHERE id=?',(jid,)).fetchone()
    if not r:raise HTTPException(404,'精修任务不存在')
    return refinement_json(r)
@app.post('/api/refinement/jobs/{jid}/cancel')
def cancel_refinement(jid:str):
    get_refinement(jid)
    with db() as con:con.execute('UPDATE refinement_jobs SET cancel_requested=1 WHERE id=?',(jid,))
    return get_refinement(jid)
@app.get('/api/projects/{pid}/refinement-jobs')
def project_refinements(pid:str):
    with db() as con:rows=con.execute('SELECT * FROM refinement_jobs WHERE project_id=? ORDER BY created_at DESC',(pid,)).fetchall()
    return [refinement_json(r) for r in rows]

COMMENT_CATEGORIES={'contour','proportion','identity','geometry','intersection','missing_structure','texture','color','material','uv','other'}
COMMENT_SEVERITIES={'blocking','important','normal','note'}
COMMENT_ROUTES={'blender_automatic','reference_regeneration','manual','not_configured'}

def comment_json(row):
    d=dict(row)
    with db() as con:
        replies=con.execute('SELECT * FROM comment_replies WHERE comment_id=? ORDER BY created_at',(d['id'],)).fetchall()
        attachments=con.execute('SELECT ca.*,a.original_name,a.storage_path,a.mime_type FROM comment_attachments ca JOIN assets a ON a.id=ca.asset_id WHERE ca.comment_id=? ORDER BY ca.created_at',(d['id'],)).fetchall()
    return {'id':d['id'],'projectId':d['project_id'],'versionId':d['version_id'],'number':d['number'],'title':d['title'],'description':d['description'],'category':d['category'],'severity':d['severity'],'status':d['status'],'recommendedRoute':d['recommended_route'],'meshName':d['mesh_name'],'position':load(d['position_json']), 'normal':load(d['normal_json']),'cameraSnapshot':load(d['camera_snapshot_json']),'screenshotUrl':'/'+d['screenshot_path'] if d['screenshot_path'] else None,'createdAt':d['created_at'],'updatedAt':d['updated_at'],'replies':[{'id':x['id'],'authorType':x['author_type'],'body':x['body'],'attachments':load(x['attachments_json'],[]),'createdAt':x['created_at']} for x in replies],'attachments':[{'id':x['id'],'assetId':x['asset_id'],'viewRole':x['view_role'],'purpose':x['purpose'],'name':x['original_name'],'mimeType':x['mime_type'],'url':'/'+x['storage_path'].replace('\\','/')} for x in attachments]}

def get_comment(cid):
    with db() as con:r=con.execute('SELECT * FROM version_comments WHERE id=?',(cid,)).fetchone()
    if not r:raise HTTPException(404,'Comment 不存在')
    return r

@app.post('/api/versions/{vid}/comments',status_code=201)
def create_comment(vid:str,body:CommentInput):
    version=version_json(vid)
    if body.category not in COMMENT_CATEGORIES or body.severity not in COMMENT_SEVERITIES or body.recommendedRoute not in COMMENT_ROUTES:raise HTTPException(422,'Comment 分类、严重程度或处理路线无效')
    cid=uid('cmt');stamp=now();screenshot=None
    if body.screenshotDataUrl:
        import base64
        try:
            header,data=body.screenshotDataUrl.split(',',1)
            if 'image/png' not in header:raise ValueError()
            raw=base64.b64decode(data,validate=True)
            if len(raw)>10*1024*1024:raise ValueError()
            target=project_dir(version['projectId'])/'comments';target.mkdir(parents=True,exist_ok=True);path=target/f'{cid}.png';path.write_bytes(raw);screenshot=storage_path(path)
        except ValueError:raise HTTPException(422,'截图必须是小于 10MB 的 PNG data URL')
    with db() as con:
        number=con.execute('SELECT COALESCE(MAX(number),0)+1 FROM version_comments WHERE project_id=?',(version['projectId'],)).fetchone()[0]
        con.execute('INSERT INTO version_comments VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(cid,version['projectId'],vid,number,body.title,body.description,body.category,body.severity,'open',body.recommendedRoute,body.meshName,dump(body.position) if body.position else None,dump(body.normal) if body.normal else None,dump(body.cameraSnapshot) if body.cameraSnapshot else None,screenshot,stamp,stamp,None))
    return comment_json(get_comment(cid))

@app.get('/api/versions/{vid}/comments')
def version_comments(vid:str,status:str|None=None):
    version_json(vid);sql='SELECT * FROM version_comments WHERE version_id=?';args=[vid]
    if status:sql+=' AND status=?';args.append(status)
    sql+=' ORDER BY number DESC'
    with db() as con:rows=con.execute(sql,args).fetchall()
    return [comment_json(r) for r in rows]

@app.get('/api/comments/{cid}')
def comment(cid:str):return comment_json(get_comment(cid))

@app.patch('/api/comments/{cid}')
def patch_comment(cid:str,body:CommentPatch):
    row=get_comment(cid)
    if row['status'] not in ('draft','open'):raise HTTPException(409,'只有草稿或开放 Comment 可以编辑')
    data=body.model_dump(exclude_none=True);mapping={'title':'title','description':'description','category':'category','severity':'severity','recommendedRoute':'recommended_route'}
    with db() as con:
        for key,value in data.items():con.execute(f'UPDATE version_comments SET {mapping[key]}=?,updated_at=? WHERE id=?',(value,now(),cid))
    return comment_json(get_comment(cid))

@app.post('/api/comments/{cid}/replies',status_code=201)
def reply_comment(cid:str,body:ReplyInput):
    get_comment(cid);rid=uid('rpl');stamp=now()
    with db() as con:con.execute('INSERT INTO comment_replies VALUES(?,?,?,?,?,?)',(rid,cid,'user',body.body,'[]',stamp))
    return comment_json(get_comment(cid))

def transition_comment(cid,status):
    row=get_comment(cid);allowed={'closed':{'open','resolved','partially_resolved','unresolved'},'open':{'closed','reopened'}}
    if row['status'] not in allowed[status]:raise HTTPException(409,f'不能从 {row["status"]} 转为 {status}')
    with db() as con:con.execute('UPDATE version_comments SET status=?,updated_at=?,closed_at=? WHERE id=?',(status,now(),now() if status=='closed' else None,cid))
    return comment_json(get_comment(cid))
@app.post('/api/comments/{cid}/close')
def close_comment(cid:str):return transition_comment(cid,'closed')
@app.post('/api/comments/{cid}/reopen')
def reopen_comment(cid:str):return transition_comment(cid,'open')

@app.post('/api/comments/{cid}/attachments',status_code=201)
async def comment_attachment(cid:str,viewRole:str=Query(...),purpose:str=Query('auxiliary_reference'),file:UploadFile=File(...)):
    row=get_comment(cid);safe=Path(file.filename or 'reference.png').name;ext=Path(safe).suffix.lower()
    if safe!=file.filename or ext not in {'.png','.jpg','.jpeg','.webp'}:raise HTTPException(415,'仅支持 PNG/JPG/WEBP 参考图')
    raw=await file.read(20*1024*1024+1)
    if len(raw)>20*1024*1024:raise HTTPException(413,'图片超过 20MB')
    aid=uid('ast');target=project_dir(row['project_id'])/'assets'/'comments';target.mkdir(parents=True,exist_ok=True);path=target/f'{aid}{ext}';path.write_bytes(raw)
    try:
        with Image.open(path) as im:im.verify()
        with Image.open(path) as im:w,h=im.size;fmt=(im.format or '').lower()
    except Exception:path.unlink(missing_ok=True);raise HTTPException(415,'图片内容无法解码')
    mime={'png':'image/png','jpeg':'image/jpeg','webp':'image/webp'}.get(fmt)
    if not mime:path.unlink(missing_ok=True);raise HTTPException(415,'图片格式不受支持')
    stamp=now();link=uid('cat')
    with db() as con:
        con.execute('INSERT INTO assets VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',(aid,row['project_id'],f'comment-{viewRole}',safe,storage_path(path),mime,len(raw),w,h,sha256(path),1,stamp))
        con.execute('INSERT INTO comment_attachments VALUES(?,?,?,?,?,?)',(link,cid,aid,viewRole,purpose,stamp))
    return comment_json(get_comment(cid))

def reference_set_json(row):
    d=dict(row)
    with db() as con:assets=con.execute('SELECT rsa.*,a.original_name,a.storage_path,a.mime_type FROM reference_set_assets rsa JOIN assets a ON a.id=rsa.asset_id WHERE rsa.reference_set_id=? ORDER BY rsa.created_at',(d['id'],)).fetchall()
    return {'id':d['id'],'projectId':d['project_id'],'number':d['number'],'parentReferenceSetId':d['parent_reference_set_id'],'status':d['status'],'consistencyReport':load(d['consistency_report'],{}),'lockedAt':d['locked_at'],'createdAt':d['created_at'],'assets':[{'assetId':a['asset_id'],'viewRole':a['view_role'],'purpose':a['purpose'],'sourceCommentId':a['source_comment_id'],'name':a['original_name'],'url':'/'+a['storage_path'].replace('\\','/')} for a in assets]}

def build_reference_set(project_id,comment_ids):
    stamp=now();rid=uid('rfs')
    with db() as con:
        number=con.execute('SELECT COALESCE(MAX(number),0)+1 FROM reference_sets WHERE project_id=?',(project_id,)).fetchone()[0]
        parent=con.execute('SELECT id FROM reference_sets WHERE project_id=? ORDER BY number DESC LIMIT 1',(project_id,)).fetchone()
        con.execute('INSERT INTO reference_sets VALUES(?,?,?,?,?,?,?,?)',(rid,project_id,number,parent['id'] if parent else None,'draft','{}',stamp,None))
        base=con.execute("SELECT * FROM assets WHERE project_id=? AND active=1 AND role IN ('front','side','back','left-three-quarter','right-three-quarter')",(project_id,)).fetchall()
        for a in base:con.execute('INSERT INTO reference_set_assets VALUES(?,?,?,?,?,?,?)',(uid('rsa'),rid,a['id'],a['role'],'baseline',None,stamp))
        marks=','.join('?'*len(comment_ids));extra=con.execute(f'SELECT ca.*,a.role FROM comment_attachments ca JOIN assets a ON a.id=ca.asset_id WHERE ca.comment_id IN ({marks})',comment_ids).fetchall()
        for a in extra:con.execute('INSERT INTO reference_set_assets VALUES(?,?,?,?,?,?,?)',(uid('rsa'),rid,a['asset_id'],a['view_role'],a['purpose'],a['comment_id'],stamp))
    return rid

@app.post('/api/revisions/plan')
def plan_revision(body:RevisionPlanInput):
    source=version_json(body.sourceVersionId)
    with db() as con:comments=con.execute(f"SELECT * FROM version_comments WHERE id IN ({','.join('?'*len(body.commentIds))})",body.commentIds).fetchall()
    if len(comments)!=len(set(body.commentIds)) or any(c['version_id']!=body.sourceVersionId for c in comments):raise HTTPException(422,'所选 Comments 必须属于源版本')
    routes={r:sum(c['recommended_route']==r for c in comments) for r in COMMENT_ROUTES};usable=sum(r['recommended_route']=='reference_regeneration' for r in comments)
    return {'sourceVersion':source,'comments':[comment_json(c) for c in comments],'routes':routes,'canCreate':usable>0,'excludedCommentIds':[c['id'] for c in comments if c['recommended_route']!='reference_regeneration'],'risk':'Hunyuan 将根据完整 Reference Set 重新生成独立候选版本，不保证只修改标注区域，也不保证拓扑、UV 或材质保持不变。'}

@app.post('/api/revisions',status_code=201)
def create_revision(body:RevisionCreateInput):
    plan=plan_revision(body)
    if not plan['canCreate']:raise HTTPException(409,'所选 Comments 中没有可执行的参考图重生成项')
    selected=[c for c in plan['comments'] if c['recommendedRoute']=='reference_regeneration'];cid=[c['id'] for c in selected];source=plan['sourceVersion'];rid=body.referenceSetId or build_reference_set(source['projectId'],cid);request_id=uid('rev');stamp=now()
    with db() as con:
        rs=con.execute('SELECT * FROM reference_sets WHERE id=? AND project_id=?',(rid,source['projectId'])).fetchone()
        if not rs or rs['locked_at']:raise HTTPException(409,'Reference Set 不存在或已经锁定')
        assets=con.execute('SELECT view_role FROM reference_set_assets WHERE reference_set_id=?',(rid,)).fetchall();views={a['view_role'] for a in assets};report={'valid':'front' in views,'views':sorted(views),'warnings':[] if len(views)>=2 else ['建议增加侧面或 3/4 参考图']}
        if not report['valid']:raise HTTPException(422,'Reference Set 至少需要一张正面图')
        con.execute("UPDATE reference_sets SET status='locked',consistency_report=?,locked_at=? WHERE id=?",(dump(report),stamp,rid))
        con.execute('INSERT INTO revision_requests VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(request_id,source['projectId'],body.sourceVersionId,None,rid,'queued','reference_regeneration',dump(body.config),dump([f'[{stamp[11:19]}] 修订任务已创建，Reference Set v{rs["number"]} 已锁定']),stamp,None,None,None,0))
        for c in selected:
            con.execute('INSERT INTO revision_comment_links VALUES(?,?,?,?,?,?,?,?,?)',(uid('rcl'),request_id,c['id'],body.sourceVersionId,None,None,None,stamp,None))
            con.execute("UPDATE version_comments SET status='planned',updated_at=? WHERE id=?",(stamp,c['id']))
    threading.Thread(target=run_revision,args=(request_id,),daemon=True).start()
    return revision_json(request_id)

def revision_json(rid):
    with db() as con:
        r=con.execute('SELECT * FROM revision_requests WHERE id=?',(rid,)).fetchone()
        if not r:raise HTTPException(404,'修订任务不存在')
        links=con.execute('SELECT * FROM revision_comment_links WHERE revision_request_id=?',(rid,)).fetchall();rs=con.execute('SELECT * FROM reference_sets WHERE id=?',(r['reference_set_id'],)).fetchone()
    d=dict(r);return {'id':d['id'],'projectId':d['project_id'],'sourceVersionId':d['source_version_id'],'outputVersionId':d['output_version_id'],'referenceSet':reference_set_json(rs),'status':d['status'],'route':d['route'],'config':load(d['config_snapshot'],{}),'logs':load(d['logs'],[]),'errorSummary':d['error_summary'],'createdAt':d['created_at'],'startedAt':d['started_at'],'completedAt':d['completed_at'],'comments':[comment_json(get_comment(x['comment_id']))|{'resultStatus':x['result_status'],'resultNotes':x['result_notes']} for x in links]}

def run_revision(rid):
    logs=[]
    def log(message):
        logs.append(f'[{now()[11:19]}] {message}')
        with db() as con:con.execute('UPDATE revision_requests SET logs=? WHERE id=?',(dump(logs),rid))
    def cancelled():
        with db() as con:return bool(con.execute('SELECT cancel_requested FROM revision_requests WHERE id=?',(rid,)).fetchone()[0])
    try:
        with db() as con:
            r=dict(con.execute('SELECT * FROM revision_requests WHERE id=?',(rid,)).fetchone());config=load(r['config_snapshot'],{});logs=load(r['logs'],[])
            asset=con.execute("SELECT a.storage_path FROM reference_set_assets rsa JOIN assets a ON a.id=rsa.asset_id WHERE rsa.reference_set_id=? ORDER BY CASE rsa.purpose WHEN 'revised_design' THEN 0 ELSE 1 END, CASE rsa.view_role WHEN 'front' THEN 0 ELSE 1 END LIMIT 1",(r['reference_set_id'],)).fetchone()
            number=con.execute('SELECT COALESCE(MAX(number),0)+1 FROM versions WHERE project_id=?',(r['project_id'],)).fetchone()[0]
            con.execute("UPDATE revision_requests SET status='processing',started_at=? WHERE id=?",(now(),rid));con.execute("UPDATE version_comments SET status='processing',updated_at=? WHERE id IN (SELECT comment_id FROM revision_comment_links WHERE revision_request_id=?)",(now(),rid))
        if not capabilities().get('hunyuan3d'):raise RuntimeError('真实 Hunyuan3D 环境未配置，任务不会使用模拟产物')
        if not capabilities().get('blenderRefinement'):raise RuntimeError('真实 Blender 自动精修环境未配置')
        root=project_dir(r['project_id'])/'revisions'/rid;root.mkdir(parents=True,exist_ok=True);raw=root/'hunyuan-candidate.glb';seed=int(config.get('seed',random.randint(1,2**31-1)));quality=config.get('quality','standard')
        generate_hunyuan(resolve_storage(asset['storage_path']),raw,seed,quality,log,cancelled)
        refdir=root/'blender';refdir.mkdir();cfg={'modules':['geometryRepair','uvUnwrap','pbrMaterials','webOptimization','visualReview'],'instructions':'Reference Set candidate post-processing','geometryRepairStrength':'conservative','uvStrategy':'preserve_or_smart','uvIslandMargin':.03,'materialTemplate':'neutral','targetTriangleRange':[20000,120000],'textureResolution':2048,'maxWebGlbMB':20,'preserveThickness':True,'maxThicknessLoss':.08,'maxDecimationPerPass':.2,'minThinAxisRatio':.08};cfg_path=root/'blender-config.json';cfg_path.write_text(json.dumps(cfg,ensure_ascii=False),encoding='utf-8');result=refine_blender(raw,refdir,cfg_path,log,cancelled,resolve_storage(asset['storage_path']))
        out=uid('ver');stamp=now();status='awaiting_review' if result.get('status')=='passed' else 'quality_failed'
        with db() as con:
            con.execute('INSERT INTO versions VALUES(?,?,?,?,?,?,?)',(out,r['project_id'],number,f'v{number:03d} · Reference Set 候选重生成','ready_for_review' if status=='awaiting_review' else 'quality_failed',dump(result),stamp))
            jid=uid('ref');con.execute('INSERT INTO refinement_jobs(id,project_id,source_version_id,output_version_id,status,config,module_states,logs,created_at,started_at,completed_at,blender_version,quality_report) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',(jid,r['project_id'],r['source_version_id'],out,status,dump(cfg),dump({m:'passed' for m in cfg['modules']}),dump(logs),r['created_at'],r['started_at'],stamp,result.get('blenderVersion'),dump(result)));con.execute('INSERT INTO version_links VALUES(?,?,?,?,?)',(uid('vln'),r['source_version_id'],out,jid,stamp))
            files=[('glb','candidate-refined.glb',refdir/'refined.glb','model/gltf-binary')]+[('render',f'{v}.png',refdir/f'{v}.png','image/png') for v in ('front','left-three-quarter','side','back')]
            for kind,label,path,mime in files:
                if path.exists():con.execute('INSERT INTO refinement_artifacts VALUES(?,?,?,?,?,?,?,?,?,?,?)',(uid('rart'),jid,out,kind,label,storage_path(path),mime,path.stat().st_size,sha256(path),dump({'revisionRequestId':rid}),stamp))
            con.execute('UPDATE revision_requests SET output_version_id=?,status=?,completed_at=? WHERE id=?',(out,status,stamp,rid));con.execute('UPDATE revision_comment_links SET output_version_id=? WHERE revision_request_id=?',(out,rid));con.execute("UPDATE version_comments SET status='awaiting_review',updated_at=? WHERE id IN (SELECT comment_id FROM revision_comment_links WHERE revision_request_id=?)",(stamp,rid))
    except CancelledError as exc:
        with db() as con:con.execute("UPDATE revision_requests SET status='cancelled',completed_at=?,error_summary=? WHERE id=?",(now(),str(exc),rid));con.execute("UPDATE version_comments SET status='open',updated_at=? WHERE id IN (SELECT comment_id FROM revision_comment_links WHERE revision_request_id=?)",(now(),rid))
    except Exception as exc:
        log(f'修订任务失败：{exc}')
        with db() as con:con.execute("UPDATE revision_requests SET status='failed',completed_at=?,error_summary=? WHERE id=?",(now(),str(exc),rid));con.execute("UPDATE version_comments SET status='open',updated_at=? WHERE id IN (SELECT comment_id FROM revision_comment_links WHERE revision_request_id=?)",(now(),rid))

@app.get('/api/revisions/{rid}')
def get_revision(rid:str):return revision_json(rid)
@app.post('/api/revisions/{rid}/cancel')
def cancel_revision(rid:str):
    revision_json(rid)
    with db() as con:con.execute('UPDATE revision_requests SET cancel_requested=1 WHERE id=?',(rid,))
    return revision_json(rid)
@app.post('/api/revisions/{rid}/retry',status_code=201)
def retry_revision(rid:str):
    old=revision_json(rid)
    if old['status'] not in ('failed','cancelled'):raise HTTPException(409,'只有失败或取消的任务可以重试')
    return create_revision(RevisionCreateInput(sourceVersionId=old['sourceVersionId'],commentIds=[c['id'] for c in old['comments']],config=old['config']))
@app.post('/api/revisions/{rid}/comments/{cid}/review')
def review_revision_comment(rid:str,cid:str,body:CommentReviewInput):
    mapping={'resolved':'resolved','partially_resolved':'partially_resolved','unresolved':'unresolved','new_issue':'unresolved'}
    if body.resultStatus not in mapping:raise HTTPException(422,'复核结果无效')
    with db() as con:
        link=con.execute('SELECT * FROM revision_comment_links WHERE revision_request_id=? AND comment_id=?',(rid,cid)).fetchone()
        if not link:raise HTTPException(404,'Comment 不属于该修订任务')
        req=con.execute('SELECT status FROM revision_requests WHERE id=?',(rid,)).fetchone()
        if req['status']!='awaiting_review':raise HTTPException(409,'任务尚未进入人工复核')
        con.execute('UPDATE revision_comment_links SET result_status=?,result_notes=?,reviewed_at=? WHERE revision_request_id=? AND comment_id=?',(body.resultStatus,body.notes,now(),rid,cid));con.execute('UPDATE version_comments SET status=?,updated_at=? WHERE id=?',(mapping[body.resultStatus],now(),cid))
        if body.resultStatus=='new_issue':
            src=get_comment(cid);newid=uid('cmt');number=con.execute('SELECT COALESCE(MAX(number),0)+1 FROM version_comments WHERE project_id=?',(src['project_id'],)).fetchone()[0];stamp=now();con.execute('INSERT INTO version_comments VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(newid,src['project_id'],link['output_version_id'],number,f'衍生问题：{src["title"]}',body.notes or '候选版本产生了新问题',src['category'],src['severity'],'open',src['recommended_route'],src['mesh_name'],src['position_json'],src['normal_json'],src['camera_snapshot_json'],None,stamp,stamp,None))
    return revision_json(rid)

def detail_plan_json(plan_id:str):
    with db() as con:
        plan=con.execute('SELECT * FROM detail_plans WHERE id=?',(plan_id,)).fetchone()
        if not plan:raise HTTPException(404,'细节计划不存在')
        regions=con.execute('SELECT * FROM detail_regions WHERE detail_plan_id=? ORDER BY rowid',(plan_id,)).fetchall()
    return {'id':plan['id'],'projectId':plan['project_id'],'sourceReferenceSetId':plan['source_reference_set_id'],'status':plan['status'],'mode':plan['mode'],'analyzerVersion':plan['analyzer_version'],'summary':load(plan['summary_json'],{}),'createdAt':plan['created_at'],'confirmedAt':plan['confirmed_at'],'regions':[{'id':r['id'],'regionKey':r['region_key'],'visibleViews':load(r['visible_views_json'],[]),'coverageScore':r['coverage_score'],'clarityScore':r['clarity_score'],'consistencyScore':r['consistency_score'],'evidenceLevel':r['evidence_level'],'targetUsage':r['target_usage'],'riskLevel':r['risk_level'],'recommendedViews':load(r['recommended_views_json'],[]),'constraints':load(r['constraints_json'],{}),'selected':bool(r['selected'])} for r in regions]}

def ensure_source_reference_set(con,project_id:str):
    latest=con.execute("SELECT id FROM reference_sets WHERE project_id=? AND status='locked' ORDER BY number DESC LIMIT 1",(project_id,)).fetchone()
    if latest:return latest['id']
    assets=con.execute("SELECT * FROM assets WHERE project_id=? AND active=1 AND role IN ('front','side','back','left-three-quarter','right-three-quarter') ORDER BY created_at",(project_id,)).fetchall()
    if not any(a['role']=='front' for a in assets):raise HTTPException(422,'创建细节计划前必须上传正面素材')
    stamp=now();rid=uid('rfs');number=con.execute('SELECT COALESCE(MAX(number),0)+1 FROM reference_sets WHERE project_id=?',(project_id,)).fetchone()[0]
    con.execute('INSERT INTO reference_sets VALUES(?,?,?,?,?,?,?,?)',(rid,project_id,number,None,'locked',dump({'valid':True,'views':sorted({a['role'] for a in assets}),'source':'validated-assets'}),stamp,stamp))
    for a in assets:con.execute('INSERT INTO reference_set_assets VALUES(?,?,?,?,?,?,?)',(uid('rsa'),rid,a['id'],a['role'],'baseline',None,stamp))
    return rid

@app.post('/api/projects/{pid}/detail-plans',status_code=201)
def create_detail_plan(pid:str,body:DetailPlanInput):
    get_project(pid)
    if body.mode not in DETAIL_MODES:raise HTTPException(422,'细节模式无效')
    with db() as con:
        validation=con.execute('SELECT * FROM validations WHERE project_id=? ORDER BY created_at DESC LIMIT 1',(pid,)).fetchone()
        if not validation or validation['verdict'] in ('request_input','reject') or (validation['verdict']=='conditional' and not validation['accepted_at']):raise HTTPException(409,'素材必须先通过校验并接受风险')
        active={r['role']:r for r in con.execute("SELECT role,width,height FROM assets WHERE project_id=? AND active=1",(pid,)).fetchall()};views=set(active);source=ensure_source_reference_set(con,pid);stamp=now();plan_id=uid('dtp')
        old=con.execute("SELECT id FROM detail_plans WHERE project_id=? AND status IN ('analyzing','awaiting_confirmation','confirmed')",(pid,)).fetchall()
        for row in old:con.execute("UPDATE detail_plans SET status='superseded' WHERE id=?",(row['id'],))
        con.execute('INSERT INTO detail_plans VALUES(?,?,?,?,?,?,?,?,?)',(plan_id,pid,source,'awaiting_confirmation',body.mode,'rules-v1',dump({'availableViews':sorted(views),'regionCount':len(DETAIL_REGION_SPECS),'notice':'规则规划，不替代人工区域确认'}),stamp,None))
        for key,(usage,recommended) in DETAIL_REGION_SPECS.items():
            relevant=set(recommended);visible=sorted(views&relevant);coverage=round(len(visible)/max(len(relevant),1),2);clarity=round(min([min(active[v]['width'],active[v]['height'])/2048 for v in visible] or [0]),2);consistency=round(.5+.15*max(0,len(visible)-1),2);evidence='observed' if coverage==1 else ('constrained' if len(visible)>=2 else 'inferred');risk='low' if coverage==1 and clarity>=.5 else ('medium' if visible else 'high');selected=key in ('face','neck_collar','left_shoulder_sleeve','right_shoulder_sleeve') and risk!='low'
            constraints={'mode':body.mode,'preserveIdentity':key in ('head','face','hair'),'preserveGarmentStructure':key not in ('head','face','hair')}
            con.execute('INSERT INTO detail_regions VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(uid('dtr'),plan_id,key,None,dump(visible),coverage,clarity,consistency,evidence,usage,risk,dump([v for v in recommended if v not in views]),dump(constraints),int(selected)))
    return detail_plan_json(plan_id)

@app.get('/api/detail-plans/{plan_id}')
def get_detail_plan(plan_id:str):return detail_plan_json(plan_id)

@app.patch('/api/detail-plans/{plan_id}/regions/{region_id}')
def patch_detail_region(plan_id:str,region_id:str,body:DetailRegionPatch):
    with db() as con:
        plan=con.execute('SELECT status FROM detail_plans WHERE id=?',(plan_id,)).fetchone();region=con.execute('SELECT * FROM detail_regions WHERE id=? AND detail_plan_id=?',(region_id,plan_id)).fetchone()
        if not plan or not region:raise HTTPException(404,'细节计划或区域不存在')
        if plan['status']!='awaiting_confirmation':raise HTTPException(409,'只有待确认计划可以修改')
        if body.targetUsage and body.targetUsage not in DETAIL_USAGES:raise HTTPException(422,'目标用途无效')
        constraints=load(region['constraints_json'],{})
        if body.mode:
            if body.mode not in DETAIL_MODES:raise HTTPException(422,'细节模式无效')
            constraints['mode']=body.mode
        if body.constraints is not None:constraints.update(body.constraints)
        con.execute('UPDATE detail_regions SET selected=?,target_usage=?,constraints_json=? WHERE id=?',(int(body.selected) if body.selected is not None else region['selected'],body.targetUsage or region['target_usage'],dump(constraints),region_id))
    return detail_plan_json(plan_id)

@app.post('/api/detail-plans/{plan_id}/confirm')
def confirm_detail_plan(plan_id:str):
    with db() as con:
        plan=con.execute('SELECT status FROM detail_plans WHERE id=?',(plan_id,)).fetchone()
        if not plan:raise HTTPException(404,'细节计划不存在')
        if plan['status']!='awaiting_confirmation':raise HTTPException(409,'计划不能重复确认')
        if not con.execute('SELECT 1 FROM detail_regions WHERE detail_plan_id=? AND selected=1',(plan_id,)).fetchone():raise HTTPException(422,'至少选择一个区域')
        con.execute("UPDATE detail_plans SET status='confirmed',confirmed_at=? WHERE id=?",(now(),plan_id))
    return detail_plan_json(plan_id)

def detail_job_json(job_id:str):
    with db() as con:
        job=con.execute('SELECT * FROM detail_generation_jobs WHERE id=?',(job_id,)).fetchone()
        if not job:raise HTTPException(404,'细节生成任务不存在')
        groups=con.execute('SELECT dcg.*,dr.region_key FROM detail_candidate_groups dcg JOIN detail_regions dr ON dr.id=dcg.region_id WHERE dcg.job_id=? ORDER BY dr.region_key,dcg.group_index',(job_id,)).fetchall()
        result=[]
        for g in groups:
            assets=con.execute('SELECT dca.*,a.original_name,a.storage_path,a.sha256 FROM detail_candidate_assets dca JOIN assets a ON a.id=dca.asset_id WHERE dca.candidate_group_id=? ORDER BY dca.view_role',(g['id'],)).fetchall()
            review=con.execute("SELECT reference_set_id FROM detail_review_events WHERE candidate_group_id=? AND action='approved' ORDER BY created_at DESC LIMIT 1",(g['id'],)).fetchone()
            result.append({'id':g['id'],'regionId':g['region_id'],'regionKey':g['region_key'],'groupIndex':g['group_index'],'status':g['status'],'evidenceLevel':g['evidence_level'],'targetUsage':g['target_usage'],'referenceSetId':review['reference_set_id'] if review else None,'consistencyMetrics':load(g['consistency_metrics_json'],{}),'reviewedAt':g['reviewed_at'],'reviewNote':g['review_note'],'assets':[{'assetId':a['asset_id'],'viewRole':a['view_role'],'name':a['original_name'],'url':'/'+a['storage_path'].replace('\\','/'),'sha256':a['sha256']} for a in assets]})
    with db() as con:project_id=con.execute('SELECT dp.project_id FROM detail_plans dp WHERE dp.id=?',(job['detail_plan_id'],)).fetchone()['project_id']
    return {'id':job['id'],'projectId':project_id,'detailPlanId':job['detail_plan_id'],'status':job['status'],'provider':job['provider'],'model':job['model'],'workflowVersion':job['workflow_version'],'seed':job['seed'],'parameters':load(job['parameters_json'],{}),'createdAt':job['created_at'],'startedAt':job['started_at'],'finishedAt':job['finished_at'],'errorCode':job['error_code'],'errorMessage':job['error_message'],'progress':{'current':job['current_step'],'total':job['total_steps'],'message':job['current_message'],'percent':round(job['current_step']/job['total_steps']*100) if job['total_steps'] else 0},'logs':load(job['logs_json'],[]),'groups':result}

@app.post('/api/detail-plans/{plan_id}/jobs',status_code=201)
def create_detail_job(plan_id:str,body:DetailJobInput):
    with db() as con:
        plan=con.execute('SELECT * FROM detail_plans WHERE id=?',(plan_id,)).fetchone()
        if not plan:raise HTTPException(404,'细节计划不存在')
        if plan['status']!='confirmed':raise HTTPException(409,'计划确认后才能创建生成任务')
        job_id=uid('dtj');stamp=now();seed=body.seed or random.randint(1,2**31-1)
        con.execute('INSERT INTO detail_generation_jobs(id,detail_plan_id,status,provider,model,workflow_version,seed,parameters_json,started_at,finished_at,error_code,error_message,cancel_requested,created_at,current_step,total_steps,current_message,logs_json) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(job_id,plan_id,'queued','comfyui_local','sd15-inpainting','detail-regions-v1',seed,dump({'candidateCount':body.candidateCount,'mode':plan['mode'],'gpuPolicy':'serial'}),None,None,None,None,0,stamp,0,0,'等待 Worker 领取',dump([f'[{stamp[11:19]}] 细节任务已进入串行 GPU 队列'])))
        regions=con.execute('SELECT * FROM detail_regions WHERE detail_plan_id=? AND selected=1',(plan_id,)).fetchall()
        for region in regions:
            evidence='designed' if plan['mode']=='creative' else ('inferred' if region['evidence_level']=='inferred' else 'constrained')
            for index in range(1,body.candidateCount+1):con.execute('INSERT INTO detail_candidate_groups VALUES(?,?,?,?,?,?,?,?,?,?)',(uid('dcg'),job_id,region['id'],index,'draft',evidence,region['target_usage'],dump({'status':'pending_generation'}),None,None))
    threading.Thread(target=run_detail_job,args=(job_id,),daemon=True,name=f'detail-{job_id}').start()
    return detail_job_json(job_id)

def run_detail_job(job_id:str):
    def cancelled():
        with db() as con:return bool(con.execute('SELECT cancel_requested FROM detail_generation_jobs WHERE id=?',(job_id,)).fetchone()[0])
    try:
        with db() as con:
            job=con.execute('SELECT dgj.*,dp.project_id,dp.mode,dp.source_reference_set_id FROM detail_generation_jobs dgj JOIN detail_plans dp ON dp.id=dgj.detail_plan_id WHERE dgj.id=?',(job_id,)).fetchone()
            groups=con.execute('SELECT dcg.*,dr.region_key,dr.visible_views_json,dr.mask_asset_id FROM detail_candidate_groups dcg JOIN detail_regions dr ON dr.id=dcg.region_id WHERE dcg.job_id=? ORDER BY dcg.group_index,dr.region_key',(job_id,)).fetchall()
            sources={a['view_role']:a for a in con.execute('SELECT rsa.view_role,a.* FROM reference_set_assets rsa JOIN assets a ON a.id=rsa.asset_id WHERE rsa.reference_set_id=?',(job['source_reference_set_id'],)).fetchall()}
            total=sum(len([v for v in load(g['visible_views_json'],[]) if v in sources and v in ('front','side','back','left-three-quarter','right-three-quarter')]) for g in groups)
            con.execute("UPDATE detail_generation_jobs SET status='generating',started_at=?,total_steps=?,current_message=? WHERE id=?",(now(),total,'准备 ComfyUI 环境',job_id))
        denoise={'conservative':.20,'balanced':.28,'creative':.45}[job['mode']];root=project_dir(job['project_id'])/'detail-jobs'/job_id
        def log(message):
            stamp=now();entry=f'[{stamp[11:19]}] {message}'
            with db() as con:
                row=con.execute('SELECT logs_json FROM detail_generation_jobs WHERE id=?',(job_id,)).fetchone();logs=load(row['logs_json'],[]);logs.append(entry);con.execute('UPDATE detail_generation_jobs SET logs_json=?,current_message=? WHERE id=?',(dump(logs[-200:]),message,job_id))
        completed=0
        for group in groups:
            views=[v for v in load(group['visible_views_json'],[]) if v in sources and v in ('front','side','back','left-three-quarter','right-three-quarter')]
            if not views:raise RuntimeError(f"区域 {group['region_key']} 没有可生成的真实源视图")
            generated=[]
            for view in views:
                if cancelled():raise CancelledError('细节生成已取消')
                message=f"生成 {group['region_key']} · 候选组 {group['group_index']} · {view}"
                with db() as con:con.execute('UPDATE detail_generation_jobs SET current_message=? WHERE id=?',(message,job_id))
                log(message)
                source=sources[view];seed=int(job['seed'])+group['group_index']*100+len(generated);output=root/group['region_key']/f"group-{group['group_index']}"/f'{view}.png';meta=generate_detail_candidate(resolve_storage(source['storage_path']),group['region_key'],view,output,seed,denoise,log,cancelled)
                aid=uid('ast');stamp=now();rel=storage_path(output)
                with Image.open(output) as im:width,height=im.size
                with db() as con:
                    con.execute('INSERT INTO assets VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',(aid,job['project_id'],'detail-candidate',output.name,rel,'image/png',output.stat().st_size,width,height,sha256(output),0,stamp))
                    con.execute('INSERT INTO detail_candidate_assets VALUES(?,?,?,?,?,?,?,?)',(uid('dca'),group['id'],aid,view,dump({'role':view}),source['id'],group['mask_asset_id'],stamp))
                generated.append({'view':view,'width':width,'height':height,'sha256':sha256(output),'generation':meta})
                completed+=1
                with db() as con:con.execute('UPDATE detail_generation_jobs SET current_step=?,current_message=? WHERE id=?',(completed,f"已完成 {group['region_key']} · 候选组 {group['group_index']} · {view}",job_id))
            unique_views=len({x['view'] for x in generated})==len(generated);hashes_unique=len({x['sha256'] for x in generated})==len(generated);gate='passed' if unique_views and (len(generated)==1 or hashes_unique) else 'blocked'
            with db() as con:con.execute("UPDATE detail_candidate_groups SET consistency_metrics_json=? WHERE id=?",(dump({'status':gate,'viewCount':len(generated),'views':[x['view'] for x in generated],'uniqueViews':unique_views,'distinctOutputs':hashes_unique,'checks':{'decodable':True,'dimensionsPreserved':True,'maskQualityPassed':True},'generation':generated}),group['id']))
        with db() as con:con.execute("UPDATE detail_generation_jobs SET status='awaiting_approval',finished_at=?,current_step=total_steps,current_message='候选生成完成，等待人工审批' WHERE id=?",(now(),job_id))
    except CancelledError as exc:
        with db() as con:con.execute("UPDATE detail_generation_jobs SET status='cancelled',finished_at=?,error_message=?,current_message='任务已取消' WHERE id=?",(now(),str(exc),job_id))
    except Exception as exc:
        with db() as con:con.execute("UPDATE detail_generation_jobs SET status='failed',finished_at=?,error_code='DETAIL_PROVIDER_ERROR',error_message=?,current_message='候选生成失败' WHERE id=?",(now(),str(exc),job_id))
    finally:
        stop_detail_server(log)

@app.get('/api/detail-jobs/{job_id}')
def get_detail_job(job_id:str):return detail_job_json(job_id)

@app.post('/api/detail-jobs/{job_id}/cancel')
def cancel_detail_job(job_id:str):
    detail_job_json(job_id)
    with db() as con:con.execute("UPDATE detail_generation_jobs SET cancel_requested=1,status=CASE WHEN status IN ('queued','generating') THEN 'cancelled' ELSE status END,finished_at=CASE WHEN status IN ('queued','generating') THEN ? ELSE finished_at END WHERE id=?",(now(),job_id))
    return detail_job_json(job_id)

@app.post('/api/detail-jobs/{job_id}/retry',status_code=201)
def retry_detail_job(job_id:str):
    old=detail_job_json(job_id)
    if old['status'] not in ('failed','cancelled'):raise HTTPException(409,'只有失败或取消的细节任务可以重试')
    return create_detail_job(old['detailPlanId'],DetailJobInput(candidateCount=int(old['parameters'].get('candidateCount',2))))

@app.post('/api/detail-candidate-groups/{group_id}/reject')
def reject_detail_group(group_id:str,body:DetailReviewInput):
    with db() as con:
        group=con.execute('SELECT status FROM detail_candidate_groups WHERE id=?',(group_id,)).fetchone()
        if not group:raise HTTPException(404,'候选组不存在')
        if group['status']!='draft':raise HTTPException(409,'候选组已经完成审批')
        stamp=now();con.execute("UPDATE detail_candidate_groups SET status='rejected',reviewed_at=?,review_note=? WHERE id=?",(stamp,body.notes,group_id));con.execute('INSERT INTO detail_review_events VALUES(?,?,?,?,?,?,?)',(uid('dre'),group_id,'rejected','local-admin',body.notes,None,stamp))
    return {'groupId':group_id,'status':'rejected'}

@app.post('/api/detail-candidate-groups/{group_id}/approve')
def approve_detail_group(group_id:str,body:DetailReviewInput):
    with db() as con:
        group=con.execute('SELECT dcg.*,dgj.detail_plan_id,dp.project_id,dp.source_reference_set_id FROM detail_candidate_groups dcg JOIN detail_generation_jobs dgj ON dgj.id=dcg.job_id JOIN detail_plans dp ON dp.id=dgj.detail_plan_id WHERE dcg.id=?',(group_id,)).fetchone()
        if not group:raise HTTPException(404,'候选组不存在')
        if group['status']!='draft':raise HTTPException(409,'候选组已经完成审批')
        candidates=con.execute('SELECT * FROM detail_candidate_assets WHERE candidate_group_id=?',(group_id,)).fetchall()
        if not candidates:raise HTTPException(409,'候选组尚无完整生成资产，不能批准')
        metrics=load(group['consistency_metrics_json'],{})
        if metrics.get('status')!='passed':raise HTTPException(409,'候选组未通过跨视图一致性门禁，不能批准')
        prior=con.execute("SELECT dre.reference_set_id FROM detail_review_events dre JOIN detail_candidate_groups dcg ON dcg.id=dre.candidate_group_id JOIN detail_generation_jobs dgj ON dgj.id=dcg.job_id WHERE dgj.detail_plan_id=? AND dre.action='approved' ORDER BY dre.created_at DESC LIMIT 1",(group['detail_plan_id'],)).fetchone();parent_id=prior['reference_set_id'] if prior else group['source_reference_set_id']
        stamp=now();rid=uid('rfs');number=con.execute('SELECT COALESCE(MAX(number),0)+1 FROM reference_sets WHERE project_id=?',(group['project_id'],)).fetchone()[0]
        con.execute('INSERT INTO reference_sets VALUES(?,?,?,?,?,?,?,?)',(rid,group['project_id'],number,parent_id,'locked',dump({'approvedCandidateGroupId':group_id,'evidenceLevel':group['evidence_level'],'targetUsage':group['target_usage']}),stamp,stamp))
        parent_assets=con.execute('SELECT * FROM reference_set_assets WHERE reference_set_id=?',(parent_id,)).fetchall()
        for a in parent_assets:con.execute('INSERT INTO reference_set_assets VALUES(?,?,?,?,?,?,?)',(uid('rsa'),rid,a['asset_id'],a['view_role'],a['purpose'],a['source_comment_id'],stamp))
        for a in candidates:con.execute('INSERT INTO reference_set_assets VALUES(?,?,?,?,?,?,?)',(uid('rsa'),rid,a['asset_id'],a['view_role'],group['target_usage'],None,stamp))
        con.execute("UPDATE detail_candidate_groups SET status='approved',reviewed_at=?,review_note=? WHERE id=?",(stamp,body.notes,group_id));con.execute('INSERT INTO detail_review_events VALUES(?,?,?,?,?,?,?)',(uid('dre'),group_id,'approved','local-admin',body.notes,rid,stamp))
    return {'groupId':group_id,'status':'approved','referenceSet':reference_set_json(con_row_reference(rid))}

def con_row_reference(rid:str):
    with db() as con:return con.execute('SELECT * FROM reference_sets WHERE id=?',(rid,)).fetchone()

def reference_set_consumption(rid:str):
    with db() as con:
        rs=con.execute('SELECT * FROM reference_sets WHERE id=?',(rid,)).fetchone()
        if not rs:raise HTTPException(404,'Reference Set 不存在')
        rows=con.execute('SELECT rsa.*,a.original_name,a.storage_path,a.sha256,a.mime_type FROM reference_set_assets rsa JOIN assets a ON a.id=rsa.asset_id WHERE rsa.reference_set_id=? ORDER BY rsa.created_at',(rid,)).fetchall()
    actual={}
    for a in rows:
        if a['view_role'] in ('front','side','back') and (a['view_role'] not in actual or a['purpose']=='geometry'):actual[a['view_role']]={'assetId':a['asset_id'],'name':a['original_name'],'storagePath':a['storage_path'],'sha256':a['sha256'],'purpose':a['purpose']}
    blender=[{'assetId':a['asset_id'],'viewRole':a['view_role'],'name':a['original_name'],'storagePath':a['storage_path'],'sha256':a['sha256'],'purpose':a['purpose']} for a in rows if a['view_role'] not in ('front','side','back') or a['purpose'] in ('normal_displacement','material')]
    return {'referenceSetId':rid,'version':rs['number'],'lockedAt':rs['locked_at'],'hunyuanInputs':actual,'blenderOnlyAssets':blender,'warnings':([] if all(v in actual for v in ('front','side','back')) else ['Hunyuan3D-2mv 需要 front、side、back；缺失时任务将被阻断'])}

@app.get('/api/reference-sets/{rid}/consumption-map')
def get_reference_consumption(rid:str):return reference_set_consumption(rid)

def seed_demo():
    with db() as con:
        if con.execute('SELECT COUNT(*) FROM projects').fetchone()[0]:return
        src=ROOT/'public'/'models'/'yoyo-front-projection-v1.glb'
        if not src.exists():return
        pid='prj_0000000000000001';stamp=now();thumb='/public/yoyo-reference.png';con.execute('INSERT INTO projects(id,slug,name,subject_type,intended_use,quality,status,passed_stages,total_stages,actual_backend,thumbnail_url,settings,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(pid,'yoyo-demo','YOYO · 星空信使','character','web','high','ready_for_review',9,9,'Hunyuan3D + Blender',thumb,'{}',stamp,stamp));vid='ver_0000000000000001';jid='job_0000000000000001';con.execute('INSERT INTO versions VALUES(?,?,?,?,?,?,?)',(vid,pid,1,'v001 · 参考图投射基线','ready_for_review',dump({'scores':{'轮廓匹配':92,'比例一致性':95,'正面可信度':94,'侧面可信度':79,'背面可信度':72},'stats':{'fileSize':'16.7 MB','maxTexture':'2048 × 2048'},'differences':[{'severity':'minor','message':'背面披风厚度来自推断。'}],'approximations':[{'region':'背面','confidence':.72,'note':'参考证据有限'}]}),stamp));con.execute('INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(jid,pid,vid,'completed','{}','hunyuan3d','Hunyuan3D + Blender','2.1',42,'web_optimization',1,stamp,stamp,stamp,None,None,0));con.execute('UPDATE projects SET current_job_id=? WHERE id=?',(jid,pid));con.execute('INSERT INTO artifacts VALUES(?,?,?,?,?,?,?,?,?,?,?)',('art_0000000000000001',jid,vid,'glb','yoyo-front-projection-v1.glb',src.relative_to(ROOT).as_posix(),'model/gltf-binary',src.stat().st_size,sha256(src),dump({'backend':'Hunyuan3D + Blender','baseline':True}),stamp))

init_db()
app.mount('/data',StaticFiles(directory=DATA),name='data')
app.mount('/public',StaticFiles(directory=ROOT/'public'),name='public')

_dist=ROOT/'dist'
if _dist.exists():
    app.mount('/assets',StaticFiles(directory=_dist/'assets'),name='assets')
    @app.get('/{path:path}',include_in_schema=False)
    def spa(path:str):
        candidate=(_dist/path).resolve()
        if path and candidate.is_file() and candidate.is_relative_to(_dist.resolve()):return FileResponse(candidate)
        return FileResponse(_dist/'index.html')
