import json, os
import bpy
from mathutils import Vector

ROOT=r"C:\Users\vip\Documents\3d"
SOURCE=os.path.join(ROOT,"yoyo-blender","yoyo-free-sculpt-paint.blend")
REFERENCE=os.path.join(ROOT,"public","yoyo-reference.png")
OUT=os.path.join(ROOT,"yoyo-blender","projection-v1")
BLEND=os.path.join(ROOT,"yoyo-blender","yoyo-front-projection-v1.blend")
GLB=os.path.join(ROOT,"public","models","yoyo-front-projection-v1.glb")
os.makedirs(OUT,exist_ok=True)
bpy.ops.wm.open_mainfile(filepath=SOURCE)
obj=bpy.data.objects.get('YOYO_SCULPT_WORK')
if not obj:raise RuntimeError('YOYO_SCULPT_WORK missing')

# Keep the prior paint material for inferred/hidden surfaces.
fallback=bpy.data.materials.get('YOYO_Paint_PBR')
fallback.node_tree.nodes.get('Principled BSDF').inputs['Base Color'].default_value=(.22,.24,.28,1)

# Reference projection material. The image is used as albedo evidence only.
img=bpy.data.images.load(REFERENCE,check_existing=True)
mat=bpy.data.materials.get('YOYO_Reference_Front') or bpy.data.materials.new('YOYO_Reference_Front')
mat.use_nodes=True
nodes=mat.node_tree.nodes;links=mat.node_tree.links
for n in list(nodes):nodes.remove(n)
out=nodes.new('ShaderNodeOutputMaterial');bsdf=nodes.new('ShaderNodeBsdfPrincipled');tex=nodes.new('ShaderNodeTexImage')
uvnode=nodes.new('ShaderNodeUVMap');uvnode.uv_map='YOYO_FRONT_PROJECTION'
tex.image=img;tex.interpolation='Linear';bsdf.inputs['Roughness'].default_value=.55
links.new(uvnode.outputs['UV'],tex.inputs['Vector']);links.new(tex.outputs['Color'],bsdf.inputs['Base Color']);links.new(bsdf.outputs['BSDF'],out.inputs['Surface'])
if len(obj.data.materials)<2:obj.data.materials.append(mat)
else:obj.data.materials[1]=mat

# Camera-space UVs calibrated from the visible character bounds in the 1085x1450 design image.
# The character occupies x=173..910, y=104..1327. These values are deliberately stored
# as evidence so alignment can be refined without repainting or altering geometry.
crop={'x0':173/1085,'x1':910/1085,'y0':104/1450,'y1':1327/1450}
pts=[obj.matrix_world@Vector(c) for c in obj.bound_box]
lo=Vector(tuple(min(p[i] for p in pts) for i in range(3)));hi=Vector(tuple(max(p[i] for p in pts) for i in range(3)));size=hi-lo
uv=obj.data.uv_layers.get('YOYO_FRONT_PROJECTION') or obj.data.uv_layers.new(name='YOYO_FRONT_PROJECTION')
front_faces=0;hidden_faces=0
normal_matrix=obj.matrix_world.to_3x3()
for poly in obj.data.polygons:
    n=(normal_matrix@poly.normal).normalized()
    center=obj.matrix_world@poly.center
    # +Y faces see the authoritative design camera. Near-grazing faces stay neutral.
    is_front=n.y>.22 and center.y>(lo.y+size.y*.36)
    poly.material_index=1 if is_front else 0
    if is_front:front_faces+=1
    else:hidden_faces+=1
    for li in poly.loop_indices:
        co=obj.matrix_world@obj.data.vertices[obj.data.loops[li].vertex_index].co
        nx=(co.x-lo.x)/size.x;nz=(co.z-lo.z)/size.z
        u=crop['x0']+nx*(crop['x1']-crop['x0'])
        # Blender UV origin is lower-left; source image crop values are top-left.
        v=1-(crop['y1']-nz*(crop['y1']-crop['y0']))
        uv.data[li].uv=(u,v)
obj.data.uv_layers.active=uv
obj['stage']='reference-front-projection-v1'
obj['projection_crop']=json.dumps(crop)
obj['projection_rule']='Only camera-facing polygons receive reference pixels; side/back remain inferred-neutral.'

scene=bpy.context.scene;scene.render.engine='BLENDER_EEVEE';scene.render.resolution_x=720;scene.render.resolution_y=960;scene.render.resolution_percentage=100;scene.render.image_settings.file_format='PNG'
target=Vector(((lo.x+hi.x)/2,(lo.y+hi.y)/2,lo.z+size.z*.51));cam=bpy.data.objects.get('YOYO_REFERENCE_CAMERA');scene.camera=cam;cam.data.ortho_scale=size.z*1.10
views={'front':(0,1,.025),'three-quarter':(.45,1,.07),'side':(1,0,.04),'back':(0,-1,.025)}
for name,d in views.items():
    cam.location=target+Vector(d).normalized()*max(size)*3;cam.rotation_euler=(target-cam.location).to_track_quat('-Z','Y').to_euler();scene.render.filepath=os.path.join(OUT,f'yoyo-projection-{name}.png');bpy.ops.render.render(write_still=True)

bpy.ops.wm.save_as_mainfile(filepath=BLEND)
bpy.ops.object.select_all(action='DESELECT');obj.select_set(True);bpy.context.view_layer.objects.active=obj
bpy.ops.export_scene.gltf(filepath=GLB,export_format='GLB',use_selection=True,export_apply=True,export_yup=True)
report={'blend':BLEND,'glb':GLB,'baseline':SOURCE,'reference':REFERENCE,'crop':crop,'front_faces':front_faces,'hidden_faces':hidden_faces,'geometry_changed':False,'pass':'reference-front-projection-v1','decision':'refine-code','still_missing':'Camera/crop calibration, de-lighting, seam feathering, side/back authored color, PBR channel separation.'}
with open(os.path.join(OUT,'report.json'),'w',encoding='utf-8') as f:json.dump(report,f,ensure_ascii=False,indent=2)
print(json.dumps(report,ensure_ascii=False))
