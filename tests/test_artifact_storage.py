from server import artifacts
from server.core import load


def test_prepare_artifact_uploads_once_and_records_content_key(monkeypatch,tmp_path):
    path=tmp_path/'preview.glb'
    path.write_bytes(b'glTF-test-payload')

    class FakeOss:
        def __init__(self):self.objects={};self.uploads=0
        def size(self,key):return self.objects.get(key)
        def upload(self,local,key,*,mime_type=None):
            assert mime_type=='model/gltf-binary'
            self.objects[key]=local.stat().st_size;self.uploads+=1

    fake=FakeOss()
    monkeypatch.setattr(artifacts,'resolve_transfer_backend',lambda:'oss')
    monkeypatch.setattr(artifacts.storage,'_oss',fake)
    monkeypatch.setattr(artifacts,'storage_path',lambda _: 'data/test/preview.glb')

    first=artifacts.prepare_artifact(path,'model/gltf-binary',{'kind':'preview'})
    second=artifacts.prepare_artifact(path,'model/gltf-binary',{'kind':'preview'})
    metadata=load(first[3])
    assert first[0]=='data/test/preview.glb'
    assert metadata['storageBackend']=='oss'
    assert metadata['objectKey'].endswith(first[2]+'.glb')
    assert second[2]==first[2]
    assert fake.uploads==1


def test_oss_storage_separates_internal_transfer_and_public_signing(monkeypatch):
    from server import config
    from server import storage as storage_module

    created=[]
    class FakeBucket:
        def __init__(self,auth,endpoint,bucket,**kwargs):
            self.endpoint=endpoint;self.kwargs=kwargs;created.append(self)
        def sign_url(self,method,key,expires,**kwargs):
            return f'https://{self.endpoint}/{key}'
    class FakeOss2:
        class Auth:
            def __init__(self,*_):pass
        Bucket=FakeBucket
    monkeypatch.setitem(__import__('sys').modules,'oss2',FakeOss2)
    monkeypatch.setattr(config,'OSS_INTERNAL_ENDPOINT','oss-cn-shanghai-internal.aliyuncs.com')
    monkeypatch.setattr(config,'OSS_ENDPOINT','oss-cn-shanghai.aliyuncs.com')
    monkeypatch.setattr(config,'OSS_PUBLIC_ENDPOINT','')
    client=storage_module.OssStorage()
    assert client.bucket.endpoint.endswith('-internal.aliyuncs.com')
    assert client.sign_get('artifacts/a.glb').startswith('https://oss-cn-shanghai.aliyuncs.com/')
    assert len(created)==2
