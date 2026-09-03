import asyncio

from server import main


def test_execution_mode_accepts_both_remote_architectures(monkeypatch):
    monkeypatch.setenv('PRINT3D_MODE', 'local')
    monkeypatch.setenv('WORKER_MODE', 'remote')
    assert main._execution_mode() == 'remote-gpu'

    monkeypatch.setenv('PRINT3D_MODE', 'remote')
    monkeypatch.setenv('WORKER_MODE', 'local')
    assert main._execution_mode() == 'remote-gpu'


def test_health_reports_effective_remote_mode_without_gpu_probe(monkeypatch):
    monkeypatch.setenv('WORKER_MODE', 'remote')
    monkeypatch.delenv('PRINT3D_MODE', raising=False)
    monkeypatch.setattr(main, 'capabilities', lambda: (_ for _ in ()).throw(
        AssertionError('liveness must not probe a remote GPU')
    ))

    payload = asyncio.run(main.health())

    assert payload['services']['worker'] == 'remote-gpu'
    assert payload['gpu']['status'] == 'unverified'
    assert not any(payload['backends'].values())
