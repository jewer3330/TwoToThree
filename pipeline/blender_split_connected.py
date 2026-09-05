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
import argparse, json
from pathlib import Path

def cli():
    import sys
    raw=sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else []
    p=argparse.ArgumentParser()
    p.add_argument('--input',type=Path,required=True)
    p.add_argument('--output-dir',type=Path,required=True)
    p.add_argument('--max-parts',type=int,default=12)
    p.add_argument('--min-volume',type=float,default=0.001)
    p.add_argument('--target-height-mm',type=float,default=120.0)
    return p.parse_args(raw)

def normalization_plan(lo,hi,target_height_mm:float):
    """Return one assembly-wide millimetre transform from an axis-aligned bbox."""
    if len(lo)!=3 or len(hi)!=3:raise ValueError('包围盒必须包含三个轴')
    height=float(hi[2])-float(lo[2])
    if height<=1e-9:raise ValueError('模型 Z 高度为 0，无法归一化')
    target=float(target_height_mm)
    if not 10<=target<=500:raise ValueError('目标高度必须在 10–500 mm 之间')
    center=((float(lo[0])+float(hi[0]))/2,(float(lo[1])+float(hi[1]))/2)
    scale=target/height
    offset=(-center[0],-center[1],-float(lo[2]))
    normalized_lo=tuple((float(lo[i])+offset[i])*scale for i in range(3))
    normalized_hi=tuple((float(hi[i])+offset[i])*scale for i in range(3))
    return {'scale':scale,'offset':offset,'sourceBounds':{'min':tuple(map(float,lo)),'max':tuple(map(float,hi))},
            'normalizedBounds':{'min':normalized_lo,'max':normalized_hi},'targetHeightMm':target}

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
    单对象多连通体时才 LOOSE 分离——但大模型（>150k 面）LOOSE 极慢且常是
    单件角色，直接视为单部件。小模型才 LOOSE（避免 Blender 5.2 拆零碎面片）。
    """
    import bpy
    scene=bpy.context.scene
    mesh_objs=[o for o in scene.objects if o.type=='MESH']
    total_faces=sum(len(o.data.polygons) for o in mesh_objs)
    if len(mesh_objs)<=1 and mesh_objs and total_faces<=150000:
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

def normalize_assembly(parts,target_height_mm:float):
    """Bake world transforms and apply one shared print-space transform."""
    import bpy
    from mathutils import Matrix,Vector
    if not parts:raise RuntimeError('模型没有可归一化的网格部件')
    for part in parts:
        obj=part['object']
        obj.data=obj.data.copy()
        obj.data.transform(obj.matrix_world)
        obj.matrix_world=Matrix.Identity(4)
    bpy.context.view_layer.update()
    points=[part['object'].matrix_world@Vector(c) for part in parts for c in part['object'].bound_box]
    lo=tuple(min(v[i] for v in points) for i in range(3))
    hi=tuple(max(v[i] for v in points) for i in range(3))
    plan=normalization_plan(lo,hi,target_height_mm)
    transform=Matrix.Scale(plan['scale'],4)@Matrix.Translation(Vector(plan['offset']))
    for part in parts:
        obj=part['object'];obj.data.transform(transform);obj.data.update()
    bpy.context.view_layer.update()
    for part in parts:
        obj=part['object'];bb=[obj.matrix_world@Vector(c) for c in obj.bound_box]
        part['dims']=[max(c[i] for c in bb)-min(c[i] for c in bb) for i in range(3)]
        part['volume']=part['dims'][0]*part['dims'][1]*part['dims'][2]
    return plan

def render_preview(obj,path:Path,size:int=256):
    """Render a centered, automatically framed three-quarter preview."""
    import bpy
    from mathutils import Vector
    for o in bpy.context.scene.objects:
        o.hide_set(o!=obj);o.hide_render=o!=obj;o.select_set(False)
    bpy.context.view_layer.objects.active=obj
    obj.select_set(True)
    scene=bpy.context.scene
    if 'Camera' not in scene.objects:
        cam=bpy.data.cameras.new('Cam');cam_obj=bpy.data.objects.new('Camera',cam);scene.collection.objects.link(cam_obj)
    cam_obj=scene.objects['Camera']
    bb=[obj.matrix_world@Vector(c) for c in obj.bound_box]
    lo=Vector(tuple(min(c[i] for c in bb) for i in range(3)))
    hi=Vector(tuple(max(c[i] for c in bb) for i in range(3)))
    center=(lo+hi)/2;extent=hi-lo;radius=max(extent)*2.5
    direction=Vector((1.0,-1.25,0.75)).normalized()
    cam_obj.location=center+direction*radius
    cam_obj.rotation_euler=(center-cam_obj.location).to_track_quat('-Z','Y').to_euler()
    cam_obj.data.type='ORTHO';cam_obj.data.clip_start=0.01;cam_obj.data.clip_end=max(10000,radius*5)
    bpy.context.view_layer.update()
    inverse=cam_obj.matrix_world.inverted();projected=[inverse@c for c in bb]
    width=max(c.x for c in projected)-min(c.x for c in projected)
    height=max(c.y for c in projected)-min(c.y for c in projected)
    cam_obj.data.ortho_scale=max(width,height,1e-6)*1.25
    scene.render.engine='BLENDER_WORKBENCH'
    scene.display.shading.light='STUDIO'
    scene.display.shading.color_type='MATERIAL'
    scene.render.resolution_x=size;scene.render.resolution_y=size
    scene.render.image_settings.file_format='PNG'
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
    normalization=normalize_assembly(parts,a.target_height_mm)
    out_dir=a.output_dir/'parts';out_dir.mkdir(exist_ok=True)
    report=[]
    for i,p in enumerate(parts,1):
        idx=f'{i:03d}'
        stl=out_dir/f'part_{idx}.stl'
        png=out_dir/f'part_{idx}.png'
        obj=p['object']
        bpy.context.view_layer.objects.active=obj
        bpy.ops.object.select_all(action='DESELECT')
        obj.select_set(True)
        # Blender 5.2: export_mesh.stl 改名 wm.stl_export（与导入一致）
        if hasattr(bpy.ops.wm,'stl_export'):bpy.ops.wm.stl_export(filepath=str(stl),export_selected_objects=True)
        else:bpy.ops.export_mesh.stl(filepath=str(stl),use_selection=True)
        obj.select_set(False)
        try:render_preview(obj,png)
        except Exception:
            # preview 失败时生成纯色占位 PNG，避免前端破图
            try:
                import struct,zlib
                w=h=128;white=b'\xff'*3
                raw=b''.join(b'\x00'+white*w for _ in range(h))
                data=zlib.compress(raw)
                def chunk(t,d):return struct.pack('>I',len(d))+t+d+struct.pack('>I',zlib.crc32(t+d)&0xffffffff)
                png.write_bytes(b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',w,h,8,2,0,0,0))+chunk(b'IDAT',data)+chunk(b'IEND',b''))
            except Exception:pass
        report.append({'index':i,'name':p['name'],'stl':stl.name,'preview':png.name,
                       'dims':[round(v,3) for v in p['dims']],'volume':round(p['volume'],4)})
    (a.output_dir/'split-report.json').write_text(json.dumps({'schemaVersion':2,'unit':'millimeter','partCount':len(report),'normalization':normalization,'parts':report},ensure_ascii=False,indent=2),encoding='utf-8')
    print(f'SPLIT_OK parts={len(report)}')

if __name__=='__main__':
    main()
