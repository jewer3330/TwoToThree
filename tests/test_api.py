import time
import shutil
from io import BytesIO
from PIL import Image
from fastapi.testclient import TestClient
from server.main import app

def image_bytes(size=(1024,1024)):
    out=BytesIO();Image.new('RGB',size,(42,70,100)).save(out,'PNG');return out.getvalue()

def test_project_validation_and_job_contract(monkeypatch,tmp_path):
    import server.worker as worker
    import server.main as main
    sample=worker.ROOT/'public/models/yoyo-sf3d.glb'
    def fake_generate(image,output,seed,quality,log,cancelled):
        output.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(sample,output);return {'backend':'hunyuan3d','modelVersion':'test'}
    def fake_render(source,output_dir,web_glb,log,cancelled):
        output_dir.mkdir(parents=True,exist_ok=True);shutil.copy2(source,web_glb);result={}
        for name in ('front','left-three-quarter','side','back'):
            path=output_dir/f'{name}.png';path.write_bytes(image_bytes((32,32)));result[name]=path
        return result
    monkeypatch.setattr(worker,'capabilities',lambda:{'hunyuan3d':True,'sf3d':True,'triposr':True,'blender':True})
    monkeypatch.setattr(worker,'generate_hunyuan',fake_generate);monkeypatch.setattr(worker,'render_blender',fake_render)
    def fake_refine(source,output_dir,config_path,log,cancelled,reference_image=None):
        output_dir.mkdir(parents=True,exist_ok=True);shutil.copy2(source,output_dir/'refined.glb');(output_dir/'textures').mkdir()
        for name in ('base-color','roughness','metallic','normal','ao'):(output_dir/'textures'/f'{name}.png').write_bytes(image_bytes((4,4)))
        for name in ('front','left-three-quarter','side','back'):(output_dir/f'{name}.png').write_bytes(image_bytes((4,4)))
        report={'status':'passed','blenderVersion':'test','gates':{'glbValid':True,'meshValid':True,'triangleBudget':True,'uvValid':True,'pbrComplete':True,'sizeBudget':True,'boundsSafe':True,'rendersComplete':True}};(output_dir/'quality-report.json').write_text(__import__('json').dumps(report),encoding='utf-8');return report
    monkeypatch.setattr(main,'capabilities',lambda:{'blenderRefinement':True});monkeypatch.setattr(main,'refine_blender',fake_refine)
    with TestClient(app) as client:
        created=client.post('/api/projects',json={'name':'API contract test','subjectType':'character','intendedUse':'web','quality':'standard'})
        assert created.status_code==201
        pid=created.json()['id']
        upload=client.post(f'/api/projects/{pid}/assets?role=front',files={'file':('front.png',image_bytes(),'image/png')})
        assert upload.status_code==201
        assert upload.json()['sha256']
        validation=client.post(f'/api/projects/{pid}/validate')
        assert validation.status_code==200
        assert validation.json()['verdict']=='conditional'
        assert client.post(f'/api/projects/{pid}/validation/accept-risks').status_code==200
        job=client.post(f'/api/projects/{pid}/jobs')
        assert job.status_code==201
        jid=job.json()['id']
        for _ in range(80):
            snapshot=client.get(f'/api/jobs/{jid}').json()
            if snapshot['status'] in {'awaiting_geometry_confirmation','failed'}:break
            time.sleep(.1)
        assert snapshot['status']=='awaiting_geometry_confirmation'
        assert not any(a['type']=='render' for a in snapshot['artifacts'])
        assert client.post(f'/api/jobs/{jid}/confirm-geometry').status_code==200
        for _ in range(80):
            snapshot=client.get(f'/api/jobs/{jid}').json()
            if snapshot['status'] in {'completed','failed'}:break
            time.sleep(.1)
        assert snapshot['status']=='completed'
        assert client.post(f'/api/jobs/{jid}/confirm-geometry').status_code==409
        assert len(snapshot['stages'])==6
        assert any(a['mimeType']=='model/gltf-binary' for a in snapshot['artifacts'])
        version=client.get(f'/api/projects/{pid}/versions').json()[0]
        assert client.post(f"/api/versions/{version['id']}/accept",json={'notes':''}).status_code==200
        refinement=client.post('/api/refinement/jobs',json={'sourceVersionId':version['id'],'modules':['geometryRepair','webOptimization','visualReview'],'instructions':'修正轮廓'})
        assert refinement.status_code==201
        for _ in range(40):
            ref=client.get(f"/api/refinement/jobs/{refinement.json()['id']}").json()
            if ref['status'] not in ('queued','running'):break
            time.sleep(.05)
        assert ref['moduleStates']['webOptimization']=='passed'
        assert ref['moduleStates']['geometryRepair']=='passed'
        assert ref['status']=='awaiting_review'
        assert ref['outputVersionId']!=version['id']
        assert any(a['label']=='quality-report.json' for a in ref['artifacts'])
        assert client.post(f"/api/versions/{ref['outputVersionId']}/accept",json={'notes':''}).status_code==200
        chained=client.post('/api/refinement/jobs',json={'sourceVersionId':ref['outputVersionId'],'modules':['geometryRepair','webOptimization']})
        assert chained.status_code==201
        for _ in range(40):
            chained_ref=client.get(f"/api/refinement/jobs/{chained.json()['id']}").json()
            if chained_ref['status'] not in ('queued','running'):break
            time.sleep(.05)
        assert chained_ref['status']=='awaiting_review'
        assert chained_ref['outputVersionId']!=ref['outputVersionId']

def test_rejects_fake_image():
    with TestClient(app) as client:
        pid=client.post('/api/projects',json={'name':'Bad upload','subjectType':'object','intendedUse':'web','quality':'standard'}).json()['id']
        response=client.post(f'/api/projects/{pid}/assets?role=front',files={'file':('fake.png',b'not an image','image/png')})
        assert response.status_code==415

def test_resolution_thresholds():
    with TestClient(app) as client:
        for size,expected_status,expected_verdict in [((255,512),'fail','request_input'),((409,512),'warning','conditional'),((1024,1024),'pass','conditional')]:
            pid=client.post('/api/projects',json={'name':f'Resolution {size[0]}','subjectType':'object','intendedUse':'web','quality':'standard'}).json()['id']
            assert client.post(f'/api/projects/{pid}/assets?role=front',files={'file':('front.png',image_bytes(size),'image/png')}).status_code==201
            result=client.post(f'/api/projects/{pid}/validate').json()
            resolution=next(c for c in result['checks'] if c['code']=='resolution')
            assert resolution['status']==expected_status
            assert result['verdict']==expected_verdict

def test_comment_reference_revision_contract(monkeypatch):
    import server.main as main
    from server.core import db,dump,now,uid
    with TestClient(app) as client:
        pid=client.post('/api/projects',json={'name':'Comment revision contract','subjectType':'character','intendedUse':'web','quality':'standard'}).json()['id']
        assert client.post(f'/api/projects/{pid}/assets?role=front',files={'file':('front.png',image_bytes(),'image/png')}).status_code==201
        vid=uid('ver')
        with db() as con:con.execute('INSERT INTO versions VALUES(?,?,?,?,?,?,?)',(vid,pid,1,'source v001','completed',dump({}),now()))
        first=client.post(f'/api/versions/{vid}/comments',json={'title':'双眼向前突出','description':'眼球不得明显超出眼睑轮廓','category':'identity','severity':'important','recommendedRoute':'reference_regeneration','cameraSnapshot':{'position':[0,2,7]}})
        second=client.post(f'/api/versions/{vid}/comments',json={'title':'左袖口穿插','description':'袖口与手腕相交','category':'intersection','severity':'normal','recommendedRoute':'blender_automatic'})
        assert first.status_code==201 and second.status_code==201
        cid=first.json()['id'];other=second.json()['id']
        assert first.json()['number']!=second.json()['number']
        replied=client.post(f'/api/comments/{cid}/replies',json={'body':'补充侧面图后再重生成'})
        assert replied.status_code==201 and len(replied.json()['replies'])==1
        assert client.post(f'/api/comments/{cid}/close').json()['status']=='closed'
        assert client.post(f'/api/comments/{cid}/reopen').json()['status']=='open'
        plan=client.post('/api/revisions/plan',json={'sourceVersionId':vid,'commentIds':[cid,other]}).json()
        assert plan['canCreate'] is True and plan['excludedCommentIds']==[other]
        monkeypatch.setattr(main,'capabilities',lambda:{'hunyuan3d':False,'blenderRefinement':False})
        created=client.post('/api/revisions',json={'sourceVersionId':vid,'commentIds':[cid,other],'config':{}})
        assert created.status_code==201
        rid=created.json()['id']
        for _ in range(30):
            revision=client.get(f'/api/revisions/{rid}').json()
            if revision['status']=='failed':break
            time.sleep(.02)
        assert revision['status']=='failed'
        assert revision['outputVersionId'] is None
        assert revision['referenceSet']['status']=='locked'
        assert client.get(f'/api/comments/{cid}').json()['status']=='open'
        assert client.get(f'/api/comments/{other}').json()['status']=='open'
def test_delete_project_removes_record_and_files():
    import server.main as main
    with TestClient(app) as client:
        created=client.post('/api/projects',json={'name':'Delete me','subjectType':'object','intendedUse':'web','quality':'standard'})
        assert created.status_code==201
        pid=created.json()['id']
        directory=main.project_dir(pid)
        assert directory.exists()
        deleted=client.delete(f'/api/projects/{pid}')
        assert deleted.status_code==204
        assert client.get(f'/api/projects/{pid}').status_code==404
        assert not directory.exists()
