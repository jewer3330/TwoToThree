"""Run a named acceptance job through real model upload, Blender and 3MF export."""
import json
import os
import sys
from pathlib import Path
import httpx

with httpx.Client(base_url=os.environ.get('VERIFY_BASE','http://127.0.0.1:8000'),timeout=650) as client:
    response=client.post('/api/auth/login',data={'username':os.environ['SIMPLE_ADMIN_USER'],'password':os.environ['SIMPLE_ADMIN_PASSWORD']})
    assert response.status_code==303
    client.headers['Cookie']='; '.join(f'{k}={v}' for k,v in client.cookies.items())
    job=client.post('/api/print/jobs',json={'name':'production-real-print-acceptance'}).json()
    path='/api/print/jobs/'+job['id']
    print(json.dumps({'job':job['id']}),flush=True)
    with Path(sys.argv[1]).open('rb') as model:
        response=client.post(path+'/model',files={'file':('model.glb',model)})
    response.raise_for_status()
    response=client.post(path+'/split',json={'targetHeightMm':20,'maxParts':12})
    response.raise_for_status()
    job=response.json()
    print(json.dumps({'split':job['split']},ensure_ascii=False),flush=True)
    assignments={Path(p['stl']).name:'#FDD835' for p in job['split']['parts']}
    client.post(path+'/color',json={'assignments':assignments}).raise_for_status()
    response=client.post(path+'/export3mf',json={'addBase':False})
    response.raise_for_status()
    print(json.dumps({'export':response.json()},ensure_ascii=False),flush=True)
