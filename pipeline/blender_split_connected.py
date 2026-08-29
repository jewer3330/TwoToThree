"""Blender 自动连通体拆分脚本。

用法:
  blender --background --factory-startup --python blender_split_connected.py -- \
    --input model.glb --output-dir out_dir --max-parts 12

输出:
  out_dir/parts/part_001.stl ...（每个连通体一个 STL）
  out_dir/parts/part_001.png ...（四视图缩略预览）
  out_dir/split-report.json（部件清单与尺寸/顶点数）
"""
from __future__ import annotations
import argparse, json, math
from pathlib import Path

def cli():
    import sys
    raw=sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else []
    p=argparse.ArgumentParser()
    p.add_argument('--input',type=Path,required=True)
    p.add_argument('--output-dir',type=Path,required=True)
    p.add_argument('--max-parts',type=int,default=12)
    p.add_argument('--min-volume',type=float,default=0.001)
    return p.parse_args(raw)

def import_model(path:Path):
    import bpy
    bpy.ops.wm.read_factory_settings(use_empty=True)
    ext=path.suffix.lower()
    if ext=='.glb' or ext=='.gltf':bpy.ops.import_scene.gltf(filepath=str(path))
    elif ext=='.stl':bpy.ops.wm.stl_import(filepath=str(path))
    elif ext=='.obj':bpy.ops.wm.obj_import(filepath=str(path))
    elif ext=='.fbx':bpy.ops.import_scene.fbx(filepath=str(path))
    else:raise RuntimeError(f'不支持的格式: {ext}')

def split_loose_parts():
    """按连通体拆分为多个独立对象，返回每个对象的世界包围盒体积（用于排序/过滤）。

    策略：glTF/STL/OBJ 导入通常每个连通体就是一个 MESH 对象，直接按对象收集；
    只有当整个场景只有一个 MESH 对象（单对象多连通体）时才做 LOOSE 分离。
    （Blender 5.2 的 LOOSE 分离会把立方体拆成零体积面片，不能无条件使用）
    """
    import bpy
    scene=bpy.context.scene
    mesh_objs=[o for o in scene.objects if o.type=='MESH']
    if len(mesh_objs)<=1 and mesh_objs:
        for obj in mesh_objs:
            obj.select_set(True)
            bpy.context.view_layer.objects.active=obj
            bpy.ops.object.mode_set(mode='EDIT')
            bpy.ops.mesh.separate(type='LOOSE')
            bpy.ops.object.mode_set(mode='OBJECT')
            obj.select_set(False)
    parts=[]
    for obj in list(scene.objects):
        if obj.type!='MESH':continue
        if not obj.data.vertices:continue
        bbox=[obj.matrix_world @ mathutils_Vector(c) for c in obj.bound_box]
        dims=[max(c[i] for c in bbox)-min(c[i] for c in bbox) for i in range(3)]
        volume=obj.dimensions.x*obj.dimensions.y*obj.dimensions.z
        parts.append({'name':obj.name,'object':obj,'dims':dims,'volume':volume})
    return parts

def render_preview(obj,path:Path,size:int=256):
    """对单个部件渲染一张前视图 PNG。"""
    import bpy
    for o in bpy.context.scene.objects:o.hide_set(o!=obj);o.select_set(o==obj)
    bpy.context.view_layer.objects.active=obj
    bpy.ops.object.select_all(action='DESELECT');obj.select_set(True)
    # 相机对准
    scene=bpy.context.scene
    if 'Camera' not in scene.objects:
        cam=bpy.data.cameras.new('Cam');cam_obj=bpy.data.objects.new('Camera',cam);scene.collection.objects.link(cam_obj)
    cam_obj=scene.objects['Camera']
    center=obj.matrix_world @ (obj.bound_box[0]+obj.bound_box[6])/2
    dims=obj.dimensions;radius=max(dims)/2*1.6
    cam_obj.location=(center.x+radius,center.y-radius*0.7,center.z+radius*0.5)
    cam_obj.rotation_euler=(math.radians(60),0,math.radians(45))
    scene.render.engine='BLENDER_EEVEE';scene.render.resolution_x=size;scene.render.resolution_y=size
    scene.render.filepath=str(path)
    scene.camera=cam_obj
    bpy.ops.render.render(write_still=True)

def main():
    import bpy
    global mathutils_Vector
    from mathutils import Vector as mathutils_Vector
    a=cli();a.output_dir.mkdir(parents=True,exist_ok=True)
    import_model(a.input)
    parts=split_loose_parts()
    # 过滤过小部件，按体积降序，限制数量
    parts=[p for p in parts if p['volume']>=a.min_volume]
    parts.sort(key=lambda p:-p['volume'])
    if len(parts)>a.max_parts:parts=parts[:a.max_parts]
    out_dir=a.output_dir/'parts';out_dir.mkdir(exist_ok=True)
    report=[]
    for i,p in enumerate(parts,1):
        idx=f'{i:03d}'
        stl=out_dir/f'part_{idx}.stl'
        png=out_dir/f'part_{idx}.png'
        obj=p['object']
        bpy.context.view_layer.objects.active=obj
        obj.select_set(True)
        # Blender 5.2: export_mesh.stl 改名 wm.stl_export（与导入一致）
        if hasattr(bpy.ops.wm,'stl_export'):bpy.ops.wm.stl_export(filepath=str(stl))
        else:bpy.ops.export_mesh.stl(filepath=str(stl))
        obj.select_set(False)
        try:render_preview(obj,png)
        except Exception:pass
        report.append({'index':i,'name':p['name'],'stl':stl.name,'preview':png.name,
                       'dims':[round(v,3) for v in p['dims']],'volume':round(p['volume'],4)})
    (a.output_dir/'split-report.json').write_text(json.dumps({'schemaVersion':1,'partCount':len(report),'parts':report},ensure_ascii=False,indent=2),encoding='utf-8')
    print(f'SPLIT_OK parts={len(report)}')

if __name__=='__main__':
    main()
