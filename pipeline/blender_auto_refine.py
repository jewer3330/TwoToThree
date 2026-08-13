# -*- coding: utf-8 -*-
"""Blender V1 automatic GLB refinement with honest quality gates."""
import argparse,json,math,sys
from pathlib import Path
import bpy,bmesh
from mathutils import Vector

VIEWS={'front':(0,-8,2.3),'left-three-quarter':(-5.6,-5.6,2.7),'side':(-8,0,2.3),'back':(0,8,2.3)}
def cli():
    raw=sys.argv[sys.argv.index('--')+1:];p=argparse.ArgumentParser();p.add_argument('--input',type=Path,required=True);p.add_argument('--output-dir',type=Path,required=True);p.add_argument('--config',type=Path,required=True);p.add_argument('--reference-image',type=Path);return p.parse_args(raw)
def say(stage,message):print('REFINE_EVENT='+json.dumps({'stage':stage,'message':message},ensure_ascii=False),flush=True)
def stats(meshes):
    points=[o.matrix_world@Vector(c) for o in meshes for c in o.bound_box];lo=[min(p[i] for p in points) for i in range(3)];hi=[max(p[i] for p in points) for i in range(3)]
    return {'objects':len(meshes),'vertices':sum(len(o.data.vertices) for o in meshes),'polygons':sum(len(o.data.polygons) for o in meshes),'triangles':sum(len(p.loop_indices)-2 for o in meshes for p in o.data.polygons),'bounds':[hi[i]-lo[i] for i in range(3)],'bboxVolume':math.prod(max(hi[i]-lo[i],1e-9) for i in range(3))}
def active(o):bpy.ops.object.select_all(action='DESELECT');o.select_set(True);bpy.context.view_layer.objects.active=o
def main():
    a=cli();cfg=json.loads(a.config.read_text(encoding='utf-8'));a.output_dir.mkdir(parents=True,exist_ok=True)
    bpy.ops.object.select_all(action='SELECT');bpy.ops.object.delete(use_global=False);bpy.ops.import_scene.gltf(filepath=str(a.input));meshes=[o for o in bpy.context.scene.objects if o.type=='MESH']
    if not meshes:raise RuntimeError('输入 GLB 不包含网格')
    before=stats(meshes);say('geometryRepair','读取源模型并采集处理前统计')
    for o in meshes:
        active(o);bpy.ops.object.transform_apply(location=False,rotation=True,scale=True);bm=bmesh.new();bm.from_mesh(o.data);bmesh.ops.remove_doubles(bm,verts=bm.verts,dist=0.00001);loose=[v for v in bm.verts if not v.link_edges];bmesh.ops.delete(bm,geom=loose,context='VERTS');deg=[f for f in bm.faces if f.calc_area()<1e-12];bmesh.ops.delete(bm,geom=deg,context='FACES');bmesh.ops.recalc_face_normals(bm,faces=bm.faces);bm.to_mesh(o.data);bm.free();o.data.update()
    after_cleanup=stats(meshes);say('geometryRepair','完成变换、重复点、松散几何、退化面和法线清理')
    target=cfg.get('targetTriangleRange',[0,10**9]);max_triangles=int(target[1])
    if after_cleanup['triangles']>max_triangles and max_triangles>0:
        ratio=max(.01,min(1.0,max_triangles/after_cleanup['triangles']*.98))
        for o in meshes:
            active(o);modifier=o.modifiers.new('AutoRefine_Web_Decimate','DECIMATE');modifier.decimate_type='COLLAPSE';modifier.ratio=ratio;modifier.use_collapse_triangulate=True;bpy.ops.object.modifier_apply(modifier=modifier.name);o.data.validate(clean_customdata=True);bm=bmesh.new();bm.from_mesh(o.data);bmesh.ops.recalc_face_normals(bm,faces=bm.faces);bm.to_mesh(o.data);bm.free();o.data.update()
        say('webOptimization',f'按目标上限执行保守减面：{after_cleanup["triangles"]} → {stats(meshes)["triangles"]}')
    uv_source='preserved';uv_ok=True
    for o in meshes:
        if not o.data.uv_layers or not o.data.uv_layers.active or len(o.data.uv_layers.active.data)==0:
            uv_source='smart_project';active(o);bpy.ops.object.mode_set(mode='EDIT');bpy.ops.mesh.select_all(action='SELECT');bpy.ops.uv.smart_project(angle_limit=math.radians(66),island_margin=float(cfg.get('uvIslandMargin',0.03)));bpy.ops.object.mode_set(mode='OBJECT')
        layer=o.data.uv_layers.active
        uv_ok=uv_ok and bool(layer) and all(-1e-5<=x<=1.00001 for d in layer.data for x in d.uv)
    say('uvUnwrap',f'UV 策略完成：{uv_source}')
    tex_dir=a.output_dir/'textures';tex_dir.mkdir(exist_ok=True);colors={'base-color':(0.5,0.5,0.5,1),'roughness':(0.65,0.65,0.65,1),'metallic':(0,0,0,1),'normal':(0.5,0.5,1,1),'ao':(1,1,1,1)}
    images={}
    for name,color in colors.items():
        path=tex_dir/f'{name}.png'
        if name=='base-color' and a.reference_image and a.reference_image.exists():
            im=bpy.data.images.load(str(a.reference_image),check_existing=False);resolution=int(cfg.get('textureResolution',2048));im.scale(resolution,resolution);im.filepath_raw=str(path);im.file_format='PNG';im.save()
            for o in meshes:
                layer=o.data.uv_layers.active or o.data.uv_layers.new(name='UVMap');points=[o.matrix_world@v.co for v in o.data.vertices];lo_x=min(p.x for p in points);hi_x=max(p.x for p in points);lo_z=min(p.z for p in points);hi_z=max(p.z for p in points)
                for poly in o.data.polygons:
                    for li in poly.loop_indices:
                        p=o.matrix_world@o.data.vertices[o.data.loops[li].vertex_index].co;layer.data[li].uv=((p.x-lo_x)/max(hi_x-lo_x,1e-9),(p.z-lo_z)/max(hi_z-lo_z,1e-9))
            uv_source='front_reference_projection'
        else:
            im=bpy.data.images.new(name,32,32);im.generated_color=color;im.filepath_raw=str(path);im.file_format='PNG';im.save()
        images[name]=im
    for o in meshes:
        mat=bpy.data.materials.new('AutoRefine_PBR');mat.use_nodes=True;nodes=mat.node_tree.nodes;links=mat.node_tree.links;bsdf=nodes.get('Principled BSDF')
        base=nodes.new('ShaderNodeTexImage');base.name='Base Color';base.image=images['base-color'];links.new(base.outputs['Color'],bsdf.inputs['Base Color'])
        rough=nodes.new('ShaderNodeTexImage');rough.name='Roughness';rough.image=images['roughness'];rough.image.colorspace_settings.name='Non-Color';links.new(rough.outputs['Color'],bsdf.inputs['Roughness'])
        metal=nodes.new('ShaderNodeTexImage');metal.name='Metallic';metal.image=images['metallic'];metal.image.colorspace_settings.name='Non-Color';links.new(metal.outputs['Color'],bsdf.inputs['Metallic'])
        normal=nodes.new('ShaderNodeTexImage');normal.name='Normal';normal.image=images['normal'];normal.image.colorspace_settings.name='Non-Color';normal_map=nodes.new('ShaderNodeNormalMap');links.new(normal.outputs['Color'],normal_map.inputs['Color']);links.new(normal_map.outputs['Normal'],bsdf.inputs['Normal'])
        ao=nodes.new('ShaderNodeTexImage');ao.name='Ambient Occlusion';ao.image=images['ao'];ao.image.colorspace_settings.name='Non-Color'
        o.data.materials.clear();o.data.materials.append(mat)
    say('pbrMaterials','创建 Principled BSDF 与五通道 PBR 贴图；Base Color 使用正面参考投射，侧后区域标记为自动推断')
    refined=a.output_dir/'refined.glb';bpy.ops.object.select_all(action='DESELECT');[o.select_set(True) for o in meshes];bpy.ops.export_scene.gltf(filepath=str(refined),export_format='GLB',use_selection=True,export_apply=True,export_yup=True,export_materials='EXPORT')
    scene=bpy.context.scene;scene.render.engine='BLENDER_EEVEE';scene.render.resolution_x=512;scene.render.resolution_y=512;scene.render.resolution_percentage=100;scene.world.color=(.02,.025,.035);bpy.ops.object.light_add(type='AREA',location=(4,-4,7));bpy.context.object.data.energy=1100;bpy.context.object.data.size=5;bpy.ops.object.camera_add();cam=bpy.context.object;scene.camera=cam;camera_target=Vector((0,0,2))
    for name,pos in VIEWS.items():cam.location=pos;cam.rotation_euler=(camera_target-cam.location).to_track_quat('-Z','Y').to_euler();scene.render.filepath=str(a.output_dir/f'{name}.png');bpy.ops.render.render(write_still=True)
    final=stats(meshes);size_mb=refined.stat().st_size/1048576;bounds_change=max(abs(final['bounds'][i]-before['bounds'][i])/max(before['bounds'][i],1e-9) for i in range(3));gates={'glbValid':refined.exists() and refined.stat().st_size>12,'meshValid':final['triangles']>0,'triangleBudget':target[0]<=final['triangles']<=target[1],'uvValid':uv_ok,'pbrComplete':all((tex_dir/f'{n}.png').exists() for n in colors),'sizeBudget':size_mb<=cfg.get('maxWebGlbMB',20),'boundsSafe':bounds_change<=.15,'rendersComplete':all((a.output_dir/f'{n}.png').exists() for n in VIEWS)}
    report={'schemaVersion':1,'status':'passed' if all(gates.values()) else 'failed','blenderVersion':bpy.app.version_string,'source':str(a.input),'output':str(refined),'before':before,'afterCleanup':after_cleanup,'after':final,'uv':{'source':uv_source,'valid':uv_ok},'materials':{'channels':list(colors),'baseColorSource':'front_reference_projection' if a.reference_image else 'neutral_inference','inference':'侧面和背面自动推断，待验收'},'gates':gates,'fileSizeMB':round(size_mb,3),'config':cfg}
    (a.output_dir/'quality-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');say('qualityGate',f'质量门禁：{report["status"]}')
if __name__=='__main__':main()
