"""selfreg（WS 自注册 GPU 节点）调度/执行链路回归测试。

覆盖正式线「GPU 不跑」修复：
- selfreg 主机不再向 agent 派发 run_job（节点没有控制面 DB/素材，worker.run
  无从执行），改由控制面 worker 线程 bind_host 执行，GPU 命令经 WS run_cmd
  通道下发到节点；
- capabilities() 在线程绑定主机时取主机 status.caps（selfreg=agent 上报、
  SSH=探针刷新），避免控制面本地无权重时误判 environment unavailable；
- SelfregRemote 补齐与 backends.Remote 对齐的 download_dir（目录 tar→回传→
  解压）与 run(cwd_remote)；
- selfreg 数据面（pullbox 下发 / inbox 回传）走机器通道，不被浏览器会话边界
  拦截，端点内校验 X-Worker-Token。
"""
import io
import tarfile
import threading
from pathlib import Path

CAP_KEYS = ('hunyuan3d', 'hunyuan3dMultiview', 'sf3d', 'triposr', 'blender',
            'blenderRefinement', 'blenderStlExport')


# ---------- remote_from_cfg：selfreg / ssh ----------

def test_remote_from_cfg_selfreg_binds_agent_node(monkeypatch):
    from server import backends
    from server.gpu import selfreg as sr
    node = {'id': 'n1', 'os': 'windows', 'workDir': r'D:\print3d\work',
            'repoRoot': r'D:\print3d\TwoToThree', 'extRoot': r'D:\print3d'}
    monkeypatch.setitem(sr._agents, 'n1', {'node': node})
    try:
        r = backends.remote_from_cfg({'id': 'n1', 'provider': 'selfreg', 'name': 'GPU-1'})
        assert r is not None and r.node_id == 'n1'
        assert r.is_windows
        assert r.work == r'D:\print3d\work'
        assert r.root == r'D:\print3d\TwoToThree'
        assert r.ext == r'D:\print3d'
        assert r._host_cfg['id'] == 'n1'   # 绑定主机配置回传，供 capabilities 使用
    finally:
        monkeypatch.delitem(sr._agents, 'n1')


def test_remote_from_cfg_ssh_returns_remote(tmp_path):
    from server import backends
    r = backends.remote_from_cfg({'id': 'g1', 'provider': 'ssh', 'host': '10.0.0.1',
                                  'user': 'd0993', 'key': str(tmp_path / 'k'),
                                  'root': 'r', 'ext': 'e', 'work': 'w', 'os': 'windows'})
    assert r is not None and r.host == '10.0.0.1'
    assert r._host_cfg['id'] == 'g1'


def test_remote_from_cfg_unknown_returns_none():
    from server import backends
    assert backends.remote_from_cfg(None) is None
    assert backends.remote_from_cfg({'id': 'x', 'provider': 'ssh'}) is None  # 无 host


# ---------- capabilities：绑定主机能力优先 ----------

def test_capabilities_uses_bound_host_caps(monkeypatch):
    from server import backends
    from server.gpu import hosts as gpu_hosts
    caps = {'hunyuan3d': True, 'hunyuan3dMultiview': True, 'sf3d': False, 'triposr': False,
            'blender': True, 'blenderRefinement': True, 'blenderStlExport': True}
    monkeypatch.setattr(gpu_hosts, 'list_hosts',
                        lambda: [{'id': 'n1', 'name': 'GPU', 'status': {'caps': caps}}])
    monkeypatch.setattr(backends, 'MODE', 'local')
    monkeypatch.setattr(backends, 'REMOTE_HOST', '')
    try:
        backends.bind_host({'id': 'n1', 'provider': 'selfreg', 'name': 'GPU'})
        out = backends.capabilities()
        assert out['hunyuan3d'] is True and out['blender'] is True
        assert out['sf3d'] is False and out['triposr'] is False
        assert set(out) == set(CAP_KEYS)
    finally:
        backends.bind_host(None)


def test_capabilities_unbound_falls_back_local(monkeypatch):
    """未绑定主机时不走集群状态（避免把控制台 API 的判定绑到远端）。"""
    from server import backends
    backends.bind_host(None)
    monkeypatch.setattr(backends, 'MODE', 'local')
    monkeypatch.setattr(backends, 'REMOTE_HOST', '')
    out = backends.capabilities()
    assert set(out) == set(CAP_KEYS)


# ---------- SelfregRemote.download_dir（节点 tar → 回传 → 解压） ----------

def _fake_dir_tar_bytes(dirname='renders'):
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode='w:gz') as t:
        for name, data in ((f'{dirname}/front.png', b'PNG1'), (f'{dirname}/back.png', b'PNG2')):
            info = tarfile.TarInfo(name)
            info.size = len(data)
            t.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def test_selfreg_download_dir(monkeypatch, tmp_path):
    from server.gpu import selfreg as sr
    from server.gpu.selfreg_remote import SelfregRemote
    node = {'os': 'linux', 'workDir': str(tmp_path / 'work'), 'repoRoot': str(tmp_path),
            'extRoot': str(tmp_path / 'ext')}
    remote = SelfregRemote('n1', node)
    work = remote.work
    remote_dir = remote.join(work, 'renders')
    tar_calls = []

    def fake_run_command_sync(node_id, argv, *, cwd=None, timeout=3600, log=None):
        tar_calls.append(argv)
        return 0, None

    def fake_upload_file_sync(node_id, path, timeout=600, upload_id=None):
        root = sr.inbox_root(upload_id)
        root.mkdir(parents=True, exist_ok=True)
        (root / 'renders.tgz').write_bytes(_fake_dir_tar_bytes())
        return True, None

    monkeypatch.setattr(sr, 'run_command_sync', fake_run_command_sync)
    monkeypatch.setattr(sr, 'upload_file_sync', fake_upload_file_sync)
    local_dir = tmp_path / 'out'
    remote.download_dir(remote_dir, local_dir)
    assert tar_calls and tar_calls[0][0] == 'tar'
    assert (local_dir / 'front.png').exists() and (local_dir / 'back.png').exists()
    assert not (local_dir / 'renders').exists()   # 目录内容上提，无多余嵌套


def test_ssh_download_dir_idempotent(monkeypatch, tmp_path):
    """远端目录回传解压上提时，本地已有同名条目必须先删再移（幂等），
    否则 shutil.move 抛 "Destination path already exists"，使已成功渲染的
    Blender 产物无法落库（Blender 阶段会因此整体 failed）。"""
    import tarfile
    import server.backends as b
    from server import transfers
    from server.transfers import TransferError, TRANSFER_FAILED

    def _mk_tgz(entries):
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode='w:gz') as t:
            for name, data in entries:
                info = tarfile.TarInfo(name)
                info.size = len(data)
                t.addfile(info, io.BytesIO(data))
        return buf.getvalue()

    local_dir = tmp_path / 'out'
    local_dir.mkdir()
    (local_dir / 'blender-report.json').write_text('old')   # 模拟残留/重复回传

    r = b.Remote('h', 'root', None, '/r/tt', '/r', '/r/work', os_type='linux')
    r.remote_archive_metadata = lambda d: ('/r/renders.tgz', 10, '0' * 64)
    r.download = lambda src, dst, **k: dst.write_bytes(
        _mk_tgz([('renders/blender-report.json', b'new'), ('renders/front.png', b'PNG')]))
    r.download_dir('/r/renders', local_dir)
    assert (local_dir / 'blender-report.json').read_text() == 'new'
    assert (local_dir / 'front.png').exists()
    assert not (local_dir / 'renders').exists()


def test_selfreg_run_accepts_cwd_remote(monkeypatch):
    """sf3d/triposr 等 remote 分支传 cwd_remote 时不抛 TypeError。"""
    from server.gpu import selfreg as sr
    from server.gpu.selfreg_remote import SelfregRemote
    node = {'os': 'linux', 'workDir': '/w', 'repoRoot': '/r', 'extRoot': '/e'}
    remote = SelfregRemote('n1', node)
    calls = {}

    def fake_run_command_sync(node_id, argv, *, cwd=None, timeout=3600, log=None):
        calls['cwd'] = cwd
        return 0, None

    monkeypatch.setattr(sr, 'run_command_sync', fake_run_command_sync)
    remote.run(['echo', 'hi'], lambda m: None, lambda: False, timeout=60, marker='',
               cwd_remote='/repo')
    assert calls['cwd'] == '/repo'


def test_selfreg_run_fetches_by_stage_token(monkeypatch):
    """backends 传 marker=完整 stage 路径（SSH 惯例）时，selfreg 需按末段 token
    拉取 pullbox 输入到对应 stage 目录；拉取失败必须中止而不是裸跑 GPU。"""
    from server.gpu import selfreg as sr
    from server.gpu.selfreg_remote import SelfregRemote
    node = {'os': 'linux', 'workDir': '/w', 'repoRoot': '/r', 'extRoot': '/e'}
    remote = SelfregRemote('n1', node)
    calls = {}

    def fake_fetch(node_id, marker, dest_dir, timeout=120):
        calls['fetch'] = (marker, dest_dir)
        return False, 'boom'

    monkeypatch.setattr(sr, 'fetch_files_sync', fake_fetch)
    try:
        remote.run(['echo', 'hi'], lambda m: None, lambda: False, timeout=60,
                   marker='/w/selfreg-stage/p3d-abc123')
        raise AssertionError('fetch 失败应中止执行')
    except RuntimeError as exc:
        assert '输入下发失败' in str(exc)
    assert calls['fetch'] == ('p3d-abc123', '/w/selfreg-stage/p3d-abc123')
    assert remote._marker_token('/w/selfreg-stage/p3d-abc123') == 'p3d-abc123'
    assert remote._marker_token('p3d-xyz') == 'p3d-xyz'


# ---------- scheduler：selfreg 不再把 worker 派到 agent 侧 ----------

def test_scheduler_selfreg_runs_control_plane_worker(monkeypatch):
    from server import backends, worker
    from server.gpu import scheduler
    src = Path('server/gpu/scheduler.py').read_text(encoding='utf-8')
    assert "'type':'run_job'" not in src and '"type":"run_job"' not in src  # 不再向 agent dispatch run_job
    assert '_spawn_selfreg' not in src   # v1 派发路径已删除
    ran = {}
    done = threading.Event()

    def fake_worker_run(job_id):
        r = backends.remote()
        ran['job'] = job_id
        ran['bound_node'] = getattr(r, 'node_id', None) if r is not None else None
        done.set()

    monkeypatch.setattr(worker, 'run', fake_worker_run)
    scheduler._spawn({'id': 'job_x'}, {'id': 'n1', 'provider': 'selfreg', 'name': 'GPU-1'})
    assert done.wait(3), 'selfreg 任务应在本进程（控制面）线程中执行'
    assert ran.get('job') == 'job_x'
    assert ran.get('bound_node') == 'n1'   # 线程已绑定 selfreg 主机 → backends 走 WS 通道


# ---------- 数据面鉴权：机器通道 + token ----------

def test_auth_selfreg_data_plane_is_public_prefix():
    from server import auth
    assert auth.is_public('/api/gpu/selfreg/upload/up-123') is True
    assert auth.is_public('/api/gpu/selfreg/pullbox/m1/a.png') is True
    # 其余 GPU 管理 API 仍需要会话鉴权（管理员）
    assert auth.is_public('/api/gpu/hosts') is False
    assert auth.is_public('/api/gpu/queue') is False


def test_selfreg_worker_token_check(monkeypatch):
    from fastapi import HTTPException
    from server import config
    from server.gpu import selfreg as sr

    class _Req:
        def __init__(self, token):
            self.headers = {'x-worker-token': token} if token else {}

    monkeypatch.setattr(config, 'WORKER_TOKEN', 's3cret')
    sr._require_worker_token(_Req('s3cret'))          # 正确 token 放行
    try:
        sr._require_worker_token(_Req('wrong'))
        raise AssertionError('错误 token 应 401')
    except HTTPException as exc:
        assert exc.status_code == 401
    monkeypatch.setattr(config, 'WORKER_TOKEN', '')   # 未配置（本地开发）放行
    sr._require_worker_token(_Req(''))
