from __future__ import annotations
import hashlib, json, os, re, sqlite3, threading, uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from studio_paths import DATA_ROOT

ROOT=Path(__file__).resolve().parents[1]
DATA=DATA_ROOT
DB=DATA/'studio.db'
DATA.mkdir(parents=True,exist_ok=True)
_lock=threading.RLock()

def now()->str:return datetime.now(timezone.utc).astimezone().isoformat(timespec='seconds')
def uid(prefix:str)->str:return f'{prefix}_{uuid.uuid4().hex[:16]}'
def slugify(value:str)->str:
    clean=re.sub(r'[^\w\-\u4e00-\u9fff]+','-',value.strip(),flags=re.UNICODE).strip('-').lower()
    return f'{clean or "project"}-{uuid.uuid4().hex[:6]}'
def sha256(path:Path)->str:
    h=hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
    return h.hexdigest()
def storage_path(path:Path)->str:
    resolved=path.resolve()
    if resolved.is_relative_to(DATA.resolve()):return f"data/{resolved.relative_to(DATA.resolve()).as_posix()}"
    return resolved.relative_to(ROOT.resolve()).as_posix()
def resolve_storage(value:str)->Path:
    normalized=value.replace('\\','/').lstrip('/')
    if normalized=='data' or normalized.startswith('data/'):
        relative=normalized[4:].lstrip('/')
        path=(DATA/relative).resolve()
        if path!=DATA.resolve() and DATA.resolve() not in path.parents:raise ValueError('Unsafe data path')
        return path
    path=(ROOT/normalized).resolve()
    if path!=ROOT.resolve() and ROOT.resolve() not in path.parents:raise ValueError('Unsafe project path')
    return path
def dump(v:Any)->str:return json.dumps(v,ensure_ascii=False,separators=(',',':'))
def load(v:str|None,default:Any=None)->Any:
    if not v:return default
    return json.loads(v)

@contextmanager
def db():
    with _lock:
        con=sqlite3.connect(DB,timeout=30,check_same_thread=False);con.row_factory=sqlite3.Row;con.execute('PRAGMA foreign_keys=ON')
        try:yield con;con.commit()
        except:con.rollback();raise
        finally:con.close()

def init_db():
    schema=(ROOT/'server'/'schema.sql').read_text(encoding='utf-8')
    with db() as con:
        con.executescript(schema)
        project_columns={r['name'] for r in con.execute('PRAGMA table_info(projects)')}
        if 'base_version_id' not in project_columns:con.execute('ALTER TABLE projects ADD COLUMN base_version_id TEXT')
        columns={r['name'] for r in con.execute('PRAGMA table_info(refinement_jobs)')}
        for name,definition in (('cancel_requested','INTEGER NOT NULL DEFAULT 0'),('blender_version','TEXT'),('quality_report','TEXT')):
            if name not in columns:con.execute(f'ALTER TABLE refinement_jobs ADD COLUMN {name} {definition}')
        detail_columns={r['name'] for r in con.execute('PRAGMA table_info(detail_generation_jobs)')}
        for name,definition in (('current_step','INTEGER NOT NULL DEFAULT 0'),('total_steps','INTEGER NOT NULL DEFAULT 0'),('current_message','TEXT'),('logs_json',"TEXT NOT NULL DEFAULT '[]'")):
            if name not in detail_columns:con.execute(f'ALTER TABLE detail_generation_jobs ADD COLUMN {name} {definition}')

def rowdict(row:sqlite3.Row|None)->dict[str,Any]|None:
    if row is None:return None
    d=dict(row)
    for k in ('config_snapshot','metadata','checks','risks','quality_report','payload'):
        if k in d:d[k]=load(d[k],{} if k in ('metadata','quality_report','payload') else [])
    return d

def project_dir(project_id:str)->Path:
    if not re.fullmatch(r'prj_[a-f0-9]{16}',project_id):raise ValueError('Invalid project id')
    path=(DATA/'projects'/project_id).resolve();base=(DATA/'projects').resolve()
    if base not in path.parents:raise ValueError('Unsafe path')
    return path
