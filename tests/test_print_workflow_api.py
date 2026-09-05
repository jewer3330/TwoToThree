import io
import zipfile

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from server.printpipeline import jobs, routes


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(jobs, 'JOBS_DIR', tmp_path)
    app=FastAPI();app.include_router(routes.router)
    return TestClient(app)


def test_upload_returns_job_and_invalidates_old_outputs(client):
    job=client.post('/api/print/jobs',json={'name':'acceptance'}).json()
    job['sliced']={'file':'old'};job['color']['preview3mf']='old'
    jobs.save_job(job)
    response=client.post(f'/api/print/jobs/{job["id"]}/model',files={'file':('model.stl',b'solid test\nendsolid test')})
    assert response.status_code==201
    updated=response.json()
    assert updated['id']==job['id']
    assert updated['step']=='split'
    assert not updated['color']['preview3mf']
    assert 'sliced' not in updated


def test_sliced_import_rejects_model_archive_and_keeps_model(client):
    job=client.post('/api/print/jobs',json={}).json()
    archive=io.BytesIO()
    with zipfile.ZipFile(archive,'w') as z:z.writestr('3D/3dmodel.model','model')
    url=f'/api/print/jobs/{job["id"]}/sliced'
    response=client.post(url,files={'file':('model.3mf',archive.getvalue())})
    assert response.status_code==422
    assert list(jobs.job_dir(job['id']).glob('*.3mf'))==[]
    archive=io.BytesIO()
    with zipfile.ZipFile(archive,'w') as z:z.writestr('Metadata/plate_1.gcode','; HEADER_BLOCK_START\n'+'G1 X1 Y1\n'*30)
    response=client.post(url,files={'file':('sliced.3mf',archive.getvalue())})
    assert response.status_code==201
    assert response.json()['sliced']['hash']
