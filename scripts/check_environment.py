import importlib.util, json, shutil, sys
from pathlib import Path
root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root))
from studio_paths import LOCAL_ROOT
checks={
 'python':{'ok':sys.version_info>=(3,10),'value':sys.version.split()[0]},
 'fastapi':{'ok':importlib.util.find_spec('fastapi') is not None},
 'node':{'ok':shutil.which('node') is not None,'value':shutil.which('node')},
 'blender':{'ok':(LOCAL_ROOT/'Blender52/blender.exe').exists(),'value':str(LOCAL_ROOT/'Blender52/blender.exe')},
 'hunyuanWeights':{'ok':(LOCAL_ROOT/'Hunyuan3D-2.1-model').exists(),'value':str(LOCAL_ROOT/'Hunyuan3D-2.1-model')},
 'sampleGlb':{'ok':(root/'public/models/yoyo-front-projection-v1.glb').exists()},
}
print(json.dumps({'schemaVersion':1,'status':'passed' if all(v['ok'] for k,v in checks.items() if k not in ('blender','hunyuanWeights')) else 'failed','checks':checks},ensure_ascii=False,indent=2))
raise SystemExit(0 if checks['python']['ok'] and checks['fastapi']['ok'] and checks['node']['ok'] and checks['sampleGlb']['ok'] else 1)
