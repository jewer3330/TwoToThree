"""打印网格修复脚本（GPU 节点执行）：
1. pymeshlab 补洞/清理（生成模型常非流形/底部开口）
2. add_base 时用 Blender 布尔并集加扁平底座 → 单个封闭 mesh（切片器不再报空层）
"""
from __future__ import annotations
import argparse, sys
from pathlib import Path

def cli():
    raw=sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else []
    p=argparse.ArgumentParser()
    p.add_argument('--input',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--add-base',type=str,default='1')
    p.add_argument('--base-thickness',type=float,default=3.0)
    p.add_argument('--pad',type=float,default=2.0)
    return p.parse_args(raw)

def pymeshlab_repair(src:Path,dst:Path):
    import pymeshlab
    ms=pymeshlab.MeshSet();ms.load_new_mesh(str(src))
    for op in ('meshing_repair_non_manifold_edges','meshing_close_holes','meshing_remove_duplicate_faces','meshing_remove_unreferenced_vertices'):
        try:getattr(ms,op)()
        except Exception:pass
    ms.save_current_mesh(str(dst))
    return ms.current_mesh().vertex_number()

def add_base_stl(model:Path, base_stl:Path, thickness:float, pad:float):
    """Blender 布尔并集：模型 ∪ 底座 → 单个封闭 STL。"""
    import bpy
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.wm.stl_import(filepath=str(model))
    doll=bpy.context.active_object
    # 计算模型底部包围盒
    bb=[doll.matrix_world @ c for c in doll.bound_box]
    lo=[min(c[i] for c in bb) for i in range(3)]
    hi=[max(c[i] for c in bb) for i in range(3)]
    cx=(hi[0]+lo[0])/2;cy=(hi[1]+lo[1])/2
    bx=hi[0]-lo[0]+2*pad;by=hi[1]-lo[1]+2*pad
    bpy.ops.mesh.primitive_cube_add(size=1,location=(cx,cy,lo[2]-thickness/2))
    base=bpy.context.active_object;base.scale=(bx/2,by/2,thickness/2)
    bpy.ops.object.transform_apply(location=False,rotation=False,scale=True)
    mod=base.modifiers.new('bool','BOOLEAN');mod.operation='UNION';mod.object=doll
    bpy.context.view_layer.objects.active=base
    bpy.ops.object.modifier_apply(modifier='bool')
    bpy.ops.object.select_all(action='DESELECT');base.select_set(True)
    bpy.context.view_layer.objects.active=base
    if hasattr(bpy.ops.wm,'stl_export'):bpy.ops.wm.stl_export(filepath=str(base_stl))
    else:bpy.ops.export_mesh.stl(filepath=str(base_stl))
    return len(base.data.vertices)

def main():
    a=cli()
    tmp=a.output.with_suffix('.repaired.stl')
    verts=pymeshlab_repair(a.input,tmp)
    print(f'PML_REPAIR verts={verts}')
    if a.add_base=='1':
        verts2=add_base_stl(tmp,a.output,a.base_thickness,a.pad)
        print(f'BASE_ADDED verts={verts2} size={a.output.stat().st_size}')
    else:
        tmp.replace(a.output)
        print(f'REPAIR_ONLY size={a.output.stat().st_size}')

if __name__=='__main__':
    main()
