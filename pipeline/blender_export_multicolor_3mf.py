"""Blender 多色 3MF 导出脚本（AMS 多色分区）。

用法:
  blender --background --factory-startup --python blender_export_multicolor_3mf.py -- \
    --parts-dir out/parts --colors '{"part_001.stl":"#E53935",...}' --output multicolor.3mf

把每个部件 STL 导入并赋颜色材质（Principled BSDF），导出多对象 3MF（可被切片器识别为多色）。
"""
from __future__ import annotations
import argparse, json
from pathlib import Path

def cli():
    import sys
    raw=sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else []
    p=argparse.ArgumentParser()
    p.add_argument('--parts-dir',type=Path,required=True)
    p.add_argument('--colors',type=str,default='')     # JSON 字符串（可选）
    p.add_argument('--colors-file',type=Path,default=None)  # JSON 文件（推荐，避免命令行转义）
    p.add_argument('--output',type=Path,required=True)
    return p.parse_args(raw)

def hex_to_rgb(h:str)->tuple[float,float,float,float]:
    h=h.lstrip('#')
    return (int(h[0:2],16)/255,int(h[2:4],16)/255,int(h[4:6],16)/255,1.0)

def main():
    import bpy
    from mathutils import Vector
    a=cli()
    bpy.ops.wm.read_factory_settings(use_empty=True)
    # factory-startup 下 3MF 导出插件默认禁用，需显式启用
    try:bpy.ops.preferences.addon_enable(module='io_scene_3mf')
    except Exception:pass
    if a.colors_file is not None:
        colors=json.loads(a.colors_file.read_text(encoding='utf-8'))
    else:
        colors=json.loads(a.colors)
    stls=sorted((a.parts_dir).glob('*.stl'))
    if not stls:raise RuntimeError('parts 目录无 STL')
    a.output.parent.mkdir(parents=True,exist_ok=True)
    created=0
    for stl in stls:
        name=stl.name
        bpy.ops.wm.stl_import(filepath=str(stl))
        obj=bpy.context.active_object
        if obj is None:continue
        obj.name=f'part_{created:03d}_{name}'
        hexc=colors.get(name,'#9E9E9E')
        mat=bpy.data.materials.new(f'M_{name}')
        mat.use_nodes=True
        bsdf=mat.node_tree.nodes.get('Principled BSDF')
        if bsdf:bsdf.inputs['Base Color'].default_value=hex_to_rgb(hexc)
        if obj.data.materials:obj.data.materials[0]=mat
        else:obj.data.materials.append(mat)
        # 居中到原点（3MF 打印友好）
        bpy.ops.object.origin_set(type='ORIGIN_GEOMETRY',center='BOUNDS')
        center=obj.matrix_world @ (Vector(obj.bound_box[0])+Vector(obj.bound_box[6]))/2
        obj.location-=center
        created+=1
    if not created:raise RuntimeError('没有导入任何部件')
    # Blender 5.2: export_mesh.threedsmf 改名 wm.threedsmf_export
    if hasattr(bpy.ops.wm,'threedsmf_export'):bpy.ops.wm.threedsmf_export(filepath=str(a.output))
    else:bpy.ops.export_mesh.threedsmf(filepath=str(a.output),use_selection=False)
    print(f'3MF_EXPORT_OK parts={created} size={a.output.stat().st_size}')

if __name__=='__main__':
    main()
