import json, math, os
import bpy
from mathutils import Vector

ROOT=r"C:\Users\vip\Documents\3d"
SOURCE=os.path.join(ROOT,"yoyo-blender","yoyo-volume-v2.blend")
OUT=os.path.join(ROOT,"yoyo-blender","sculpt-v3")
BLEND=os.path.join(ROOT,"yoyo-blender","yoyo-sculpt-v3.blend")
GLB=os.path.join(ROOT,"public","models","yoyo-sculpt-v3.glb")
os.makedirs(OUT,exist_ok=True)
bpy.ops.wm.open_mainfile(filepath=SOURCE)
base=bpy.data.objects.get('YOYO_VOLUME_V2')
if not base: raise RuntimeError('Locked YOYO_VOLUME_V2 baseline not found')

def bounds(obj):
    pts=[obj.matrix_world@Vector(c) for c in obj.bound_box]
    lo=Vector(tuple(min(p[i] for p in pts) for i in range(3)))
    hi=Vector(tuple(max(p[i] for p in pts) for i in range(3)))
    return lo,hi
base_lo,base_hi=bounds(base)

# Immutable in-file backup plus a sculpt copy. No remesh, scale or transform is applied.
base.name='YOYO_VOLUME_V2_LOCKED_BASELINE';base.hide_render=True;base.hide_set(True)
sculpt=base.copy();sculpt.data=base.data.copy();sculpt.name='YOYO_SCULPT_V3'
bpy.context.scene.collection.objects.link(sculpt);sculpt.hide_render=False;sculpt.hide_set(False)
bpy.ops.object.select_all(action='DESELECT');sculpt.select_set(True);bpy.context.view_layer.objects.active=sculpt

def g(x,z,cx,cz,sx,sz):
    return math.exp(-.5*(((x-cx)/sx)**2+((z-cz)/sz)**2))

changed=0;max_abs=0.0
for v in sculpt.data.vertices:
    x,y,z=v.co
    # Strict face-only mask: front-facing vertices, inset from the head silhouette.
    front=max(0.0,min(1.0,(v.normal.y-.38)/.42))
    face_mask=g(x,z,0,.603,.235,.135)
    edge_guard=max(0.0,min(1.0,(.285-abs(x))/.055))
    if front<=0 or face_mask<.025 or edge_guard<=0: continue
    d=0.0
    # Flatten the central facial plane very slightly; preserve the mantou cheek volume.
    d-=.0020*g(x,z,0,.615,.205,.105)
    # Deep oval eye sockets, plus restrained upper/lower eyelid rims.
    for side in (-1,1):
        ex=side*.073
        d-=.0100*g(x,z,ex,.620,.025,.047)
        d+=.0032*g(x,z,ex,.663,.032,.010)
        d+=.0020*g(x,z,ex,.577,.030,.009)
        # Soft cheek pad below and outside each eye.
        d+=.0025*g(x,z,side*.115,.555,.055,.030)
        # Three shallow freckle beads sculpted into the same continuous shell.
        for dx in (-.022,0,.022):
            d+=.0018*g(x,z,side*.126+dx,.548,.006,.006)
    # Restore the broad lower-face/mantou shelf without inventing a mouth or nose.
    d+=.0035*g(x,z,0,.536,.160,.027)
    # Fade displacement at the protected mask boundary.
    # face_mask is a binary region selector here; the Gaussian features already
    # provide their own smooth falloff. Edge guard alone protects the silhouette.
    d*=front*edge_guard
    if abs(d)>1e-6:
        v.co.y+=d;changed+=1;max_abs=max(max_abs,abs(d))

sculpt.data.update()
for p in sculpt.data.polygons:p.use_smooth=True
sculpt['stage']='baseline-locked-face-sculpt-v3'
sculpt['source']='YOYO_VOLUME_V2_LOCKED_BASELINE'
sculpt['changes']='Shallow face-plane, oval eye sockets, eyelid rims, cheek pads, freckles and lower mantou shelf.'
sculpt['constraints']='No transform, remesh, macro-volume edit, silhouette edit, or modular replacement.'

# Reuse the exact v2 review scene/cameras for direct visual comparison.
scene=bpy.context.scene;scene.render.engine='BLENDER_EEVEE';scene.render.resolution_x=720;scene.render.resolution_y=960;scene.render.resolution_percentage=100;scene.render.image_settings.file_format='PNG'
lo,hi=bounds(sculpt);dims=hi-lo;target=Vector(((lo.x+hi.x)/2,(lo.y+hi.y)/2,lo.z+dims.z*.51));cam=bpy.data.objects.get('Review_Camera');scene.camera=cam;cam.data.type='ORTHO';cam.data.ortho_scale=dims.z*1.13
views={'front':(0,1,.06),'three-quarter':(.72,1,.12),'side':(1,0,.06),'back':(0,-1,.06)}
for name,direction in views.items():
    cam.location=target+Vector(direction).normalized()*max(dims)*3;cam.rotation_euler=(target-cam.location).to_track_quat('-Z','Y').to_euler();scene.render.filepath=os.path.join(OUT,f'yoyo-sculpt-{name}.png');bpy.ops.render.render(write_still=True)

new_lo,new_hi=bounds(sculpt)
extent_delta=[(new_hi[i]-new_lo[i])-(base_hi[i]-base_lo[i]) for i in range(3)]
bpy.ops.wm.save_as_mainfile(filepath=BLEND)
bpy.ops.object.select_all(action='DESELECT');sculpt.select_set(True);bpy.context.view_layer.objects.active=sculpt
bpy.ops.export_scene.gltf(filepath=GLB,export_format='GLB',use_selection=True,export_apply=True,export_yup=True)
report={'blend':BLEND,'glb':GLB,'baseline':SOURCE,'changed_vertices':changed,'max_displacement':max_abs,'bounding_extent_delta':extent_delta,'pass':'baseline-locked-face-sculpt-v3','decision':'refine-code','still_missing':'Eye inserts/material, cleaner hood opening, hands, clasp and garment folds; all future edits remain baseline-locked.'}
with open(os.path.join(OUT,'report.json'),'w',encoding='utf-8') as f:json.dump(report,f,ensure_ascii=False,indent=2)
print(json.dumps(report,ensure_ascii=False))
