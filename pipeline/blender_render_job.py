"""Generic background GLB normalization, web export and four-view renderer."""
import argparse,json,sys
from pathlib import Path
import bpy
from mathutils import Vector

def args():
    raw=sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else []
    p=argparse.ArgumentParser();p.add_argument('--input',type=Path,required=True);p.add_argument('--output-dir',type=Path,required=True);p.add_argument('--web-glb',type=Path,required=True);return p.parse_args(raw)
def look(camera,target):camera.rotation_euler=(target-camera.location).to_track_quat('-Z','Y').to_euler()
def main():
    a=args();a.output_dir.mkdir(parents=True,exist_ok=True);a.web_glb.parent.mkdir(parents=True,exist_ok=True)
    bpy.ops.object.select_all(action='SELECT');bpy.ops.object.delete(use_global=False)
    bpy.ops.import_scene.gltf(filepath=str(a.input));meshes=[o for o in bpy.context.scene.objects if o.type=='MESH']
    if not meshes:raise RuntimeError('GLB contains no mesh objects')
    for o in meshes:o.select_set(True)
    mins=Vector((min(v for o in meshes for v in [c[0] for c in o.bound_box]),min(v for o in meshes for v in [c[1] for c in o.bound_box]),min(v for o in meshes for v in [c[2] for c in o.bound_box])))
    # Use evaluated world-space bounds for arbitrary generator orientation.
    points=[o.matrix_world@Vector(c) for o in meshes for c in o.bound_box];lo=Vector(tuple(min(p[i] for p in points) for i in range(3)));hi=Vector(tuple(max(p[i] for p in points) for i in range(3)));dims=hi-lo
    scale=4.0/max(dims.z,dims.y,dims.x,1e-5);center=(lo+hi)/2
    root=bpy.data.objects.new('NormalizedRoot',None);bpy.context.collection.objects.link(root)
    for o in meshes:o.parent=root
    root.scale=(scale,)*3;root.location=(-center.x*scale,-center.y*scale,-lo.z*scale)
    bpy.context.view_layer.update()
    bpy.ops.object.select_all(action='DESELECT');root.select_set(True)
    for o in meshes:o.select_set(True)
    bpy.context.view_layer.objects.active=root
    bpy.ops.export_scene.gltf(filepath=str(a.web_glb),export_format='GLB',use_selection=True,export_apply=True,export_yup=True,export_materials='EXPORT',export_image_format='AUTO')
    scene=bpy.context.scene;scene.render.engine='BLENDER_EEVEE';scene.render.resolution_x=768;scene.render.resolution_y=768;scene.render.resolution_percentage=100;scene.render.image_settings.file_format='PNG';scene.render.film_transparent=False
    scene.world.color=(0.018,0.025,0.035)
    bpy.ops.object.light_add(type='AREA',location=(4,-4,7));bpy.context.object.data.energy=1100;bpy.context.object.data.shape='DISK';bpy.context.object.data.size=5
    bpy.ops.object.light_add(type='AREA',location=(-4,1,5));bpy.context.object.data.energy=700;bpy.context.object.data.color=(0.35,0.5,1);bpy.context.object.data.size=4
    bpy.ops.object.camera_add();cam=bpy.context.object;scene.camera=cam;cam.data.lens=60;target=Vector((0,0,2))
    views={'front':(0,-8,2.3),'left-three-quarter':(-5.6,-5.6,2.7),'side':(-8,0,2.3),'back':(0,8,2.3)}
    for name,pos in views.items():cam.location=pos;look(cam,target);scene.render.filepath=str(a.output_dir/f'{name}.png');bpy.ops.render.render(write_still=True)
    stats={'schemaVersion':1,'status':'passed','input':str(a.input),'webGlb':str(a.web_glb),'objects':len(meshes),'vertices':sum(len(o.data.vertices) for o in meshes),'polygons':sum(len(o.data.polygons) for o in meshes),'renders':list(views)}
    (a.output_dir/'blender-report.json').write_text(json.dumps(stats,ensure_ascii=False,indent=2),encoding='utf-8');print('STUDIO_REPORT='+json.dumps(stats,ensure_ascii=False))
if __name__=='__main__':main()
