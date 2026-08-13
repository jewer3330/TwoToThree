import json, os
import bpy
from mathutils import Vector

ROOT=r"C:\Users\vip\Documents\3d"
SOURCE=os.path.join(ROOT,"yoyo-blender","yoyo-sculpt-v3.blend")
OUT=os.path.join(ROOT,"yoyo-blender","color-v4")
BLEND=os.path.join(ROOT,"yoyo-blender","yoyo-color-v4.blend")
GLB=os.path.join(ROOT,"public","models","yoyo-color-v4.glb")
os.makedirs(OUT,exist_ok=True)
bpy.ops.wm.open_mainfile(filepath=SOURCE)
obj=bpy.data.objects.get('YOYO_SCULPT_V3')
if not obj: raise RuntimeError('Baseline-locked YOYO_SCULPT_V3 not found')

def mat(name,color,rough=.55,metal=.0):
    m=bpy.data.materials.get(name) or bpy.data.materials.new(name)
    m.diffuse_color=(*color,1);m.roughness=rough;m.metallic=metal
    m.use_nodes=True
    bsdf=m.node_tree.nodes.get('Principled BSDF')
    bsdf.inputs['Base Color'].default_value=(*color,1)
    bsdf.inputs['Roughness'].default_value=rough
    bsdf.inputs['Metallic'].default_value=metal
    return m
mats=[
 mat('YOYO_Indigo',(0.055,.085,.25),.62),
 mat('YOYO_Teal',(.035,.38,.50),.48),
 mat('YOYO_Skin',(.94,.66,.59),.45),
 mat('YOYO_Cream',(.82,.76,.62),.68),
 mat('YOYO_Gold',(.92,.50,.07),.34,.08),
 mat('YOYO_Brown',(.22,.065,.025),.62),
]
obj.data.materials.clear()
for m in mats:obj.data.materials.append(m)

# Materials are assigned per face on the unchanged continuous mesh. Coordinates
# were calibrated against the locked v2/v3 front, side and back renders.
points=[obj.matrix_world@Vector(c) for c in obj.bound_box]
bmin=Vector(tuple(min(p[i] for p in points) for i in range(3)))
bmax=Vector(tuple(max(p[i] for p in points) for i in range(3)))
bsize=bmax-bmin
counts=[0]*len(mats)
for poly in obj.data.polygons:
    c=obj.matrix_world@poly.center;x,y,z=c
    q=(z-bmin.z)/bsize.z
    xn=x/(bsize.x*.5)
    yn=(y-(bmin.y+bmax.y)*.5)/(bsize.y*.5)
    # Default coat/garment.
    idx=3
    # Legs exposed above boots, then boots and soles.
    if q<.055: idx=5
    elif q<.205: idx=4
    elif q<.305 and abs(xn)<.62: idx=2
    # Main coat shell.
    elif q<.535: idx=3
    # Shoulder cape / hood transition, including back volume.
    elif q<.665: idx=0
    # Head zone: front-central face, otherwise indigo hood.
    elif q<.855:
        front_face=(yn>.28 and abs(xn)<.72 and q<.80)
        idx=2 if front_face else 0
    # Hat zone: teal where top/tail dominates; keep front lower band indigo.
    else:
        idx=1
        if q<.89 and yn>.10: idx=0
    # Hands protrude laterally around sleeve height.
    if .34<q<.55 and abs(xn)>.62: idx=2
    # Pom at the right-side cap end is cream.
    if q>.80 and xn>.36 and yn<.25: idx=3
    poly.material_index=idx;counts[idx]+=1

obj['stage']='baseline-locked-color-regions-v4'
obj['changes']='Face-based multi-material regions on unchanged continuous mesh.'
obj['constraints']='No geometry split, no transform, no remesh, no silhouette edit.'
obj['inferred_regions']='Side/back boundaries inferred from volume because only one authoritative color view exists.'

def bounds(o):
    pts=[o.matrix_world@Vector(c) for c in o.bound_box]
    lo=Vector(tuple(min(p[i] for p in pts) for i in range(3)));hi=Vector(tuple(max(p[i] for p in pts) for i in range(3)))
    return lo,hi
lo,hi=bounds(obj);dims=hi-lo;target=Vector(((lo.x+hi.x)/2,(lo.y+hi.y)/2,lo.z+dims.z*.51))
scene=bpy.context.scene;scene.render.engine='BLENDER_EEVEE';scene.render.resolution_x=720;scene.render.resolution_y=960;scene.render.resolution_percentage=100;scene.render.image_settings.file_format='PNG'
cam=bpy.data.objects.get('Review_Camera');scene.camera=cam;cam.data.type='ORTHO';cam.data.ortho_scale=dims.z*1.13
views={'front':(0,1,.06),'three-quarter':(.72,1,.12),'side':(1,0,.06),'back':(0,-1,.06)}
for name,d in views.items():
    cam.location=target+Vector(d).normalized()*max(dims)*3;cam.rotation_euler=(target-cam.location).to_track_quat('-Z','Y').to_euler();scene.render.filepath=os.path.join(OUT,f'yoyo-color-{name}.png');bpy.ops.render.render(write_still=True)

bpy.ops.wm.save_as_mainfile(filepath=BLEND)
bpy.ops.object.select_all(action='DESELECT');obj.select_set(True);bpy.context.view_layer.objects.active=obj
bpy.ops.export_scene.gltf(filepath=GLB,export_format='GLB',use_selection=True,export_apply=True,export_yup=True)
report={'blend':BLEND,'glb':GLB,'baseline':SOURCE,'material_face_counts':dict(zip([m.name for m in mats],counts)),'bounding_dimensions':list(dims),'pass':'baseline-locked-color-regions-v4','decision':'refine-code','still_missing':'Reference-camera mask refinement at face/hood and sleeve/hand borders; eyes, freckles, clasp, strap and bag need localized projected masks.'}
with open(os.path.join(OUT,'report.json'),'w',encoding='utf-8') as f:json.dump(report,f,ensure_ascii=False,indent=2)
print(json.dumps(report,ensure_ascii=False))
