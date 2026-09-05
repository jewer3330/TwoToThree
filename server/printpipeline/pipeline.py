"""分模块（自动连通体拆分）+ AMS 上色（多色分区）执行器。

带**多主机故障转移**：按顺序尝试每个启用且在线的 GPU 主机（GPU-1→GPU-2→GPU-3…），
每台主机执行前设置超时（`timeout_seconds`），失败/超时自动切换下一台，全部失败才报错。
"""
from __future__ import annotations
import json, shutil
from pathlib import Path
from ..core import DATA
from ..backends import BackendError, bind_host, _rc, _marker
from ..gpu import hosts as gpu_hosts

SPLIT_SCRIPT='pipeline/blender_split_connected.py'
EXPORT_SCRIPT='pipeline/blender_export_multicolor_3mf.py'


def _online_hosts()->list[dict]:
    """启用且在线的 GPU 主机（按注册顺序）。"""
    return [h for h in gpu_hosts.list_hosts() if h.get('enabled') and h.get('status',{}).get('online')]

def run_on_hosts(fn, timeout_seconds:int=600, name:str='任务'):
    """在多台 GPU 主机上依次尝试执行 fn（fn 内部用线程绑定的 remote）。
    每台主机执行设超时；失败/超时换下一台。返回 (host_name, result)。
    全部失败抛 BackendError（含各主机错误摘要）。"""
    hosts=_online_hosts()
    if not hosts:
        raise BackendError(f'{name}需要在线 GPU 主机，但当前无可用主机（请检查 GPU 控制台）')
    errors=[]
    for h in hosts:
        try:
            bind_host(h)
            result=fn()
            return h.get('name') or h['host'],result
        except Exception as exc:
            errors.append(f"{h.get('name') or h['host']}: {str(exc)[:150]}")
        finally:
            bind_host(None)
    raise BackendError(f'{name}在所有 GPU 主机上均失败（超时保底已切换）: ' + '; '.join(errors))

def _split_on_host(input_glb:Path, out_dir:Path, max_parts:int, target_height_mm:float, timeout:int):
    from ..backends import remote
    from ..core import ROOT
    r=remote()
    if not r:raise BackendError('主机绑定失败')
    rc=_rc();marker=_marker();stag=r.stage(marker)
    # 输入（模型 + 分件脚本）经 prepare 下发：SSH 直传远端 stag；selfreg 放
    # pullbox 并在 run() 时由 agent fetch 到同路径 stag。统一走 r.join 的节点路径。
    split_script=ROOT/'pipeline'/'blender_split_connected.py'
    r.prepare(marker,[input_glb,split_script])
    rmodel=r.join(stag,input_glb.name);rscript=r.join(stag,split_script.name);rout=r.join(stag,'out')
    command=[rc['blender'],'--background','--factory-startup','--python',rscript,'--',
             '--input',rmodel,'--output-dir',rout,'--max-parts',str(max_parts),
             '--target-height-mm',str(target_height_mm)]
    r.run(command,lambda m:None,lambda:False,timeout=timeout,marker=stag)
    r.download_dir(rout,out_dir)
    r.cleanup(marker)
    report=out_dir/'split-report.json'
    if not report.exists():raise BackendError('Blender 未生成拆分报告')
    return json.loads(report.read_text(encoding='utf-8'))

def split_model(input_glb:Path, out_dir:Path, max_parts:int=12, target_height_mm:float=120, timeout_seconds:int=600):
    """带故障转移的拆分：GPU-1→GPU-2→GPU-3…，超时自动切换。返回 split-report 数据。"""
    _,data=run_on_hosts(lambda:_split_on_host(input_glb,out_dir,max_parts,target_height_mm,timeout_seconds),
                        timeout_seconds=timeout_seconds,name='分模块')
    parts_dir=out_dir/'parts'
    if (out_dir/'out'/'parts').exists():
        shutil.rmtree(parts_dir,ignore_errors=True);shutil.copytree(out_dir/'out'/'parts',parts_dir)
    return data

def _export_on_host(parts_dir:Path, colors:dict, output:Path, timeout:int):
    from ..backends import remote
    from ..core import ROOT
    r=remote()
    if not r:raise BackendError('主机绑定失败')
    rc=_rc();marker=_marker();stag=r.stage(marker)
    export_script=ROOT/'pipeline'/'blender_export_multicolor_3mf.py'
    colors_local=output.parent/'colors.json'
    colors_local.write_text(json.dumps(colors),encoding='utf-8')
    # parts STL 平铺下发到 stag（prepare→fetch）；导出脚本只 glob *.stl，
    # 把 --parts-dir 指到 stag 根即可同时兼容 selfreg(平铺) 与 SSH。
    stls=sorted(parts_dir.glob('*.stl'))
    r.prepare(marker,[export_script,colors_local,*stls])
    rscript=r.join(stag,export_script.name)
    rout=r.join(stag,'multicolor.3mf')
    command=[rc['blender'],'--background','--factory-startup','--python',rscript,'--',
             '--parts-dir',stag,'--colors-file',r.join(stag,colors_local.name),'--output',rout]
    r.run(command,lambda m:None,lambda:False,timeout=timeout,marker=stag)
    output.parent.mkdir(parents=True,exist_ok=True)
    r.download_compressed(rout,output)
    r.cleanup(marker)
    if not output.exists():raise BackendError('Blender 未生成 3MF')
    return output

def export_multicolor_3mf(parts_dir:Path, colors:dict[str,str], output:Path, timeout_seconds:int=600):
    """带故障转移的多色 3MF 导出。"""
    _,out=run_on_hosts(lambda:_export_on_host(parts_dir,colors,output,timeout_seconds),
                       timeout_seconds=timeout_seconds,name='多色 3MF 导出')
    return out

def assign_colors(job:dict, assignments:dict[str,str]):
    """assignments: {part_stl_name: '#RRGGBB'}。写入 job.color。"""
    job['color']['assignments']=assignments
    job['color']['status']='assigned'
    from . import jobs as jobs_mod
    jobs_mod.save_job(job)
    return job
