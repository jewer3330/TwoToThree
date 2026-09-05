"""Exercise deployed authentication and print artifact APIs without starting hardware."""
import json
import os
import io
import zipfile
import httpx

base=os.environ.get('VERIFY_BASE','http://127.0.0.1:8000')
with httpx.Client(base_url=base,timeout=30) as client:
    assert client.get('/api/system/health').status_code==200
    assert client.get('/api/print/jobs').status_code==401
    login=client.post('/api/auth/login',data={'username':os.environ['SIMPLE_ADMIN_USER'],'password':os.environ['SIMPLE_ADMIN_PASSWORD']})
    assert login.status_code==303
    # The production secure session cookie is sent only over HTTPS. This diagnostic
    # connects to loopback directly and explicitly supplies the authenticated cookie.
    client.headers['Cookie']='; '.join(f'{k}={v}' for k,v in client.cookies.items())
    created=client.post('/api/print/jobs',json={'name':'release-api-acceptance'})
    assert created.status_code==201,created.text
    job=created.json()['id']
    path=f'/api/print/jobs/{job}'
    uploaded=client.post(path+'/model',files={'file':('sample.stl',b'solid sample\nendsolid sample')})
    assert uploaded.status_code==201 and uploaded.json()['id']==job
    invalid=client.post(path+'/sliced',files={'file':('bad.3mf',b'invalid')})
    assert invalid.status_code==422
    archive=io.BytesIO()
    with zipfile.ZipFile(archive,'w') as z:
        z.writestr('Metadata/plate_1.gcode','; HEADER_BLOCK_START\n'+'G1 X1 Y1\n'*30)
    sliced=client.post(path+'/sliced',files={'file':('sample.3mf',archive.getvalue())})
    assert sliced.status_code==201 and sliced.json()['sliced']['hash']
    assert client.get(path).json()['step']=='send'
    # Delete only this script's disposable, non-hardware acceptance fixture.
    assert client.delete(path).status_code==204
    print(json.dumps({'health':200,'anonymous':401,'login':303,'modelUpload':201,'invalidSliced':422,'slicedUpload':201,'fixtureCleanup':204}))
