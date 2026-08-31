from __future__ import annotations
import json, shutil, subprocess, threading, time, urllib.error, urllib.request, uuid
from pathlib import Path
from typing import Callable
from PIL import Image,ImageDraw
import psutil
from .core import ROOT
from .backends import BackendError,CancelledError
from studio_paths import LOCAL_ROOT

COMFY=LOCAL_ROOT/'ComfyUI';COMFY_PY=COMFY/'.venv-gpu/Scripts/python.exe';LAUNCHER=ROOT/'scripts/run_comfy_gpu.py';SERVER='http://127.0.0.1:8188';CHECKPOINT='sd-v1-5-inpainting.ckpt'
_server_process:subprocess.Popen|None=None
_server_lock=threading.Lock()
REGION_BOXES={
 'head':(.24,.12,.76,.53),'face':(.30,.28,.70,.51),'hair':(.20,.08,.80,.38),'neck_collar':(.25,.43,.75,.62),
 'torso_garment':(.18,.48,.82,.78),'left_shoulder_sleeve':(.05,.45,.43,.72),'right_shoulder_sleeve':(.57,.45,.95,.72),
 'arms_hands':(.03,.48,.97,.78),'lower_body':(.18,.70,.82,.99),'back_structure':(.15,.28,.85,.78),'accessories':(.10,.30,.90,.88),
}
PROMPTS={
 'face':'preserve the exact same character identity, face proportions, eyes, nose, mouth, hairstyle and illustration colors; restore coherent facial detail only inside the mask',
 'neck_collar':'preserve identity and garment design; clarify the neck and collar layers, seams, thickness and overlap only inside the mask',
 'left_shoulder_sleeve':'preserve the exact costume; clarify left shoulder and sleeve layers, silhouette and attachment only inside the mask',
 'right_shoulder_sleeve':'preserve the exact costume; clarify right shoulder and sleeve layers, silhouette and attachment only inside the mask',
}
NEGATIVE='changed identity, changed silhouette, changed costume color, extra limb, extra eye, missing feature, asymmetry, photorealistic, blurry, text, watermark, edits outside mask'

def _request(path:str,payload:dict|None=None,timeout=30):
 data=json.dumps(payload).encode() if payload is not None else None;req=urllib.request.Request(SERVER+path,data=data,headers={'Content-Type':'application/json'})
 with urllib.request.urlopen(req,timeout=timeout) as response:return json.load(response)
def healthy()->bool:
 try:_request('/system_stats',timeout=2);return True
 except Exception:return False
def ensure_server(log:Callable[[str],None],cancelled:Callable[[],bool]):
 global _server_process
 if healthy():return
 if not (COMFY_PY.exists() and LAUNCHER.exists() and (COMFY/'models/checkpoints'/CHECKPOINT).exists()):raise BackendError('ComfyUI、本地 GPU Python 或 inpainting checkpoint 未安装完整')
 with _server_lock:
  if not healthy():
   logs=ROOT/'logs';logs.mkdir(exist_ok=True);out=(logs/'comfy-detail.out.log').open('a',encoding='utf-8');err=(logs/'comfy-detail.err.log').open('a',encoding='utf-8')
   _server_process=subprocess.Popen([str(COMFY_PY),str(LAUNCHER),'--listen','127.0.0.1','--port','8188','--lowvram'],cwd=COMFY,stdout=out,stderr=err,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
   log('按需启动 ComfyUI Local API（lowvram）')
 deadline=time.monotonic()+150
 while time.monotonic()<deadline:
  if cancelled():raise CancelledError('细节生成已取消')
  if healthy():log('ComfyUI Local API 已就绪');return
  if _server_process and _server_process.poll() is not None:raise BackendError('ComfyUI 启动失败，请查看 logs/comfy-detail.err.log')
  time.sleep(2)
 raise BackendError('ComfyUI 在 150 秒内未就绪')

def stop_server(log:Callable[[str],None]|None=None):
 global _server_process
 try:
  if healthy():_request('/free',{'unload_models':True,'free_memory':True},timeout=10)
 except Exception:pass
 launcher=str(LAUNCHER.resolve()).lower();targets=[]
 for process in psutil.process_iter(['pid','cmdline']):
  try:
   command=[str(x).lower() for x in (process.info.get('cmdline') or [])]
   if any(Path(x).resolve().as_posix().lower()==Path(launcher).resolve().as_posix().lower() for x in command if x.endswith('.py')):targets.append(process)
  except (psutil.NoSuchProcess,psutil.AccessDenied,OSError):continue
 for process in targets:
  try:
   children=process.children(recursive=True)
   process.terminate()
   for child in children:child.terminate()
   _,alive=psutil.wait_procs([process,*children],timeout=8)
   for item in alive:item.kill()
  except (psutil.NoSuchProcess,psutil.AccessDenied):pass
 _server_process=None
 if log:log('ComfyUI 已卸载模型并关闭，GPU 显存已释放给 Hunyuan/Blender')

def prepare_mask(source:Path,region_key:str,target:Path)->dict:
 image=Image.open(source).convert('RGB');w,h=image.size;box=REGION_BOXES[region_key];xy=(int(box[0]*w),int(box[1]*h),int(box[2]*w),int(box[3]*h));mask=Image.new('RGB',(w,h),'white');draw=ImageDraw.Draw(mask);radius=max(8,int(min(w,h)*.02));draw.rounded_rectangle(xy,radius=radius,fill='black');target.parent.mkdir(parents=True,exist_ok=True);mask.save(target)
 return {'relativeBox':box,'pixelBox':xy,'width':w,'height':h,'method':'rules-v1-relative-box'}

def generate(source:Path,region_key:str,view_role:str,output:Path,seed:int,denoise:float,log,cancelled)->dict:
 ensure_server(log,cancelled);token=uuid.uuid4().hex[:8];source_name=f'detail-source-{token}.png';mask_name=f'detail-mask-{region_key}-{view_role}-{token}.png';source_path=COMFY/'input'/source_name;mask_path=COMFY/'input'/mask_name;source_path.parent.mkdir(parents=True,exist_ok=True);Image.open(source).convert('RGB').save(source_path);mask=prepare_mask(source,region_key,mask_path)
 positive=PROMPTS.get(region_key,f'preserve the exact same character and costume; add coherent {region_key} detail only inside the mask')
 workflow={
  '1':{'class_type':'CheckpointLoaderSimple','inputs':{'ckpt_name':CHECKPOINT}},'2':{'class_type':'LoadImage','inputs':{'image':source_name}},'9':{'class_type':'LoadImageMask','inputs':{'image':mask_name,'channel':'red'}},
  '3':{'class_type':'CLIPTextEncode','inputs':{'text':positive,'clip':['1',1]}},'4':{'class_type':'CLIPTextEncode','inputs':{'text':NEGATIVE,'clip':['1',1]}},
  '5':{'class_type':'VAEEncode','inputs':{'pixels':['2',0],'vae':['1',2]}},'10':{'class_type':'SetLatentNoiseMask','inputs':{'samples':['5',0],'mask':['9',0]}},
  '6':{'class_type':'KSampler','inputs':{'seed':seed,'steps':24,'cfg':7.0,'sampler_name':'dpmpp_2m','scheduler':'karras','denoise':denoise,'model':['1',0],'positive':['3',0],'negative':['4',0],'latent_image':['10',0]}},
  '7':{'class_type':'VAEDecode','inputs':{'samples':['6',0],'vae':['1',2]}},'8':{'class_type':'SaveImage','inputs':{'filename_prefix':f'detail_candidates/{region_key}-{view_role}','images':['7',0]}},
 }
 queued=_request('/prompt',{'prompt':workflow,'client_id':uuid.uuid4().hex});prompt_id=queued['prompt_id'];deadline=time.monotonic()+1200
 while time.monotonic()<deadline:
  if cancelled():
   try:_request('/interrupt',{})
   except Exception:pass
   raise CancelledError('细节生成已取消')
  history=_request(f'/history/{prompt_id}')
  if prompt_id in history:
   record=history[prompt_id]
   if record.get('status',{}).get('status_str')=='error':raise BackendError('ComfyUI 工作流失败：'+json.dumps(record.get('status'),ensure_ascii=False)[-1500:])
   images=record.get('outputs',{}).get('8',{}).get('images',[])
   if images:
    item=images[0];generated=COMFY/'output'/item.get('subfolder','')/item['filename'];output.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(generated,output);validate_candidate(output,mask)
    return {'provider':'comfyui_local','model':'stable-diffusion-v1-5-inpainting','workflowVersion':'detail-regions-v1','promptId':prompt_id,'seed':seed,'denoise':denoise,'steps':24,'cfg':7.0,'mask':mask,'positivePrompt':positive,'negativePrompt':NEGATIVE}
  time.sleep(2)
 raise BackendError('ComfyUI 候选生成超时')

def validate_candidate(path:Path,mask:dict):
 image=Image.open(path).convert('RGB');x1,y1,x2,y2=mask['pixelBox'];crop=image.crop((x1,y1,x2,y2));pixels=list(crop.resize((64,64)).getdata());means=[sum(p[i] for p in pixels)/len(pixels) for i in range(3)];variance=sum(sum((p[i]-means[i])**2 for i in range(3)) for p in pixels)/(len(pixels)*3);channel_spread=max(means)-min(means)
 if variance<90 or (variance<260 and channel_spread<8):raise BackendError(f'候选质量门禁失败：蒙版区域疑似空白或灰块（variance={variance:.1f}, channelSpread={channel_spread:.1f}）')
