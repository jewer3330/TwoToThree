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

# 已存在表可能需要补齐的列（旧库无这些列时迁移）
_MIGRATIONS=[
    ('host_cfg','TEXT'),
    ('expected_size','INTEGER'),
    ('expected_sha256','TEXT'),
    ('committed_at','REAL'),
    ('error_code','TEXT'),
]

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
            status TEXT NOT NULL DEFAULT 'pending',   -- pending|downloaded|verified|committed|cleaned
            error_code TEXT,
            created_at REAL NOT NULL,
            committed_at REAL,
            updated_at REAL NOT NULL,
            host_cfg TEXT
        )''')
        # 幂等迁移：已存在但缺列的旧表逐个补齐（SQLite 无 ADD COLUMN IF NOT EXISTS）
        cols={r['name'] for r in con.execute('PRAGMA table_info(transfers)')}
        for name,ddl in _MIGRATIONS:
            if name not in cols:
                con.execute(f'ALTER TABLE transfers ADD COLUMN {name} {ddl}')
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

def mark_downloaded(tid:str):
    """下载完成（未校验）。仅当当前为 pending 时推进。"""
    with _lock:
        con=_connect()
        try:
            con.execute("UPDATE transfers SET status='downloaded',updated_at=? WHERE id=? AND status='pending'",(time.time(),tid))
            con.commit()
        finally:
            con.close()

def mark_verified(tid:str):
    """校验通过（长度/SHA-256/GLB）。仅当 downloaded/pending 时推进。"""
    with _lock:
        con=_connect()
        try:
            con.execute("UPDATE transfers SET status='verified',updated_at=? WHERE id=? AND status IN ('pending','downloaded')",(time.time(),tid))
            con.commit()
        finally:
            con.close()

def get_transfer(tid:str)->dict|None:
    with _lock:
        con=_connect()
        try:
            r=con.execute('SELECT * FROM transfers WHERE id=?',(tid,)).fetchone()
            return dict(r) if r else None
        finally:
            con.close()

def _remote_for(p:dict):
    from .backends import Remote
    cfg=json.loads(p['host_cfg']) if p.get('host_cfg') else None
    if not cfg or not cfg.get('host'):raise ValueError('缺少主机连接快照，无法恢复传输')
    return Remote(cfg['host'],cfg['user'],Path(cfg['key']),cfg.get('root',''),cfg.get('ext',''),cfg.get('work',''))

def commit_transfer(tid:str):
    """调用方完成 Artifact 持久化注册后显式 commit：标记 committed 并清理远端产物。"""
    p=get_transfer(tid)
    if not p:return False
    if p['status']=='committed':return True
    if p['status']!='verified':
        return False
    # 先把主控的 durable 状态提交，再尝试清理远端。这样即使 SQLite
    # 提交失败，也绝不会先删除唯一的 GPU 端副本。
    with _lock:
        con=_connect()
        try:
            stamp=time.time()
            changed=con.execute("UPDATE transfers SET status='committed',committed_at=?,updated_at=? WHERE id=? AND status='verified'",(stamp,stamp,tid)).rowcount
            con.commit()
        finally:
            con.close()
    if not changed:return False
    try:
        r=_remote_for(p)
        r.cleanup(p['marker'],committed=True)
    except Exception:
        pass  # 远端清理失败不回滚 durable commit；由保留期清理兜底
    return True

def commit_job_transfers(job_id:str)->int:
    """把某 job 所有已 verified（或 downloaded）未 commit 的传输一并 commit。

    供 worker 在产物已注册到 Artifact 表后调用；返回 commit 数量。
    """
    n=0
    for p in pending_for_job(job_id):
        if p['status']=='verified' and commit_transfer(p['id']):n+=1
    return n

def resume_pending(job_id:str):
    """恢复传输：按 kind 分派正确方法（file/glb/compressed/dir），不重跑推理。

    返回 (resumed, pending_left)：resumed 为成功续传数（进入 verified，等待调用方
    commit_transfer），pending_left 为仍失败的项数。
    """
    from .backends import Remote, BackendError
    from .transfers import verify_file
    pending=pending_for_job(job_id)
    resumed=0;failed=0
    for p in pending:
        try:
            r=_remote_for(p)
            local=Path(p['local_path'])
            kind=p['kind']
            exp_size=p.get('expected_size');exp_sha=p.get('expected_sha256')
            if kind=='dir':
                # 目录：压缩后整体回传并解压（download_dir 内部校验归档）
                r.download_dir(p['remote_path'],local)
            elif kind=='glb':
                # GLB 走压缩回传 + GLB 有效性校验
                r.download_compressed(p['remote_path'],local,expected_size=exp_size,expected_sha256=exp_sha,kind='glb')
            elif kind=='compressed':
                r.download_compressed(p['remote_path'],local,expected_size=exp_size,expected_sha256=exp_sha,kind='file')
            else:  # file
                r.download_file(p['remote_path'],local,expected_size=exp_size,expected_sha256=exp_sha,kind='file')
            mark_verified(p['id'])
            resumed+=1
        except Exception as exc:
            failed+=1
    return resumed,failed

def all_pending():
    """全局未 commit 的传输。"""
    with _lock:
        con=_connect()
        try:
            rows=con.execute("SELECT * FROM transfers WHERE status IN ('pending','downloaded','verified') ORDER BY created_at").fetchall()
            return [dict(r) for r in rows]
        finally:
            con.close()

def pending_for_job(job_id:str):
    """未 commit 的传输（pending/downloaded/verified）——等待续传或 commit。"""
    with _lock:
        con=_connect()
        try:
            rows=con.execute("SELECT * FROM transfers WHERE job_id=? AND status IN ('pending','downloaded','verified') ORDER BY created_at",(job_id,)).fetchall()
            return [dict(r) for r in rows]
        finally:
            con.close()

def cleanup_expired(retention_hours:float=RETENTION_HOURS)->int:
    """清理超过保留期的未 commit 传输：删除远端 GPU 产物 + 本地残留，状态置 cleaned。

    只处理 pending/downloaded/verified（未 commit）；committed 由 commit_transfer 即时清理。
    """
    cutoff=time.time()-retention_hours*3600
    with _lock:
        con=_connect()
        try:
            rows=con.execute("SELECT * FROM transfers WHERE status IN ('pending','downloaded','verified') AND created_at<?",(cutoff,)).fetchall()
            for r in rows:
                # 删除远端 GPU 产物（用记录时的主机快照）
                try:
                    rmt=_remote_for(dict(r));rmt.cleanup(r['marker'],committed=True)
                except Exception:pass
                # 清理本地残留
                local=Path(r['local_path'])
                if local.exists():
                    if local.is_dir():
                        import shutil;shutil.rmtree(local,ignore_errors=True)
                    else:local.unlink(missing_ok=True)
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
