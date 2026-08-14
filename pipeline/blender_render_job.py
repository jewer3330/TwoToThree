"""Normalize a GLB, optionally apply multi-view projected color, export and render."""
import argparse,json,sys
from pathlib import Path
import bpy
from mathutils import Vector

def args():
    raw=sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else []
    p=argparse.ArgumentParser();p.add_argument('--input',type=Path,required=True);p.add_argument('--output-dir',type=Path,required=True);p.add_argument('--web-glb',type=Path,required=True)
    p.add_argument('--quality',choices=('standard','high','ultra'),default='standard');p.add_argument('--texture-resolution',type=int,default=0)
    p.add_argument('--front',type=Path);p.add_argument('--side',type=Path);p.add_argument('--back',type=Path);return p.parse_args(raw)

def look(camera,target):camera.rotation_euler=(target-camera.location).to_track_quat('-Z','Y').to_euler()

def projected_material(name,source,texture_dir,resolution):
    image=bpy.data.images.load(str(source.resolve()),check_existing=False)
    output=(texture_dir/f'{name}-{resolution}.png').resolve();image.scale(resolution,resolution);image.filepath_raw=str(output);image.file_format='PNG';image.save()
    mat=bpy.data.materials.new(f'Projected-{name}');mat.use_nodes=True
    nodes=mat.node_tree.nodes;links=mat.node_tree.links
    principled=nodes.get('Principled BSDF');tex=nodes.new('ShaderNodeTexImage');tex.image=image;tex.interpolation='Linear'
    mix=nodes.new('ShaderNodeMixRGB');mix.blend_type='MIX';mix.inputs[1].default_value=(.55,.57,.60,1)
    links.new(tex.outputs['Alpha'],mix.inputs[0]);links.new(tex.outputs['Color'],mix.inputs[2]);links.new(mix.outputs['Color'],principled.inputs['Base Color']);principled.inputs['Roughness'].default_value=.72;principled.inputs['Metallic'].default_value=0
    return mat,output

def apply_projected_color(meshes,lo,hi,refs,resolution,face_refine,texture_dir):
    texture_dir.mkdir(parents=True,exist_ok=True);materials={};outputs=[]
    for role,source in refs.items():
        if source and source.exists():materials[role],path=projected_material(role,source,texture_dir,resolution);outputs.append(path)
    if 'front' not in materials:return []
    fallback=materials['front'];dims=hi-lo
    for obj in meshes:
        obj.data.materials.clear();roles=list(materials)
        for role in roles:obj.data.materials.append(materials[role])
        uv=obj.data.uv_layers.new(name='ProjectedUV') if not obj.data.uv_layers else obj.data.uv_layers.active
        normal_matrix=obj.matrix_world.to_3x3()
        for poly in obj.data.polygons:
            center=obj.matrix_world@poly.center;normal=(normal_matrix@poly.normal).normalized()
            # Ultra keeps the face on the front reference even around its curved boundary.
            in_face=face_refine and center.z>lo.z+dims.z*.70 and center.y<(lo.y+hi.y)*.5 and normal.y<.55
            if in_face:role='front'
            elif normal.y<-.45:role='front'
            elif normal.y>.45 and 'back' in materials:role='back'
            elif 'side' in materials:role='side'
            else:role='front'
            poly.material_index=roles.index(role) if role in roles else roles.index('front')
            for loop_index in poly.loop_indices:
                point=obj.matrix_world@obj.data.vertices[obj.data.loops[loop_index].vertex_index].co
                if role=='side':u=1-(point.y-lo.y)/max(dims.y,1e-6)
                else:u=(point.x-lo.x)/max(dims.x,1e-6);u=1-u if role=='back' else u
                v=(point.z-lo.z)/max(dims.z,1e-6);uv.data[loop_index].uv=(max(0,min(1,u)),max(0,min(1,v)))
    return outputs

def main():
    a=args();a.input=a.input.resolve();a.output_dir=a.output_dir.resolve();a.web_glb=a.web_glb.resolve();a.output_dir.mkdir(parents=True,exist_ok=True);a.web_glb.parent.mkdir(parents=True,exist_ok=True)
    bpy.ops.object.select_all(action='SELECT');bpy.ops.object.delete(use_global=False)
    bpy.ops.import_scene.gltf(filepath=str(a.input));meshes=[o for o in bpy.context.scene.objects if o.type=='MESH']
    if not meshes:raise RuntimeError('GLB contains no mesh objects')
    points=[o.matrix_world@Vector(c) for o in meshes for c in o.bound_box];lo=Vector(tuple(min(p[i] for p in points) for i in range(3)));hi=Vector(tuple(max(p[i] for p in points) for i in range(3)));dims=hi-lo
    texture_outputs=[];refs={'front':a.front,'side':a.side,'back':a.back}
    if a.quality!='standard' and a.texture_resolution:
        texture_outputs=apply_projected_color(meshes,lo,hi,refs,a.texture_resolution,a.quality=='ultra',a.output_dir/'textures')
    scale=4.0/max(dims.z,dims.y,dims.x,1e-5);center=(lo+hi)/2
    root=bpy.data.objects.new('NormalizedRoot',None);bpy.context.collection.objects.link(root)
    for o in meshes:o.parent=root
    root.scale=(scale,)*3;root.location=(-center.x*scale,-center.y*scale,-lo.z*scale);bpy.context.view_layer.update()
    bpy.ops.object.select_all(action='DESELECT');root.select_set(True)
    for o in meshes:o.select_set(True)
    bpy.context.view_layer.objects.active=root
    bpy.ops.export_scene.gltf(filepath=str(a.web_glb),export_format='GLB',use_selection=True,export_apply=True,export_yup=True,export_materials='EXPORT',export_image_format='AUTO')
    scene=bpy.context.scene;scene.render.engine='BLENDER_EEVEE';scene.render.resolution_x=768;scene.render.resolution_y=768;scene.render.resolution_percentage=100;scene.render.image_settings.file_format='PNG';scene.render.film_transparent=False;scene.world.color=(0.018,0.025,0.035)
    bpy.ops.object.light_add(type='AREA',location=(4,-4,7));bpy.context.object.data.energy=1100;bpy.context.object.data.shape='DISK';bpy.context.object.data.size=5
    bpy.ops.object.light_add(type='AREA',location=(-4,1,5));bpy.context.object.data.energy=700;bpy.context.object.data.color=(0.35,0.5,1);bpy.context.object.data.size=4
    bpy.ops.object.camera_add();cam=bpy.context.object;scene.camera=cam;cam.data.lens=60;target=Vector((0,0,2))
    views={'front':(0,-8,2.3),'left-three-quarter':(-5.6,-5.6,2.7),'side':(-8,0,2.3),'back':(0,8,2.3)}
    for name,pos in views.items():cam.location=pos;look(cam,target);scene.render.filepath=str(a.output_dir/f'{name}.png');bpy.ops.render.render(write_still=True)
    stats={'schemaVersion':2,'status':'passed','quality':a.quality,'geometryResolution':{'standard':256,'high':384,'ultra':512}[a.quality],'textureResolution':a.texture_resolution or None,'faceRefinement':a.quality=='ultra','input':str(a.input),'webGlb':str(a.web_glb),'objects':len(meshes),'vertices':sum(len(o.data.vertices) for o in meshes),'polygons':sum(len(o.data.polygons) for o in meshes),'textures':[str(p) for p in texture_outputs],'renders':list(views)}
    (a.output_dir/'blender-report.json').write_text(json.dumps(stats,ensure_ascii=False,indent=2),encoding='utf-8');print('STUDIO_REPORT='+json.dumps(stats,ensure_ascii=False))
if __name__=='__main__':main()
