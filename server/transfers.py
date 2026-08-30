"""传输状态持久化与产物完整性校验（P0）。

设计要点（PRODUCTION_UPGRADE_MASTER_PLAN §2）：
- 远端存在性检查无法确认时必须失败，禁止返回 True。
- 传输状态持久化到 SQLite，主控重启后可恢复（transfer_pending → resume）。
- 下载完成校验文件长度与 SHA-256；GLB 额外校验头部与 JSON 可解析。
- cleanup 只在 artifact_committed 之后执行；GPU 产物默认保留 48 小时，由定时任务清理。
- 错误分类：COMPUTE_FAILED / TRANSFER_FAILED / CHECKSUM_MISMATCH / COMMIT_FAILED。
"""
from __future__ import annotations
import hashlib, json, sqlite3, struct, threading, time
from pathlib import Path
from .core import DATA

DB=DATA/'transfer_state.db'
RETENTION_HOURS=48

COMPUTE_FAILED='COMPUTE_FAILED'
TRANSFER_FAILED='TRANSFER_FAILED'
CHECKSUM_MISMATCH='CHECKSUM_MISMATCH'
COMMIT_FAILED='COMMIT_FAILED'

_lock=threading.RLock()

def _connect():
    con=sqlite3.connect(DB,timeout=30,check_same_thread=False)
    con.row_factory=sqlite3.Row
    return con

def init_db():
    con=_connect()
    try:
        con.execute('''CREATE TABLE IF NOT EXISTS transfers(
            id TEXT PRIMARY KEY,
            job_id TEXT NOT NULL,
            host TEXT NOT NULL,
            marker TEXT NOT NULL,
            remote_path TEXT NOT NULL,
            local_path TEXT NOT NULL,
            kind TEXT NOT NULL DEFAULT 'glb',
            expected_size INTEGER,
            expected_sha256 TEXT,
            status TEXT NOT NULL DEFAULT 'pending',   -- pending|committed|cleaned
            error_code TEXT,
            created_at REAL NOT NULL,
            committed_at REAL,
            updated_at REAL NOT NULL,
            host_cfg TEXT
        )''')
        con.execute('CREATE INDEX IF NOT EXISTS idx_transfers_job ON transfers(job_id)')
        con.execute('CREATE INDEX IF NOT EXISTS idx_transfers_status ON transfers(status)')
        con.commit()
    finally:
        con.close()

def record_pending(job_id:str,host:str,marker:str,remote_path:str,local_path:str,kind:str='glb',
                   expected_size:int|None=None,expected_sha256:str|None=None,host_cfg:dict|None=None)->str:
    tid=f'{job_id}-{marker}-{Path(remote_path).name}'
    with _lock:
        con=_connect()
        try:
            con.execute('''INSERT OR REPLACE INTO transfers
                (id,job_id,host,marker,remote_path,local_path,kind,expected_size,expected_sha256,
                 status,created_at,updated_at,host_cfg)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                (tid,job_id,host,marker,remote_path,str(local_path),kind,expected_size,expected_sha256,
                 'pending',time.time(),time.time(),json.dumps(host_cfg) if host_cfg else None))
            con.commit()
        finally:
            con.close()
    return tid

def mark_committed(tid:str):
    with _lock:
        con=_connect()
        try:
            con.execute("UPDATE transfers SET status='committed',committed_at=?,updated_at=? WHERE id=?",(time.time(),time.time(),tid))
            con.commit()
        finally:
            con.close()

def mark_cleaned(tid:str):
    with _lock:
        con=_connect()
        try:
            con.execute("UPDATE transfers SET status='cleaned',updated_at=? WHERE id=?",(time.time(),tid))
            con.commit()
        finally:
            con.close()

def pending_for_job(job_id:str):
    with _lock:
        con=_connect()
        try:
            rows=con.execute("SELECT * FROM transfers WHERE job_id=? AND status='pending' ORDER BY created_at",(job_id,)).fetchall()
            return [dict(r) for r in rows]
        finally:
            con.close()

def resume_pending(job_id:str):
    """恢复传输：对 job 的 pending 产物重新拉取并校验（不重跑推理）。

    返回 (resumed, failed)：resumed 为成功提交数，failed 为失败列表。
    每项使用记录时的 host 连接快照 + 期望校验值；成功则标记 committed。
    """
    from .backends import Remote, BackendError
    pending=pending_for_job(job_id)
    resumed=0;failed=[]
    for p in pending:
        try:
            cfg=json.loads(p['host_cfg']) if p.get('host_cfg') else None
            if not cfg or not cfg.get('host'):
                failed.append((p['id'],'缺少主机连接快照，无法恢复传输'));continue
            r=Remote(cfg['host'],cfg['user'],Path(cfg['key']),cfg.get('root',''),cfg.get('ext',''),cfg.get('work',''))
            r.download(p['remote_path'],Path(p['local_path']),
                       expected_size=p['expected_size'],expected_sha256=p['expected_sha256'],kind=p['kind'])
            mark_committed(p['id'])
            r.cleanup(p['marker'],committed=True)
            resumed+=1
        except Exception as exc:
            failed.append((p['id'],str(exc)[:200]))
    return resumed,failed

def all_pending():
    with _lock:
        con=_connect()
        try:
            rows=con.execute("SELECT * FROM transfers WHERE status='pending' ORDER BY created_at").fetchall()
            return [dict(r) for r in rows]
        finally:
            con.close()

def cleanup_expired(retention_hours:float=RETENTION_HOURS)->int:
    """清理超过保留期的 pending 记录（GPU 产物已在远端，主控仅清理本地状态与本地残留文件）。"""
    cutoff=time.time()-retention_hours*3600
    with _lock:
        con=_connect()
        try:
            rows=con.execute("SELECT * FROM transfers WHERE status='pending' AND created_at<?",(cutoff,)).fetchall()
            for r in rows:
                # 清理本地残留临时文件（远端由 GPU 端清理，主控不主动删 GPU 产物）
                local=Path(r['local_path'])
                if local.exists():local.unlink(missing_ok=True)
                con.execute("UPDATE transfers SET status='cleaned',updated_at=? WHERE id=?",(time.time(),r['id']))
            con.commit()
            return len(rows)
        finally:
            con.close()

# ---------- 校验工具 ----------

def sha256_of(path:Path)->str:
    h=hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
    return h.hexdigest()

def verify_file(path:Path, expected_size:int|None, expected_sha256:str|None, kind:str='glb') -> None:
    """校验本地文件：长度、SHA-256、GLB 有效性。失败抛 CHECKSUM_MISMATCH。"""
    if not path.exists() or path.stat().st_size==0:
        raise TransferIntegrityError(CHECKSUM_MISMATCH,f'产物不存在或为空: {path}')
    actual_size=path.stat().st_size
    if expected_size is not None and actual_size!=expected_size:
        raise TransferIntegrityError(CHECKSUM_MISMATCH,
            f'产物长度不符: 期望 {expected_size}，实际 {actual_size}（{path.name}）')
    if expected_sha256 is not None:
        actual=sha256_of(path)
        if actual!=expected_sha256:
            raise TransferIntegrityError(CHECKSUM_MISMATCH,
                f'产物 SHA-256 不符: 期望 {expected_sha256[:16]}…，实际 {actual[:16]}…（{path.name}）')
    if kind=='glb':
        validate_glb(path)

def validate_glb(path:Path):
    """GLB 基础有效性：头部 glTF + v2 + 声明长度一致 + JSON chunk 可解析。"""
    with path.open('rb') as f:head=f.read(12)
    if len(head)!=12 or head[:4]!=b'glTF':
        raise TransferIntegrityError(CHECKSUM_MISMATCH,f'GLB 缺少 glTF 头部: {path.name}')
    version,declared=struct.unpack('<II',head[4:])
    if version!=2:
        raise TransferIntegrityError(CHECKSUM_MISMATCH,f'GLB 版本不支持: {version}')
    actual=path.stat().st_size
    if declared!=actual:
        raise TransferIntegrityError(CHECKSUM_MISMATCH,f'GLB 声明长度 {declared} 与文件长度 {actual} 不一致')
    # 解析 JSON chunk（chunk 0 应为 JSON）
    with path.open('rb') as f:
        f.seek(12)
        while True:
            header=f.read(8)
            if len(header)<8:break
            length,kind=struct.unpack('<II',header)
            payload=f.read(length)
            if kind==0x4E4F534A:  # JSON
                try:json.loads(payload.rstrip(b'\x00 ').decode('utf-8'))
                except Exception as exc:raise TransferIntegrityError(CHECKSUM_MISMATCH,f'GLB JSON 不可解析: {exc}')
                return
    raise TransferIntegrityError(CHECKSUM_MISMATCH,'GLB 缺少 JSON chunk')

class TransferError(RuntimeError):
    """传输相关错误（与计算错误区分）。code 为错误分类。"""
    def __init__(self,code:str,message:str):
        super().__init__(message)
        self.code=code

class TransferIntegrityError(TransferError):
    def __init__(self,code:str,message:str):
        super().__init__(code,message)
