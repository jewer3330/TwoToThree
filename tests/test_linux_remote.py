"""Linux 连接层单元测试：OS 感知的 Remote 命令/路径构建（无需真实主机）。"""
from pathlib import Path
from server.backends import Remote, _rc, _host_cfg_snapshot


def test_linux_password_ssh_argv():
    r = Remote('connect.example.com', 'root', None, '/r/tt', '/r', '/r/work',
               os_type='linux', port=13142, password='s3cret')
    argv = r._ssh()
    assert argv[0] == 'sshpass' and argv[1] == '-p' and argv[2] == 's3cret'
    assert 'ssh' in argv
    assert '-p' in argv and '13142' in argv
    assert argv[-1] == 'root@connect.example.com'
    assert '-i' not in argv  # 密码登录不应带密钥


def test_windows_key_ssh_argv(tmp_path):
    key = tmp_path / 'id_key'
    key.write_text('x')
    r = Remote('10.0.0.1', 'd0993', key, r'D:\tt', r'D:\p', r'D:\p\work', os_type='windows')
    argv = r._ssh()
    assert 'sshpass' not in argv
    assert '-i' in argv and str(key) in argv
    assert 'BatchMode=yes' in argv


def test_linux_absolute_path_preserved():
    r = Remote('h', 'root', None, '/r/tt', '/r', '/r/work', os_type='linux')
    assert r.stage('abc') == '/r/work/abc'
    assert r.join('/r/work', 'abc', 'x.png') == '/r/work/abc/x.png'


def test_windows_path_separator():
    r = Remote('h', 'd0993', None, r'D:\tt', r'D:\p', r'D:\p\work', os_type='windows')
    assert r.stage('abc') == r'D:\p\work\abc'
    assert r.norm('D:/p/work') == r'D:\p\work'


def test_rc_linux_layout():
    r = Remote('h', 'root', None, '/r/tt', '/r', '/r/work', os_type='linux')
    rc = _rc(r)
    assert rc['python'] == '/r/local/hunyuan-bootstrap/bin/python'
    assert rc['blender'] == '/r/local/blender/blender'
    assert rc['runner'] == '/r/tt/pipeline/run_hunyuan_yoyo.py'


def test_rc_windows_layout():
    r = Remote('h', 'd0993', None, r'D:\tt', r'D:\p', r'D:\p\work', os_type='windows')
    rc = _rc(r)
    assert rc['python'] == r'D:\p\local\hunyuan-bootstrap\Scripts\python.exe'
    assert rc['blender'] == r'D:\p\local\Blender52\blender.exe'


def test_remote_cmd_linux_bash():
    r = Remote('h', 'root', None, '/r/tt', '/r', '/r/work', os_type='linux')
    cmd = r._remote_cmd(['/r/local/hunyuan-bootstrap/bin/python', '--foo', 'bar'], cwd_remote='/r/tt')
    assert 'export STUDIO_EXTERNAL_ROOT=/r' in cmd
    assert 'cd /r/tt' in cmd
    assert '--foo' in cmd


def test_host_cfg_snapshot_roundtrip():
    r = Remote('h', 'root', None, '/r/tt', '/r', '/r/work', os_type='linux', port=13142, password='pw')
    cfg = _host_cfg_snapshot(r)
    assert cfg['os'] == 'linux' and cfg['port'] == 13142 and cfg['password'] == 'pw'
    r2 = Remote(cfg['host'], cfg['user'], Path(cfg['key']) if cfg['key'] else None,
                cfg['root'], cfg['ext'], cfg['work'], os_type=cfg['os'], port=cfg['port'], password=cfg['password'])
    assert r2.is_linux and r2.port == 13142 and r2.password == 'pw'
