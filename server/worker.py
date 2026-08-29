from __future__ import annotations
import json, math, struct, threading, time
from pathlib import Path
from .core import ROOT,db,dump,now,project_dir,resolve_storage,sha256,storage_path,uid
from .backends import BackendError,CancelledError,capabilities,generate_hunyuan,generate_hunyuan_multiview,generate_sf3d,generate_triposr,render_blender

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
def glb_geometry_metrics(path:Path)->dict:
    """Use robust POSITION percentiles so isolated outlier vertices cannot hide a flat mesh."""
    raw=path.read_bytes();offset=12;doc=None;binary=b''
    while offset+8<=len(raw):
        length,kind=struct.unpack_from('<II',raw,offset);payload=raw[offset+8:offset+8+length];offset+=8+length
        if kind==0x4E4F534A:doc=json.loads(payload.rstrip(b'\x00 ').decode('utf-8'))
        elif kind==0x004E4942:binary=payload
    if not doc or not binary:raise ValueError('GLB 缺少 JSON 或 BIN 数据块')
    axes=[[],[],[]];formats={5126:('f',4),5123:('H',2),5125:('I',4),5121:('B',1),5122:('h',2)}
    for mesh in doc.get('meshes',[]):
        for primitive in mesh.get('primitives',[]):
            index=primitive.get('attributes',{}).get('POSITION')
            if index is None:continue
            accessor=doc['accessors'][index];view=doc['bufferViews'][accessor['bufferView']];fmt,size=formats[accessor['componentType']]
            start=view.get('byteOffset',0)+accessor.get('byteOffset',0);stride=view.get('byteStride',size*3)
            for i in range(accessor['count']):
                xyz=struct.unpack_from('<'+fmt*3,binary,start+i*stride)
                for axis,value in enumerate(xyz):axes[axis].append(float(value))
    if not axes[0]:raise ValueError('GLB 没有 POSITION 顶点数据')
    def q(values,p):
        values.sort();index=(len(values)-1)*p;lo=math.floor(index);hi=math.ceil(index)
        return values[lo] if lo==hi else values[lo]*(hi-index)+values[hi]*(index-lo)
    robust=[q(v,.95)-q(v,.05) for v in axes];ordered=sorted(robust);ratio=ordered[0]/max(ordered[-1],1e-9)
    return {'vertexCount':len(axes[0]),'robustDimensions':{'x':robust[0],'y':robust[1],'z':robust[2]},'thinAxisRatio':ratio,'flat':ratio<.08}
def add_artifact(job,kind,label,path:Path,mime,metadata=None):
    aid=uid('art');rel=storage_path(path)
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
            job=dict(con.execute('SELECT * FROM jobs WHERE id=?',(job_id,)).fetchone());project=con.execute('SELECT subject_type FROM projects WHERE id=?',(job['project_id'],)).fetchone();con.execute("UPDATE jobs SET status='running',started_at=COALESCE(started_at,?) WHERE id=?",(now(),job_id))
        config=json.loads(job['config_snapshot']);consumption=config.get('referenceSetConsumption');by_role={};blender_references={};deferred_detail_assets=[]
        if consumption:
            if consumption.get('warnings'):raise ValueError('; '.join(consumption['warnings']))
            with db() as con:
                for role,item in consumption.get('hunyuanInputs',{}).items():
                    row=con.execute('SELECT * FROM assets WHERE id=? AND project_id=?',(item['assetId'],job['project_id'])).fetchone()
                    if not row or row['sha256']!=item['sha256']:raise ValueError(f'Reference Set 输入 {role} 缺失或哈希不一致')
                    by_role[role]=row
                for item in consumption.get('blenderOnlyAssets',[]):
                    row=con.execute('SELECT * FROM assets WHERE id=? AND project_id=?',(item['assetId'],job['project_id'])).fetchone()
                    if not row or row['sha256']!=item['sha256']:raise ValueError(f"Blender 细节资产 {item['assetId']} 缺失或哈希不一致")
                    if item['purpose']=='material' and item['viewRole'] in ('front','side','back'):blender_references[item['viewRole']]=resolve_storage(row['storage_path'])
                    else:deferred_detail_assets.append(item)
            log(job_id,f"读取锁定 Reference Set {consumption['referenceSetId']}；Hunyuan 实际输入={sorted(by_role)}；Blender 专用资产={len(consumption.get('blenderOnlyAssets',[]))}")
        else:
            with db() as con:assets=con.execute("SELECT * FROM assets WHERE project_id=? AND role IN ('front','side','back') AND active=1 ORDER BY created_at DESC",(job['project_id'],)).fetchall()
            by_role={a['role']:a for a in assets}
        asset=by_role.get('front')
        if not asset:raise ValueError('缺少正面素材')
        source_image=resolve_storage(asset['storage_path']);source_images={role:resolve_storage(a['storage_path']) for role,a in by_role.items()};version_root=project_dir(job['project_id'])/'versions'/job['version_id']
        emit(job_id,'job.status',{'status':'running'});log(job_id,'Worker 已领取任务；资源类型 gpu，单任务串行执行')
        for index,(key,label) in enumerate(STAGES):
            with db() as con:existing=con.execute('SELECT status FROM stages WHERE job_id=? AND stage_key=?',(job_id,key)).fetchone()
            if existing and existing['status']=='passed':continue
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
                    if len(source_images)>1 and backend!='hunyuan3d':errors.append(f'{backend}: multi-view unsupported; fallback refused');continue
                    if len(source_images)>1 and backend=='hunyuan3d' and not available.get('hunyuan3dMultiview'):errors.append('hunyuan3d: Hunyuan3D-2mv environment unavailable');continue
                    if not available.get(backend):errors.append(f'{backend}: environment unavailable');continue
                    try:
                        if backend=='hunyuan3d':
                            if len(source_images)>1:result=generate_hunyuan_multiview(source_images,out,job['seed'],config.get('geometryQuality','standard'),config.get('viewWeights',{'front':1.8,'side':1.0,'back':0.7}),lambda m:log(job_id,m),lambda:should_cancel(job_id),config.get('visualConditioning'),config.get('modelStyle','realistic'))
                            else:result=generate_hunyuan(source_image,out,job['seed'],config.get('geometryQuality','standard'),lambda m:log(job_id,m),lambda:should_cancel(job_id))
                        elif backend=='sf3d':result=generate_sf3d(source_image,out,config.get('textureResolution',2048),lambda m:log(job_id,m),lambda:should_cancel(job_id))
                        elif backend=='triposr':result=generate_triposr(source_image,out,lambda m:log(job_id,m),lambda:should_cancel(job_id))
                        if result:break
                    except CancelledError:raise
                    except Exception as exc:errors.append(f'{backend}: {exc}');warnings.append(f'{backend}-failed');log(job_id,f'{backend} 失败，准备降级：{exc}')
                if not result:raise BackendError('所有生成后端失败：'+'; '.join(errors))
                job['actual_backend']=result['backend'];job['model_version']=result.get('modelVersion')
                with db() as con:con.execute('UPDATE jobs SET actual_backend=?,model_version=? WHERE id=?',(job['actual_backend'],job['model_version'],job_id));con.execute('UPDATE projects SET actual_backend=? WHERE id=?',(job['actual_backend'],job['project_id']))
                add_artifact(job,'glb','baseline.glb',out,'model/gltf-binary',{**result,'preservedBaseline':True,'sourceAssetId':asset['id'],'sourceSha256':asset['sha256']})
                processed=Path(result['processedImage']) if result.get('processedImage') else None
                if processed and processed.exists():add_artifact(job,'condition-image','实际送入 Hunyuan 的裁边图',processed,'image/png',{'role':'front','backgroundRemoved':True,'foregroundCropped':True})
                for role,path_text in result.get('processedImages',{}).items():
                    path=Path(path_text)
                    if path.exists():add_artifact(job,'condition-image',f'实际送入 Hunyuan3D-2mv：{role}',path,'image/png',{'role':role,'backgroundRemoved':True,'foregroundCropped':True,'multiView':True})
                for role,variants in result.get('visualCandidates',{}).items():
                    for variant,path_text in variants.items():
                        path=Path(path_text)
                        if path.exists():add_artifact(job,'visual-condition',f'{role} · {variant}',path,'image/png',{'role':role,'variant':variant,'selected':variant==result.get('visualConditioning',{}).get('selectedMode'),'experimental':variant=='depth-cue-experimental'})
                visual_report=Path(result['visualConditioningReport']) if result.get('visualConditioningReport') else None
                if visual_report and visual_report.exists():add_artifact(job,'quality_report','三视图视觉增强报告',visual_report,'application/json',{'selectedMode':result.get('visualConditioning',{}).get('selectedMode')})
            elif key=='glb_validation':
                metrics=glb_geometry_metrics(version_root/'models'/'baseline.glb')
                log(job_id,f"稳健包围尺寸={metrics['robustDimensions']}；厚度比={metrics['thinAxisRatio']:.4f}")
                if metrics['flat'] and project['subject_type'] in ('character','hybrid'):
                    raise BackendError(f"模型厚度质量门禁未通过：thinAxisRatio={metrics['thinAxisRatio']:.4f} < 0.08。该角色模型接近薄片，禁止进入预览评审。")
                out=project_dir(job['project_id'])/'versions'/job['version_id']/'models'/'baseline.glb';info=glb_info(out);log(job_id,f"GLB 文件头通过：glTF v{info['glbVersion']}，{info['byteLength']} bytes")
            elif key=='multi_view_render':
                baseline=version_root/'models'/'baseline.glb';outdir=version_root/'renders';web_glb=version_root/'models'/'web.glb';outdir.mkdir(parents=True,exist_ok=True)
                quality=config.get('geometryQuality','standard');texture_resolution=0 if quality=='standard' else (4096 if quality=='ultra' else 2048)
                processed_dir=version_root/'models'/'multiview-conditions';references={'front':processed_dir/'condition-front.png','side':processed_dir/'condition-left.png','back':processed_dir/'condition-back.png'}
                if not references['front'].exists():references={'front':version_root/'models'/'condition-front.png'}
                for role,path in blender_references.items():references[role]=path
                if blender_references:log(job_id,f'Blender 使用已批准材质候选视图：{sorted(blender_references)}')
                if deferred_detail_assets:log(job_id,f'记录 {len(deferred_detail_assets)} 个局部/法线细节资产；当前阶段不伪装为已烘焙，将转入局部精修')
                style=config.get('stylePreset',{'id':config.get('modelStyle','realistic'),'depthScale':1.0})
                render_sources=render_blender(baseline,outdir,web_glb,lambda m:log(job_id,m),lambda:should_cancel(job_id),quality,texture_resolution,references,style)
                add_artifact(job,'glb','web.glb',web_glb,'model/gltf-binary',{'backend':job['actual_backend'],'normalizedBy':'Blender 5.2','source':'baseline.glb','quality':quality,'modelStyle':style.get('id','realistic'),'styleFeaturePrompt':style.get('featurePrompt',''),'depthScale':style.get('depthScale',1.0),'geometryResolution':{'standard':256,'high':384,'ultra':512}[quality],'textureResolution':texture_resolution or None,'faceRefinement':quality=='ultra'})
                for view,source in render_sources.items():add_artifact(job,'render',view,source,'image/png',{'view':view,'renderer':'Blender 5.2'})
                for texture in sorted((outdir/'textures').glob('*.png')):add_artifact(job,'texture',texture.name,texture,'image/png',{'resolution':texture_resolution,'projection':'multi-view','embeddedIn':'web.glb'})
            path=report(job,key,'passed',started,warnings=warnings,next_action=STAGES[index+1][0] if index+1<len(STAGES) else 'ready_for_review')
            with db() as con:con.execute("UPDATE stages SET status='passed',completed_at=?,report_path=? WHERE job_id=? AND stage_key=?",(now(),storage_path(path),job_id,key));con.execute('UPDATE projects SET passed_stages=?,updated_at=? WHERE id=?',(index+1,now(),job['project_id']))
            emit(job_id,'stage.completed',{'stage':key,'status':'passed','warnings':warnings})
            if key=='multi_view_render':
                metrics=glb_geometry_metrics(version_root/'models'/'baseline.glb')
                with db() as con:
                    con.execute("UPDATE jobs SET status='awaiting_geometry_confirmation',current_stage='geometry_confirmation' WHERE id=?",(job_id,))
                    con.execute("UPDATE projects SET status='awaiting_geometry_confirmation',updated_at=? WHERE id=?",(now(),job['project_id']))
                    con.execute("UPDATE versions SET status='awaiting_geometry_confirmation',quality_report=? WHERE id=?",(dump({'geometryMetrics':metrics}),job['version_id']))
                log(job_id,'几何生成、厚度门禁与四视图预览已通过；等待用户确认后再进入 Comment 评审')
                emit(job_id,'job.status',{'status':'awaiting_geometry_confirmation','geometryMetrics':metrics})
                return
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
    """任务入队：优先交由 gpu.scheduler 派发到在线 GPU 主机；无可用主机时本机线程执行。"""
    try:
        from .gpu import scheduler as gpu_scheduler
        with db() as con:con.execute("UPDATE jobs SET status='queued' WHERE id=?",(job_id,))
        emit(job_id,'job.status',{'status':'queued'})
        if gpu_scheduler.any_online_host():
            emit(job_id,'stage.log',{'message':f'[{now()[11:19]}] 任务已入 GPU 队列，等待调度'})
            return
    except Exception:pass
    t=threading.Thread(target=run,args=(job_id,),daemon=True,name=f'studio-{job_id}');_threads[job_id]=t;t.start()
