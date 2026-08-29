"""分模块（自动连通体拆分）+ AMS 上色（多色分区）执行器。

复用 backends 的远程执行层：Blender 在 GPU 节点跑拆分脚本，结果回传。
"""
from __future__ import annotations
import json, shutil
from pathlib import Path
from ..core import DATA
from ..backends import BackendError, remote, _rc, _marker, _flatten

SPLIT_SCRIPT='pipeline/blender_split_connected.py'

def _resolve_local_script():
    """拆分脚本在容器内固定路径。"""
    from pathlib import Path as P
    return P('/app/pipeline/blender_split_connected.py')

def split_model(input_glb:Path, out_dir:Path, max_parts:int=12):
    """远程 Blender 连通体拆分。返回 split-report.json 解析结果。"""
    r=remote()
    if not r:
        raise BackendError('无可用远程主机（分模块需要 GPU 节点 Blender）')
    rc=_rc();marker=_marker();stag=r.stage(marker)
    # 上传模型 + 脚本
    r.prepare(marker,[input_glb])
    try:
        r.cmd(['powershell','-NoProfile','-Command',f"New-Item -ItemType Directory -Force -Path {stag} | Out-Null"])
        r.upload(_resolve_local_script(),f'{stag}\\split_script.py')
    except Exception as exc:
        raise BackendError(f'上传拆分脚本失败: {exc}')
    rmodel=f'{stag}\\{input_glb.name}';rout=f'{stag}\\out'
    command=[rc['blender'],'--background','--factory-startup','--python',f'{stag}\\split_script.py','--',
             '--input',rmodel,'--output-dir',rout,'--max-parts',str(max_parts)]
    r.run(command,lambda m:None,lambda:False,timeout=1800,marker=stag)
    # 回传结果
    r.download_dir(rout,out_dir)
    r.cleanup(marker)
    report=out_dir/'split-report.json'
    if not report.exists():raise BackendError('Blender 未生成拆分报告')
    data=json.loads(report.read_text(encoding='utf-8'))
    # 展平 parts 子目录
    parts_dir=out_dir/'parts'
    if (out_dir/'out'/'parts').exists():
        shutil.rmtree(parts_dir,ignore_errors=True);shutil.copytree(out_dir/'out'/'parts',parts_dir)
    return data

def assign_colors(job:dict, assignments:dict[str,str]):
    """assignments: {part_stl_name: '#RRGGBB'}。写入 job.color。"""
    job['color']['assignments']=assignments
    job['color']['status']='assigned'
    from . import jobs as jobs_mod
    jobs_mod.save_job(job)
    return job
