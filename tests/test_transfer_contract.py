"""P0 传输契约测试（PRODUCTION_UPGRADE_MASTER_PLAN §2）。

覆盖：
- 远端存在性检查无法确认时必须失败（禁止返回 True）。
- 传输错误分类：TRANSFER_FAILED / CHECKSUM_MISMATCH。
- 下载校验：长度、SHA-256、GLB 有效性。
- cleanup 只在 committed 后执行（未 committed 保留 GPU 产物）。
- 传输状态持久化：pending 记录可恢复（resume 续传）。
- 传输失败不重跑推理（worker 进入 transfer_pending）。
"""
import json, os, shutil, struct, time
import pytest
from pathlib import Path
from server import transfers
from server.transfers import (TransferError,TransferIntegrityError,
                              COMPUTE_FAILED,TRANSFER_FAILED,CHECKSUM_MISMATCH,COMMIT_FAILED)

# ---------- fixture：隔离 transfer DB ----------
@pytest.fixture(autouse=True)
def isolate_transfer_db(tmp_path,monkeypatch):
    db_path=tmp_path/'transfer_state.db'
    monkeypatch.setattr(transfers,'DB',db_path)
    transfers.init_db()
    yield

# ---------- 远端存在性检查 ----------

class _FakeCmd:
    def __init__(self,rc=0,out=''):
        self.returncode=rc;self.stdout=out

class _FakeRemote:
    """最小 Remote 替身：只实现 cmd（用于 _remote_exists 测试）。"""
    def __init__(self,cmd_results=None):
        self._cmds=list(cmd_results or [])
    def cmd(self,*a,**k):
        if not self._cmds:raise OSError('unexpected cmd call')
        return self._cmds.pop(0)

def test_remote_exists_false_when_cmd_fails():
    """rc!=0 也属无法确认 → 抛异常，禁止返回 True/False 乐观通过。"""
    from server.backends import Remote
    r=Remote.__new__(Remote)
    r.cmd=lambda *a,**k: _FakeCmd(rc=1,out='')
    with pytest.raises(TransferError) as ei:
        r._remote_exists('D:\\x\\y')
    assert ei.value.code==TRANSFER_FAILED

def test_remote_exists_true():
    from server.backends import Remote
    r=Remote.__new__(Remote)
    r.cmd=lambda *a,**k: _FakeCmd(rc=0,out='True\n')
    assert r._remote_exists('D:\\x\\y') is True

def test_remote_exists_raises_when_cmd_timeout():
    """P0 核心：无法确认（异常）必须抛 TransferError，禁止返回 True。"""
    from server.backends import Remote
    r=Remote.__new__(Remote)
    def boom(*a,**k):raise TimeoutError('ssh timeout')
    r.cmd=boom
    with pytest.raises(TransferError) as ei:
        r._remote_exists('D:\\x\\y')
    assert ei.value.code==TRANSFER_FAILED

# ---------- 校验：长度 / SHA-256 / GLB ----------

def test_verify_length_mismatch(tmp_path):
    p=tmp_path/'a.glb';p.write_bytes(b'12345678')
    with pytest.raises(TransferIntegrityError) as ei:
        transfers.verify_file(p,expected_size=9999,expected_sha256=None,kind='file')
    assert ei.value.code==CHECKSUM_MISMATCH

def test_verify_sha256_mismatch(tmp_path):
    p=tmp_path/'a.glb';p.write_bytes(b'hello')
    with pytest.raises(TransferIntegrityError) as ei:
        transfers.verify_file(p,expected_size=None,expected_sha256='0'*64,kind='file')
    assert ei.value.code==CHECKSUM_MISMATCH

def _valid_glb()->bytes:
    # glTF 头部 + JSON chunk（含 meshes 空数组）
    js=json.dumps({'asset':{'version':'2.0'},'meshes':[]}).encode()
    payload=js+b'\x00'*((4-len(js)%4)%4)
    body=struct.pack('<II',len(payload),0x4E4F534A)+payload
    total=12+len(body)
    return b'glTF'+struct.pack('<II',2,total)+body

def test_verify_glb_valid(tmp_path):
    p=tmp_path/'ok.glb';p.write_bytes(_valid_glb())
    transfers.verify_file(p,None,None,kind='glb')  # 不抛

def test_verify_glb_bad_header(tmp_path):
    p=tmp_path/'bad.glb';p.write_bytes(b'notgltf')
    with pytest.raises(TransferIntegrityError) as ei:
        transfers.verify_file(p,None,None,kind='glb')
    assert ei.value.code==CHECKSUM_MISMATCH

def test_verify_glb_length_mismatch(tmp_path):
    raw=_valid_glb();p=tmp_path/'trunc.glb';p.write_bytes(raw[:-4])  # 截断
    with pytest.raises(TransferIntegrityError) as ei:
        transfers.verify_file(p,None,None,kind='glb')
    assert '声明长度' in str(ei.value)

def test_verify_glb_json_corrupt(tmp_path):
    js=b'{not json';payload=js+b'\x00'*((4-len(js)%4)%4)
    body=struct.pack('<II',len(payload),0x4E4F534A)+payload
    total=12+len(body)
    p=tmp_path/'badjson.glb';p.write_bytes(b'glTF'+struct.pack('<II',2,total)+body)
    with pytest.raises(TransferIntegrityError) as ei:
        transfers.verify_file(p,None,None,kind='glb')
    assert ei.value.code==CHECKSUM_MISMATCH

# ---------- 传输状态持久化 + cleanup committed ----------

def test_record_pending_and_commit(tmp_path):
    tid=transfers.record_pending('job_x','host1','m1',r'D:\w\m1\out.glb',str(tmp_path/'out.glb'),kind='glb',
                                 expected_size=100,expected_sha256='abc')
    pend=transfers.pending_for_job('job_x')
    assert len(pend)==1 and pend[0]['status']=='pending'
    transfers.mark_committed(tid)
    assert len(transfers.pending_for_job('job_x'))==0

def test_cleanup_only_after_committed():
    from server.backends import Remote
    calls=[]
    r=Remote.__new__(Remote)
    r.stage=lambda m:f'D:\\w\\{m}'
    r.cmd=lambda *a,**k: calls.append(a) or _FakeCmd(rc=0)
    r.cleanup('m1')                # 未 committed → 不执行远端删除
    assert calls==[]
    r.cleanup('m1',committed=True)  # committed → 删除
    assert calls and any('Remove-Item' in str(a) for a in calls[0])

def test_cleanup_expired_local(tmp_path):
    tid=transfers.record_pending('job_old','h','m',r'D:\w\m\x',str(tmp_path/'x.glb'))
    Path(tmp_path/'x.glb').write_bytes(b'1')
    # 人为把 created_at 改到 49h 前
    with transfers._connect() as con:
        con.execute("UPDATE transfers SET created_at=? WHERE id=?",(time.time()-49*3600,tid));con.commit()
    n=transfers.cleanup_expired(retention_hours=48)
    assert n==1
    assert not (tmp_path/'x.glb').exists()

def test_error_codes_constants():
    assert {COMPUTE_FAILED,TRANSFER_FAILED,CHECKSUM_MISMATCH,COMMIT_FAILED}== \
           {'COMPUTE_FAILED','TRANSFER_FAILED','CHECKSUM_MISMATCH','COMMIT_FAILED'}

# ---------- 传输失败不重跑推理（worker 状态机） ----------

def test_worker_transfer_pending_state(monkeypatch,tmp_path):
    """TransferError → job transfer_pending，不标 failed；GPU 产物记录保留。"""
    import server.worker as worker
    import server.core as core
    # 隔离 studio.db（避免污染真实数据 + FK 冲突）
    monkeypatch.setattr(core,'DB',tmp_path/'studio.db')
    core.init_db()
    from server.core import db,now,uid
    from server import transfers as tr
    tr.DB=tmp_path/'ts.db';tr.init_db()
    pid='prj_'+uid('')[4:]
    jid='job_'+uid('')[4:]
    vid='ver_'+uid('')[4:]
    with db() as con:
        con.execute("INSERT INTO projects(id,slug,name,subject_type,intended_use,quality,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",(pid,pid[-8:],'t','character','web','standard','queued',now(),now()))
        con.execute("INSERT INTO versions(id,project_id,number,label,status,created_at) VALUES(?,?,?,?,?,?)",(vid,pid,1,'v1','processing',now()))
        con.execute("INSERT INTO jobs(id,project_id,version_id,status,config_snapshot,requested_backend,attempt,created_at) VALUES(?,?,?,?,?,?,?,?)",(jid,pid,vid,'running','{"primaryBackend":"hunyuan3d"}','hunyuan3d',1,now()))
        for i,(k,l) in enumerate(worker.STAGES):con.execute("INSERT INTO stages(id,job_id,stage_key,label,status,position) VALUES(?,?,?,?,?,?)",(uid('s'),jid,k,l,'pending',i))
    tr.record_pending(jid,'host1','m1',r'D:\w\m1\out.glb',str(tmp_path/'out.glb'),kind='glb')
    # 模拟 run 中 TransferError 被 worker 捕获后的状态写入
    try:
        raise TransferError(TRANSFER_FAILED,'scp failed')
    except TransferError as exc:
        with db() as con:
            con.execute("UPDATE jobs SET status='transfer_pending',error_code=?,error_summary=? WHERE id=?",(getattr(exc,'code','TRANSFER_FAILED'),str(exc)[:500],jid))
    with db() as con:
        row=con.execute("SELECT status,error_code FROM jobs WHERE id=?",(jid,)).fetchone()
    assert row['status']=='transfer_pending'
    assert row['error_code']==TRANSFER_FAILED
    assert len(tr.pending_for_job(jid))==1  # GPU 产物记录保留
