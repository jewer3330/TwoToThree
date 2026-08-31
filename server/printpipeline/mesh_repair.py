"""打印网格修复：3D 生成模型底部开口/非流形导致切片失败时，用远程 pymeshlab/Blender 修复。

策略：生成模型底部常开口（0.2-1mm 空层被切片器判 fatal）。
1. pymeshlab 修复（补洞/去重/非流形）
2. 仍不行 → Blender 布尔并集加底座（生成单个封闭 mesh）
"""
from __future__ import annotations
import json
from pathlib import Path
from ..backends import BackendError, remote, _rc, _marker

REPAIR_SCRIPT='pipeline/print_mesh_repair.py'

def repair_mesh_remote(stl:Path, output:Path, add_base:bool=True, base_thickness:float=3.0, pad:float=2.0):
    """在 GPU 节点修复 STL（pymeshlab 补洞 + 可选 Blender 布尔加底座），回传修复版。"""
    r=remote()
    if not r:raise BackendError('无可用远程主机（网格修复需要 GPU 节点）')
    rc=_rc();marker=_marker();stag=r.stage(marker)
    r.prepare(marker,[stl])
    r.upload(Path('/app/pipeline/print_mesh_repair.py'),f'{stag}\\repair_script.py')
    rsrc=f'{stag}\\{stl.name}';rout=f'{stag}\\repaired.stl'
    cmd=[rc['python'],f'{stag}\\repair_script.py','--input',rsrc,'--output',rout,
         '--add-base','1' if add_base else '0','--base-thickness',str(base_thickness),'--pad',str(pad)]
    r.run(cmd,lambda m:None,lambda:False,timeout=1200,marker=stag)
    output.parent.mkdir(parents=True,exist_ok=True)
    r.download_file(rout,output)
    r.cleanup(marker)
    if not output.exists() or output.stat().st_size<1000:raise BackendError('网格修复未生成有效 STL')
    return output
