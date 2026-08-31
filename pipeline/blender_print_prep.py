"""打印预处理：自动封底/加底座（3D 打印需要封闭网格）。

生成的 3D 角色底部通常开口，直接切片会报"空层"。此脚本在 Blender 中：
1. 导入模型，找出底部包围盒
2. 添加一个薄底座（覆盖底部 XY 范围，厚 base_thickness）
3. 布尔并集合并，导出 STL（封闭网格，可直接打印）
"""
from __future__ import annotations
import argparse, sys
from pathlib import Path

def cli():
    raw=sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else []
    p=argparse.ArgumentParser()
    p.add_argument('--input',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--base-thickness',type=float,default=3.0)  # 底座厚度 mm
    p.add_argument('--pad',type=float,default=2.0)             # 底座外扩 mm
    return p.parse_args(raw)

def main():
    import bpy
    from mathutils import Vector
    a=cli()
    bpy.ops.wm.read_factory_settings(use_empty=True)
    ext=a.input.suffix.lower()
    if ext=='.glb' or ext=='.gltf':bpy.ops.import_scene.gltf(filepath=str(a.input))
    elif ext=='.stl':bpy.ops.wm.stl_import(filepath=str(a.input))
    else:raise RuntimeError(f'不支持格式 {ext}')
    # 收集 mesh 并合并
    meshes=[o for o in bpy.context.scene.objects if o.type=='MESH']
    if not meshes:raise RuntimeError('无网格')
    # 计算整体包围盒（世界坐标）
    mins=[];maxs=[]
    for o in meshes:
        for c in o.bound_box:
            w=o.matrix_world @ Vector(c)
            mins.append(w);maxs.append(w)
    lo=Vector((min(v.x for v in mins),min(v.y for v in mins),min(v.z for v in mins)))
    hi=Vector((max(v.x for v in maxs),max(v.y for v in maxs),max(v.z for v in maxs)))
    # 底座：略大于底部 XY，厚 base_thickness，底边与模型底平齐
    bx=hi.x-lo.x+2*a.pad;by=hi.y-lo.y+2*a.pad
    cx=(hi.x+lo.x)/2;cy=(hi.y+lo.y)/2
    bpy.ops.mesh.primitive_cube_add(size=1,location=(cx,cy,lo.z-a.base_thickness/2))
    base=bpy.context.active_object
    base.scale=(bx/2,by/2,a.base_thickness/2)
    bpy.ops.object.transform_apply(location=False,rotation=False,scale=True)
    # 选中模型 + 底座，布尔并集
    bpy.ops.object.select_all(action='DESELECT')
    for o in meshes:o.select_set(True)
    base.select_set(True)
    bpy.context.view_layer.objects.active=base
    bpy.ops.object.join()
    # 导出 STL
    a.output.parent.mkdir(parents=True,exist_ok=True)
    if hasattr(bpy.ops.wm,'stl_export'):bpy.ops.wm.stl_export(filepath=str(a.output))
    else:bpy.ops.export_mesh.stl(filepath=str(a.output))
    print(f'PREP_OK base={a.base_thickness}mm output={a.output.stat().st_size}B')

if __name__=='__main__':
    main()
