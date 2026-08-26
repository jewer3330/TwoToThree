from __future__ import annotations
import os, subprocess, threading, time
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

class BackendError(RuntimeError):pass
class CancelledError(RuntimeError):pass

def capabilities():
    return {
        'hunyuan3d':HUNYUAN_PY.exists() and HUNYUAN_RUNNER.exists() and HUNYUAN_MODEL.exists(),
        'hunyuan3dMultiview':HUNYUAN_PY.exists() and HUNYUAN_MV_RUNNER.exists() and HUNYUAN_MV_WEIGHTS.exists() and HUNYUAN_MV_WEIGHTS.stat().st_size==HUNYUAN_MV_EXPECTED_BYTES,
        'sf3d':SF3D_PY.exists() and (SF3D_REPO/'run.py').exists(),
        'triposr':TRIPOSR_PY.exists() and (TRIPOSR_REPO/'run.py').exists(),
        'blender':BLENDER.exists() and BLENDER_RENDERER.exists(),
        'blenderRefinement':BLENDER.exists() and BLENDER_REFINER.exists(),
        'blenderStlExport':BLENDER.exists() and BLENDER_STL_EXPORTER.exists(),
    }

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

def generate_hunyuan(image:Path,output:Path,seed:int,quality:str,log,cancelled):
    steps={'standard':20,'high':30,'ultra':40}.get(quality,20)
    resolution={'standard':256,'high':384,'ultra':512}.get(quality,256)
    processed=output.parent/'condition-front.png'
    command=[str(HUNYUAN_PY),str(HUNYUAN_RUNNER),'--image',str(image),'--model',str(HUNYUAN_MODEL),'--output',str(output),'--processed-image-output',str(processed),'--steps',str(steps),'--resolution',str(resolution),'--seed',str(seed)]
    log(f'Hunyuan3D 2.1 启动：steps={steps}, octree={resolution}, seed={seed}')
    run_process(command,ROOT,log,cancelled,timeout=2400)
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
    command=[str(HUNYUAN_PY),str(HUNYUAN_MV_RUNNER),'--model',str(HUNYUAN_MV_MODEL),'--output',str(output),'--processed-dir',str(processed),'--steps',str(steps),'--resolution',str(resolution),'--seed',str(seed)]
    for role in ('front','side','back'):command.extend([f'--{role}',str(images[role])])
    weights={role:max(0.1,min(3.0,float(view_weights.get(role,1.0)))) for role in ('front','side','back')}
    for role in ('front','side','back'):command.extend([f'--{role}-weight',str(weights[role])])
    visual=visual_conditioning or {};mode=str(visual.get('mode','auto')) if visual.get('enabled',True) else 'original';depth_blend=max(0,min(.25,float(visual.get('depthBlend',.15))));command.extend(['--visual-conditioning',mode,'--style',style,'--depth-blend',str(depth_blend)])
    log(f'Hunyuan3D-2mv 启动：views=front,side,back, weights={weights}, steps={steps}, octree={resolution}, seed={seed}, memory=cpu-load/offload')
    run_process(command,ROOT,log,cancelled,timeout=2400)
    if not output.exists():raise BackendError('Hunyuan3D-2mv 未生成 GLB')
    visual_root=processed/'visual-candidates';report_path=visual_root/'visual-conditioning-report.json';report=__import__('json').loads(report_path.read_text(encoding='utf-8')) if report_path.exists() else {};candidates={role:{name:str(visual_root/role/f'{name}.png') for name in ('original','contour','rgb_depth','depth-cue-experimental')} for role in ('front','side','back')}
    selected_images={role:report.get('views',{}).get(role,{}).get('selected',str(processed/f'condition-{"left" if role=="side" else role}.png')) for role in ('front','side','back')}
    return {'backend':'hunyuan3d-2mv','modelVersion':'tencent/Hunyuan3D-2mv','steps':steps,'resolution':resolution,'seed':seed,'views':['front','side','back'],'viewWeights':weights,'processedImages':selected_images,'visualConditioning':report,'visualConditioningReport':str(report_path),'visualCandidates':candidates}

def generate_sf3d(image:Path,output:Path,texture_resolution:int,log,cancelled):
    staging=output.parent/'sf3d-output';staging.mkdir(parents=True,exist_ok=True)
    command=[str(SF3D_PY),'run.py',str(image),'--output-dir',str(staging),'--texture-resolution',str(texture_resolution),'--remesh_option','none','--target_vertex_count','-1']
    log(f'Stable Fast 3D 启动：texture={texture_resolution}')
    run_process(command,SF3D_REPO,log,cancelled,timeout=1200)
    candidates=sorted(staging.rglob('mesh.glb'),key=lambda p:p.stat().st_mtime,reverse=True)
    if not candidates:raise BackendError('SF3D 未生成 mesh.glb')
    output.write_bytes(candidates[0].read_bytes())
    return {'backend':'sf3d','modelVersion':'stabilityai/stable-fast-3d','textureResolution':texture_resolution}

def generate_triposr(image:Path,output:Path,log,cancelled):
    staging=output.parent/'triposr-output';staging.mkdir(parents=True,exist_ok=True)
    command=[str(TRIPOSR_PY),'run.py',str(image),'--output-dir',str(staging),'--model-save-format','glb']
    log('TripoSR 启动')
    run_process(command,TRIPOSR_REPO,log,cancelled,timeout=1200)
    candidates=sorted(staging.rglob('*.glb'),key=lambda p:p.stat().st_mtime,reverse=True)
    if not candidates:raise BackendError('TripoSR 未生成 GLB')
    output.write_bytes(candidates[0].read_bytes())
    return {'backend':'triposr','modelVersion':'stabilityai/TripoSR'}

def render_blender(source:Path,output_dir:Path,web_glb:Path,log,cancelled,quality:str='standard',texture_resolution:int=0,references:dict[str,Path]|None=None,style_preset:dict|None=None):
    preset=style_preset or {};style_id=str(preset.get('id','realistic'));depth_scale=max(.35,min(1.0,float(preset.get('depthScale',1.0))))
    command=[str(BLENDER),'--background','--factory-startup','--python',str(BLENDER_RENDERER),'--','--input',str(source),'--output-dir',str(output_dir),'--web-glb',str(web_glb),'--quality',quality,'--texture-resolution',str(texture_resolution),'--style',style_id,'--depth-scale',str(depth_scale)]
    for role,path in (references or {}).items():
        if role in ('front','side','back') and path.exists():command.extend([f'--{role}',str(path)])
    log(f'Blender 5.2 后台四视图渲染启动：style={style_id}, depthScale={depth_scale:.2f}')
    run_process(command,ROOT,log,cancelled,timeout=900)
    expected={v:output_dir/f'{v}.png' for v in ('front','left-three-quarter','side','back')}
    missing=[v for v,p in expected.items() if not p.exists()]
    if missing or not web_glb.exists():raise BackendError(f'Blender 产物不完整：{missing}')
    return expected

def refine_blender(source:Path,output_dir:Path,config_path:Path,log,cancelled,reference_image:Path|None=None):
    command=[str(BLENDER),'--background','--factory-startup','--python',str(BLENDER_REFINER),'--','--input',str(source),'--output-dir',str(output_dir),'--config',str(config_path)]
    if reference_image:command.extend(['--reference-image',str(reference_image)])
    log('启动真实 Blender 后台自动精修')
    run_process(command,ROOT,log,cancelled,timeout=1800)
    report=output_dir/'quality-report.json'
    if not report.exists():raise BackendError('Blender 未生成质量报告')
    import json
    result=json.loads(report.read_text(encoding='utf-8'))
    if not (output_dir/'refined.glb').exists():raise BackendError('Blender 未生成 refined.glb')
    return result

def export_stl_blender(source:Path,output:Path,scope:str,unit:str,apply_modifiers:bool,log,target_height_mm:float|None=None):
    command=[str(BLENDER),'--background','--factory-startup','--python',str(BLENDER_STL_EXPORTER),'--','--input',str(source),'--output',str(output),'--scope',scope,'--unit',unit]
    if apply_modifiers:command.append('--apply-modifiers')
    if target_height_mm is not None:command.extend(['--target-height-mm',str(target_height_mm)])
    log(f'Blender STL 导出启动：scope={scope}, unit={unit}, applyModifiers={apply_modifiers}, targetHeightMm={target_height_mm}')
    run_process(command,ROOT,log,lambda:False,timeout=900)
    if not output.exists() or not output.stat().st_size:raise BackendError('Blender 未生成 STL 文件')
    return output
