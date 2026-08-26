import time
import shutil
import pytest
from io import BytesIO
from PIL import Image
from fastapi.testclient import TestClient
from server.main import app


@pytest.fixture(autouse=True)
def remove_projects_created_by_test():
    """Keep API tests from leaving projects and their files in the local studio."""
    from server.core import db

    with db() as con:
        project_ids_before = {row['id'] for row in con.execute('SELECT id FROM projects')}

    try:
        yield
    finally:
        with db() as con:
            created_ids = [row['id'] for row in con.execute('SELECT id FROM projects') if row['id'] not in project_ids_before]
        with TestClient(app) as client:
            for project_id in created_ids:
                response = client.delete(f'/api/projects/{project_id}')
                assert response.status_code in {204, 404}

def image_bytes(size=(1024,1024)):
    out=BytesIO();Image.new('RGB',size,(42,70,100)).save(out,'PNG');return out.getvalue()

def test_project_validation_and_job_contract(monkeypatch,tmp_path):
    import server.worker as worker
    import server.main as main
    sample=worker.ROOT/'public/models/yoyo-sf3d.glb'
    def fake_generate(image,output,seed,quality,log,cancelled):
        output.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(sample,output);return {'backend':'hunyuan3d','modelVersion':'test'}
    def fake_render(source,output_dir,web_glb,log,cancelled,*args,**kwargs):
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
        report={'status':'passed','blenderVersion':'test','gates':{'glbValid':True,'meshValid':True,'triangleBudget':True,'uvValid':True,'pbrComplete':True,'sizeBudget':True,'boundsSafe':True,'volumeSafe':True,'robustThicknessSafe':True,'sideSilhouetteSafe':True,'rendersComplete':True}};(output_dir/'quality-report.json').write_text(__import__('json').dumps(report),encoding='utf-8');return report
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
        assert any(a['type']=='render' for a in snapshot['artifacts'])
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

def test_model_style_preset_is_persisted_and_applied_to_plan():
    with TestClient(app) as client:
        presets=client.get('/api/style-presets')
        assert presets.status_code==200
        assert {item['id'] for item in presets.json()}=={'realistic','cartoon','chibi'}
        created=client.post('/api/projects',json={'name':'Chibi style contract','subjectType':'character','intendedUse':'web','quality':'standard','modelStyle':'chibi','visualConditioningMode':'contour'})
        assert created.status_code==201
        pid=created.json()['id']
        assert created.json()['modelStyle']=='chibi'
        assert created.json()['visualConditioningMode']=='contour'
        plan=client.get(f'/api/projects/{pid}/plan')
        assert plan.status_code==200
        payload=plan.json()
        assert payload['modelStyle']=='chibi'
        assert payload['stylePreset']['depthScale']==.62
        assert payload['viewWeights']=={'front':1.2,'side':2.2,'back':1.0}
        assert payload['visualConditioning']=={'enabled':True,'mode':'contour','depthBlend':.15,'exportExperimentalDepth':True}
        assert '扁平毛绒玩具' in payload['stylePreset']['featurePrompt']

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

def test_version_can_be_marked_base_and_deleted_when_unreferenced():
    from server.core import db,dump,now,uid
    with TestClient(app) as client:
        pid=client.post('/api/projects',json={'name':'Version actions','subjectType':'object','intendedUse':'web','quality':'standard'}).json()['id']
        first,second=uid('ver'),uid('ver')
        with db() as con:
            con.execute('INSERT INTO versions VALUES(?,?,?,?,?,?,?)',(first,pid,1,'v001','completed',dump({}),now()))
            con.execute('INSERT INTO versions VALUES(?,?,?,?,?,?,?)',(second,pid,2,'v002','completed',dump({}),now()))
        base=client.post(f'/api/versions/{first}/set-base')
        assert base.status_code==200 and base.json()['isBase'] is True
        assert client.delete(f'/api/versions/{first}').status_code==409
        assert client.delete(f'/api/versions/{second}').status_code==204
        assert client.get(f'/api/versions/{second}').status_code==404
        assert client.get(f'/api/projects/{pid}/versions').json()==[base.json()]

def test_detail_plan_confirmation_and_candidate_gate(monkeypatch):
    import server.main as main
    from server.core import db
    def fake_detail(source,region_key,view_role,output,seed,denoise,log,cancelled):
        output.parent.mkdir(parents=True,exist_ok=True);output.write_bytes(image_bytes((64,64)));return {'provider':'test','seed':seed,'denoise':denoise}
    monkeypatch.setattr(main,'generate_detail_candidate',fake_detail)
    with TestClient(app) as client:
        pid=client.post('/api/projects',json={'name':'Detail plan contract','subjectType':'character','intendedUse':'web','quality':'standard'}).json()['id']
        for role in ('front','side','back'):
            assert client.post(f'/api/projects/{pid}/assets?role={role}',files={'file':(f'{role}.png',image_bytes(),'image/png')}).status_code==201
        validation=client.post(f'/api/projects/{pid}/validate').json()
        if validation['verdict']=='conditional':assert client.post(f'/api/projects/{pid}/validation/accept-risks').status_code==200
        plan=client.post(f'/api/projects/{pid}/detail-plans',json={'mode':'balanced'})
        assert plan.status_code==201
        payload=plan.json();assert len(payload['regions'])==11 and payload['sourceReferenceSetId']
        region=next(r for r in payload['regions'] if r['regionKey']=='face')
        assert client.patch(f"/api/detail-plans/{payload['id']}/regions/{region['id']}",json={'selected':True,'targetUsage':'material'}).status_code==200
        confirmed=client.post(f"/api/detail-plans/{payload['id']}/confirm")
        assert confirmed.status_code==200 and confirmed.json()['status']=='confirmed'
        assert client.patch(f"/api/detail-plans/{payload['id']}/regions/{region['id']}",json={'selected':False}).status_code==409
        job=client.post(f"/api/detail-plans/{payload['id']}/jobs",json={'candidateCount':2})
        assert job.status_code==201
        for _ in range(50):
            current=client.get(f"/api/detail-jobs/{job.json()['id']}").json()
            if current['status'] in ('awaiting_approval','failed'):break
            time.sleep(.02)
        assert current['status']=='awaiting_approval' and len(current['groups'])>=2
        first,second=current['groups'][:2];assert first['assets']
        approved=client.post(f"/api/detail-candidate-groups/{first['id']}/approve",json={'notes':'approve'})
        assert approved.status_code==200 and approved.json()['referenceSet']['status']=='locked'
        assert approved.json()['referenceSet']['parentReferenceSetId']==payload['sourceReferenceSetId']
        reference_set_id=approved.json()['referenceSet']['id']
        consumption=client.get(f'/api/reference-sets/{reference_set_id}/consumption-map')
        assert consumption.status_code==200
        mapping=consumption.json();assert set(mapping['hunyuanInputs'])=={'front','side','back'}
        assert mapping['hunyuanInputs']['front']['purpose']=='baseline'
        assert any(a['purpose']=='material' for a in mapping['blenderOnlyAssets'])
        monkeypatch.setattr(main,'launch',lambda _job_id:None)
        geometry_plan=client.get(f'/api/projects/{pid}/plan').json();geometry_plan['referenceSetId']=reference_set_id
        assert client.patch(f'/api/projects/{pid}/plan',json=geometry_plan).status_code==200
        geometry_job=client.post(f'/api/projects/{pid}/jobs')
        assert geometry_job.status_code==201
        with db() as con:
            snapshot=__import__('json').loads(con.execute('SELECT config_snapshot FROM jobs WHERE id=?',(geometry_job.json()['id'],)).fetchone()[0])
        assert snapshot['referenceSetConsumption']['referenceSetId']==reference_set_id
        assert snapshot['referenceSetConsumption']['hunyuanInputs']['front']['sha256']==mapping['hunyuanInputs']['front']['sha256']
        rejected=client.post(f"/api/detail-candidate-groups/{second['id']}/reject",json={'notes':'not suitable'})
        assert rejected.status_code==200
        assert client.post(f"/api/detail-candidate-groups/{second['id']}/reject",json={'notes':'again'}).status_code==409
