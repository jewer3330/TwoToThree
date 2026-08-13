from __future__ import annotations
import asyncio, json, mimetypes, os, random, shutil, threading
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
import psutil
from fastapi import FastAPI,File,HTTPException,Query,Request,UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse,StreamingResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image,UnidentifiedImageError
from pydantic import BaseModel,Field
from .core import DATA,ROOT,db,dump,init_db,load,now,project_dir,rowdict,sha256,slugify,uid
from .worker import STAGES,launch
from .backends import capabilities,refine_blender,CancelledError

@asynccontextmanager
async def lifespan(_:FastAPI):
    init_db();seed_demo();yield

app=FastAPI(title='2D→3D Studio API',version='1.0.0',docs_url='/api/docs',openapi_url='/api/openapi.json',lifespan=lifespan)
app.add_middleware(CORSMiddleware,allow_origins=['http://localhost:5173','http://127.0.0.1:5173'],allow_methods=['*'],allow_headers=['*'])

class ProjectInput(BaseModel):
    name:str=Field(min_length=1,max_length=60);subjectType:str='character';intendedUse:str='web';quality:str='standard';segmentationRequired:bool=False;rigRequired:bool=False;preserveFeatures:str='';notes:str=''
class PatchInput(BaseModel):
    name:str|None=None;subjectType:str|None=None;intendedUse:str|None=None;quality:str|None=None;segmentationRequired:bool|None=None;rigRequired:bool|None=None;preserveFeatures:str|None=None;notes:str|None=None
class DecisionInput(BaseModel):notes:str=''
class RefinementInput(BaseModel):
    sourceVersionId:str;modules:list[str]=['geometryRepair','uvUnwrap','pbrMaterials','webOptimization','visualReview'];instructions:str='';geometryRepairStrength:str='conservative';uvStrategy:str='preserve_or_smart';uvIslandMargin:float=.03;materialTemplate:str='neutral';targetTriangleRange:list[int]=[20000,120000];textureResolution:int=2048;maxWebGlbMB:int=20
class PlanInput(BaseModel):
    primaryBackend:str='hunyuan3d';fallbackBackends:list[str]=['sf3d','triposr'];geometryQuality:str='standard';textureResolution:int=2048;targetTriangleRange:list[int]=[60000,120000];segmentationRequired:bool=False;rigRequired:bool=False;preserveBaseline:bool=True;renderViews:list[str]=['front','left-three-quarter','side','back'];limitations:list[str]=[]

def project_json(r):
    d=dict(r);stage=None
    if d['current_job_id']:
        with db() as con:
            job=con.execute('SELECT current_stage FROM jobs WHERE id=?',(d['current_job_id'],)).fetchone()
            stage=job['current_stage'] if job else None
    return {'id':d['id'],'slug':d['slug'],'name':d['name'],'subjectType':d['subject_type'],'intendedUse':d['intended_use'],'quality':d['quality'],'status':d['status'],'currentJobId':d['current_job_id'],'currentStage':stage,'passedStages':d['passed_stages'],'totalStages':d['total_stages'],'actualBackend':d['actual_backend'],'thumbnailUrl':d['thumbnail_url'],'createdAt':d['created_at'],'updatedAt':d['updated_at']}
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
    disk=psutil.disk_usage(str(ROOT));caps=capabilities();gpu_ok=False;gpu_name=None
    try:
        import subprocess
        gpu_name=subprocess.check_output(['nvidia-smi','--query-gpu=name','--format=csv,noheader'],text=True,timeout=4,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0)).strip();gpu_ok=bool(gpu_name)
    except Exception:pass
    return {'status':'healthy' if gpu_ok and caps['hunyuan3d'] and caps['blender'] else 'degraded','cpu':psutil.cpu_percent(),'memory':psutil.virtual_memory().percent,'storage':disk.percent,'gpu':{'status':'ready' if gpu_ok else 'unavailable','name':gpu_name,'queueConcurrency':1},'backends':caps,'services':{'api':'online','database':'online','worker':'local-thread'}}
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
        final=target_dir/f'{aid}{ext}';tmp.replace(final);digest=sha256(final);rel=final.relative_to(ROOT).as_posix()
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
    p=get_project(pid);settings=load(p['settings'],{});return {'primaryBackend':'hunyuan3d','fallbackBackends':['sf3d','triposr'],'geometryQuality':p['quality'],'textureResolution':4096 if p['quality']=='ultra' else 2048,'targetTriangleRange':[60000,120000],'segmentationRequired':settings.get('segmentationRequired',False),'rigRequired':settings.get('rigRequired',False),'preserveBaseline':True,'renderViews':['front','left-three-quarter','side','back'],'limitations':['单张图无法准确恢复隐藏面；背面与遮挡结构按证据置信度标记。','自动分件与骨骼不作为 MVP 完成条件。','外部 GPU 后端不可用时任务会记录真实降级路线。']}
@app.get('/api/projects/{pid}/plan')
def get_plan(pid:str):return make_plan(pid)
@app.patch('/api/projects/{pid}/plan')
def update_plan(pid:str,body:PlanInput):
    get_project(pid);path=project_dir(pid)/'plan-draft.json';path.write_text(json.dumps(body.model_dump(),ensure_ascii=False,indent=2),encoding='utf-8');return body.model_dump()
@app.post('/api/projects/{pid}/jobs',status_code=201)
def create_job(pid:str):
    p=get_project(pid)
    with db() as con:v=con.execute('SELECT * FROM validations WHERE project_id=? ORDER BY created_at DESC LIMIT 1',(pid,)).fetchone()
    if not v or v['verdict'] in ('request_input','reject'):raise HTTPException(409,'素材检查存在阻断项')
    plan_path=project_dir(pid)/'plan-draft.json';config=json.loads(plan_path.read_text('utf-8')) if plan_path.exists() else make_plan(pid)
    return new_job(pid,config,1)
def new_job(pid,config,attempt):
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
    job_json(jid)
    with db() as con:con.execute('UPDATE jobs SET cancel_requested=1 WHERE id=?',(jid,))
    return job_json(jid)
@app.post('/api/jobs/{jid}/retry')
def retry(jid:str):
    old=job_json(jid)
    with db() as con:r=con.execute('SELECT config_snapshot FROM jobs WHERE id=?',(jid,)).fetchone()
    return new_job(old['projectId'],load(r['config_snapshot'],{}),old['attempt']+1)
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
    return {'id':r['id'],'projectId':r['project_id'],'number':r['number'],'label':r['label'],'status':r['status'],'model':artifact_json(art) if art else None,'createdAt':r['created_at'],'qualityReport':load(r['quality_report'],{})}
@app.get('/api/versions/{vid}')
def version(vid:str):return version_json(vid)
@app.get('/api/versions/{vid}/model')
def model(vid:str):
    v=version_json(vid)
    if not v['model']:raise HTTPException(404,'版本没有 GLB')
    return v['model']
@app.get('/api/versions/{vid}/quality-report')
def quality(vid:str):return version_json(vid)['qualityReport']
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
        result=refine_blender(ROOT/source['storage_path'],root,config_path,save_log,cancelled,ROOT/reference['storage_path'] if reference else None)
        for m in config['modules']:
            cap=REFINEMENT_MODULES[m]['capability'];states[m]='awaiting_review' if cap=='inferred' else 'passed' if cap=='automatic' else 'not_configured'
        gates=result.get('gates',{})
        if not gates.get('meshValid',False) or not gates.get('boundsSafe',False):states['geometryRepair']='failed'
        if 'uvUnwrap' in states and not gates.get('uvValid',False):states['uvUnwrap']='failed'
        if 'pbrMaterials' in states and not gates.get('pbrComplete',False):states['pbrMaterials']='failed'
        if 'webOptimization' in states and (not gates.get('triangleBudget',False) or not gates.get('sizeBudget',False) or not gates.get('glbValid',False)):states['webOptimization']='failed'
        if 'visualReview' in states and not gates.get('rendersComplete',False):states['visualReview']='failed'
        stamp=now();status='awaiting_review' if result['status']=='passed' else 'quality_failed'
        with db() as con:
            con.execute('INSERT INTO versions VALUES(?,?,?,?,?,?,?)',(out_vid,d['project_id'],number,f'v{number:03d} · Blender 自动精修','ready_for_review' if status=='awaiting_review' else 'quality_failed',dump(result),stamp));con.execute('INSERT INTO version_links VALUES(?,?,?,?,?)',(uid('vln'),d['source_version_id'],out_vid,jid,stamp))
            files=[('glb','refined.glb',root/'refined.glb','model/gltf-binary'),('quality_report','quality-report.json',root/'quality-report.json','application/json'),('config','config-snapshot.json',config_path,'application/json')]+[('texture',f'{n}.png',root/'textures'/f'{n}.png','image/png') for n in ('base-color','roughness','metallic','normal','ao')]+[('render',f'{n}.png',root/f'{n}.png','image/png') for n in ('front','left-three-quarter','side','back')]
            for kind,label,path,mime in files:
                if path.exists():con.execute('INSERT INTO refinement_artifacts VALUES(?,?,?,?,?,?,?,?,?,?,?)',(uid('rart'),jid,out_vid,kind,label,path.relative_to(ROOT).as_posix(),mime,path.stat().st_size,sha256(path),dump({'sourceVersionId':d['source_version_id']}),stamp))
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

def seed_demo():
    with db() as con:
        if con.execute('SELECT COUNT(*) FROM projects').fetchone()[0]:return
        pid='prj_0000000000000001';stamp=now();thumb='/public/yoyo-reference.png';con.execute('INSERT INTO projects(id,slug,name,subject_type,intended_use,quality,status,passed_stages,total_stages,actual_backend,thumbnail_url,settings,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(pid,'yoyo-demo','YOYO · 星空信使','character','web','high','ready_for_review',9,9,'Hunyuan3D + Blender',thumb,'{}',stamp,stamp));vid='ver_0000000000000001';jid='job_0000000000000001';con.execute('INSERT INTO versions VALUES(?,?,?,?,?,?,?)',(vid,pid,1,'v001 · 参考图投射基线','ready_for_review',dump({'scores':{'轮廓匹配':92,'比例一致性':95,'正面可信度':94,'侧面可信度':79,'背面可信度':72},'stats':{'fileSize':'16.7 MB','maxTexture':'2048 × 2048'},'differences':[{'severity':'minor','message':'背面披风厚度来自推断。'}],'approximations':[{'region':'背面','confidence':.72,'note':'参考证据有限'}]}),stamp));con.execute('INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(jid,pid,vid,'completed','{}','hunyuan3d','Hunyuan3D + Blender','2.1',42,'web_optimization',1,stamp,stamp,stamp,None,None,0));con.execute('UPDATE projects SET current_job_id=? WHERE id=?',(jid,pid));src=ROOT/'public'/'models'/'yoyo-front-projection-v1.glb';con.execute('INSERT INTO artifacts VALUES(?,?,?,?,?,?,?,?,?,?,?)',('art_0000000000000001',jid,vid,'glb','yoyo-front-projection-v1.glb',src.relative_to(ROOT).as_posix(),'model/gltf-binary',src.stat().st_size,sha256(src),dump({'backend':'Hunyuan3D + Blender','baseline':True}),stamp))

init_db()
app.mount('/data',StaticFiles(directory=DATA),name='data')
app.mount('/public',StaticFiles(directory=ROOT/'public'),name='public')
