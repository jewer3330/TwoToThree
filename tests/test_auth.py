from fastapi.testclient import TestClient

from server import auth
from server.main import app


def test_secure_boundary_rejects_anonymous(monkeypatch):
    monkeypatch.setattr(auth,'AUTH_DISABLED',False)
    client=TestClient(app)
    response=client.get('/api/projects')
    assert response.status_code==401
    assert response.json()['code']=='AUTH_REQUIRED'


def test_health_and_spa_remain_public(monkeypatch):
    monkeypatch.setattr(auth,'AUTH_DISABLED',False)
    client=TestClient(app)
    assert client.get('/api/system/health').status_code==200
    assert auth.is_public('/login')
    assert not auth.is_public('/data/projects/secret.glb')
    assert not auth.is_public('/public/models/secret.glb')


def test_admin_boundaries_and_safe_return_url():
    assert auth.requires_admin('/api/gpu/hosts','GET')
    assert auth.requires_admin('/api/printer/printers','GET')
    assert not auth.requires_admin('/api/projects','GET')
    assert auth._safe_return_to('/review/abc?x=1')=='/review/abc?x=1'
    assert auth._safe_return_to('https://evil.example/')=='/'
