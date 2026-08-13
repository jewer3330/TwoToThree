from __future__ import annotations
import json, struct, threading, time
from pathlib import Path
from .core import ROOT,db,dump,now,project_dir,sha256,uid
from .backends import BackendError,CancelledError,capabilities,generate_hunyuan,generate_sf3d,generate_triposr,render_blender

STAGES=[('intake','素材接收'),('analysis','主体分析'),('geometry','几何生成'),('glb_validation','GLB 检查'),('multi_view_render','Blender 标准化与四视图'),('web_optimization','Web GLB 输出')]
_threads:dict[str,threading.Thread]={}

def emit(job_id:str,event_type:str,payload:dict):
    with db() as con:con.execute('INSERT INTO events(job_id,event_type,payload,created_at) VALUES(?,?,?,?)',(job_id,event_type,dump(payload),now()))
def log(job_id:str,message:str):emit(job_id,'stage.log',{'message':f'[{now()[11:19]}] {message}'})
def glb_info(path:Path)->dict:
    with path.open('rb') as f:head=f.read(12)
    if len(head)!=12 or head[:4]!=b'glTF':raise ValueError('文件缺少 glTF 二进制文件头')
    version,length=struct.unpack('<II',head[4:]);actual=path.stat().st_size
    if version!=2:raise ValueError(f'不支持的 glTF 版本 {version}')
    if length!=actual:raise ValueError(f'GLB 声明长度 {length} 与文件长度 {actual} 不一致')
    return {'glbVersion':version,'byteLength':actual,'header':'glTF'}
def add_artifact(job,kind,label,path:Path,mime,metadata=None):
    aid=uid('art');rel=path.relative_to(ROOT).as_posix()
    with db() as con:con.execute('INSERT INTO artifacts VALUES(?,?,?,?,?,?,?,?,?,?,?)',(aid,job['id'],job['version_id'],kind,label,rel,mime,path.stat().st_size,sha256(path),dump(metadata or {}),now()))
    emit(job['id'],'stage.output',{'artifactId':aid,'type':kind,'label':label})
def report(job,stage,status,started,warnings=None,error=None,next_action=None):
    folder=project_dir(job['project_id'])/'versions'/job['version_id']/'reports';folder.mkdir(parents=True,exist_ok=True)
    payload={'schemaVersion':1,'stage':stage,'status':status,'startedAt':started,'completedAt':now(),'inputs':[],'outputs':[],'metrics':{},'warnings':warnings or [],'error':error,'nextAction':next_action}
    path=folder/f'{stage}.json';path.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8');return path
def should_cancel(job_id):
    with db() as con:return bool(con.execute('SELECT cancel_requested FROM jobs WHERE id=?',(job_id,)).fetchone()[0])
def run(job_id:str):
    try:
        with db() as con:
            job=dict(con.execute('SELECT * FROM jobs WHERE id=?',(job_id,)).fetchone());asset=con.execute("SELECT * FROM assets WHERE project_id=? AND role='front' AND active=1 ORDER BY created_at DESC LIMIT 1",(job['project_id'],)).fetchone();con.execute("UPDATE jobs SET status='running',started_at=? WHERE id=?",(now(),job_id))
        if not asset:raise ValueError('缺少活动正面素材')
        source_image=ROOT/asset['storage_path'];config=json.loads(job['config_snapshot']);version_root=project_dir(job['project_id'])/'versions'/job['version_id']
        emit(job_id,'job.status',{'status':'running'});log(job_id,'Worker 已领取任务；资源类型 gpu，单任务串行执行')
        for index,(key,label) in enumerate(STAGES):
            if should_cancel(job_id):
                with db() as con:con.execute("UPDATE jobs SET status='cancelled',completed_at=? WHERE id=?",(now(),job_id));con.execute("UPDATE projects SET status='cancelled',updated_at=? WHERE id=?",(now(),job['project_id']))
                emit(job_id,'job.status',{'status':'cancelled'});log(job_id,'收到取消信号；保留所有已生成产物');return
            started=now();
            with db() as con:con.execute("UPDATE stages SET status='running',started_at=? WHERE job_id=? AND stage_key=?",(started,job_id,key));con.execute('UPDATE jobs SET current_stage=? WHERE id=?',(key,job_id));con.execute('UPDATE projects SET status=?,updated_at=? WHERE id=?',(state_for(key),now(),job['project_id']))
            emit(job_id,'stage.started',{'stage':key,'label':label});log(job_id,f'开始{label}')
            time.sleep(.22)
            warnings=[]
            if key=='geometry':
                out=version_root/'models'/'baseline.glb';out.parent.mkdir(parents=True,exist_ok=True)
                requested=[config.get('primaryBackend','hunyuan3d'),*config.get('fallbackBackends',['sf3d','triposr'])];available=capabilities();errors=[];result=None
                for backend in dict.fromkeys(requested):
                    if not available.get(backend):errors.append(f'{backend}: environment unavailable');continue
                    try:
                        if backend=='hunyuan3d':result=generate_hunyuan(source_image,out,job['seed'],config.get('geometryQuality','standard'),lambda m:log(job_id,m),lambda:should_cancel(job_id))
                        elif backend=='sf3d':result=generate_sf3d(source_image,out,config.get('textureResolution',2048),lambda m:log(job_id,m),lambda:should_cancel(job_id))
                        elif backend=='triposr':result=generate_triposr(source_image,out,lambda m:log(job_id,m),lambda:should_cancel(job_id))
                        if result:break
                    except CancelledError:raise
                    except Exception as exc:errors.append(f'{backend}: {exc}');warnings.append(f'{backend}-failed');log(job_id,f'{backend} 失败，准备降级：{exc}')
                if not result:raise BackendError('所有生成后端失败：'+'; '.join(errors))
                job['actual_backend']=result['backend'];job['model_version']=result.get('modelVersion')
                with db() as con:con.execute('UPDATE jobs SET actual_backend=?,model_version=? WHERE id=?',(job['actual_backend'],job['model_version'],job_id));con.execute('UPDATE projects SET actual_backend=? WHERE id=?',(job['actual_backend'],job['project_id']))
                add_artifact(job,'glb','baseline.glb',out,'model/gltf-binary',{**result,'preservedBaseline':True,'sourceAssetId':asset['id'],'sourceSha256':asset['sha256']})
            elif key=='glb_validation':
                out=project_dir(job['project_id'])/'versions'/job['version_id']/'models'/'baseline.glb';info=glb_info(out);log(job_id,f"GLB 文件头通过：glTF v{info['glbVersion']}，{info['byteLength']} bytes")
            elif key=='multi_view_render':
                baseline=version_root/'models'/'baseline.glb';outdir=version_root/'renders';web_glb=version_root/'models'/'web.glb';outdir.mkdir(parents=True,exist_ok=True)
                render_sources=render_blender(baseline,outdir,web_glb,lambda m:log(job_id,m),lambda:should_cancel(job_id))
                add_artifact(job,'glb','web.glb',web_glb,'model/gltf-binary',{'backend':job['actual_backend'],'normalizedBy':'Blender 5.2','source':'baseline.glb'})
                for view,source in render_sources.items():add_artifact(job,'render',view,source,'image/png',{'view':view,'renderer':'Blender 5.2'})
            path=report(job,key,'passed',started,warnings=warnings,next_action=STAGES[index+1][0] if index+1<len(STAGES) else 'ready_for_review')
            with db() as con:con.execute("UPDATE stages SET status='passed',completed_at=?,report_path=? WHERE job_id=? AND stage_key=?",(now(),path.relative_to(ROOT).as_posix(),job_id,key));con.execute('UPDATE projects SET passed_stages=?,updated_at=? WHERE id=?',(index+1,now(),job['project_id']))
            emit(job_id,'stage.completed',{'stage':key,'status':'passed','warnings':warnings})
        web_glb=version_root/'models'/'web.glb';quality={'scores':{'轮廓匹配':0,'比例一致性':0,'正面可信度':0,'侧面可信度':0,'背面可信度':0},'stats':{'fileSize':f'{web_glb.stat().st_size/1048576:.2f} MB' if web_glb.exists() else 'unknown','backend':job['actual_backend']},'differences':[{'severity':'info','message':'自动视觉评分尚未接入；请依据四视图和交互模型人工验收。'}],'approximations':[{'region':'未提供视角覆盖的隐藏区域','confidence':0.5,'note':'单图生成结果需要人工复核'}]}
        with db() as con:con.execute("UPDATE jobs SET status='completed',completed_at=? WHERE id=?",(now(),job_id));con.execute("UPDATE projects SET status='ready_for_review',passed_stages=?,total_stages=?,updated_at=? WHERE id=?",(len(STAGES),len(STAGES),now(),job['project_id']));con.execute("UPDATE versions SET status='ready_for_review',quality_report=? WHERE id=?",(dump(quality),job['version_id']))
        log(job_id,'全部阶段完成；模型已进入人工验收');emit(job_id,'job.completed',{'status':'completed','versionId':job['version_id']})
    except CancelledError as exc:
        with db() as con:con.execute("UPDATE jobs SET status='cancelled',completed_at=? WHERE id=?",(now(),job_id));con.execute("UPDATE projects SET status='cancelled',updated_at=? WHERE current_job_id=?",(now(),job_id))
        log(job_id,str(exc));emit(job_id,'job.status',{'status':'cancelled'})
    except Exception as exc:
        with db() as con:con.execute("UPDATE jobs SET status='failed',error_code='WORKER_ERROR',error_summary=?,completed_at=? WHERE id=?",(str(exc),now(),job_id));con.execute("UPDATE projects SET status='failed',updated_at=? WHERE current_job_id=?",(now(),job_id))
        log(job_id,f'任务失败：{exc}');emit(job_id,'stage.failed',{'error':str(exc)})
def state_for(stage):return {'intake':'queued','analysis':'generating_geometry','geometry':'generating_geometry','glb_validation':'validating_glb','multi_view_render':'rendering_review','visual_review':'rendering_review','manual_refine':'awaiting_manual_refine','materials':'processing_materials','web_optimization':'optimizing_web'}.get(stage,'queued')
def launch(job_id):
    t=threading.Thread(target=run,args=(job_id,),daemon=True,name=f'studio-{job_id}');_threads[job_id]=t;t.start()
