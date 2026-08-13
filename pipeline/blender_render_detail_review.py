import bpy
import os
from mathutils import Vector

WORKSPACE=r"C:\Users\vip\Documents\3d"
OUT=os.path.join(WORKSPACE,"field-commander")

for obj in list(bpy.data.objects):
    if obj.type in {"CAMERA","LIGHT"}:
        bpy.data.objects.remove(obj,do_unlink=True)

def look_at(obj, target):
    obj.rotation_euler=(Vector(target)-obj.location).to_track_quat('-Z','Y').to_euler()

bpy.ops.object.camera_add(location=(0,-2.8,0.12))
cam=bpy.context.object; cam.name="DetailReviewCamera"; cam.data.type='ORTHO'; cam.data.ortho_scale=1.18; look_at(cam,(0,0,0)); bpy.context.scene.camera=cam

def area(name,location,energy,size,color):
    bpy.ops.object.light_add(type='AREA',location=location)
    obj=bpy.context.object;obj.name=name;obj.data.energy=energy;obj.data.shape='DISK';obj.data.size=size;obj.data.color=color;look_at(obj,(0,0,0.12));return obj
area('Key',(-1.2,-1.8,1.4),700,2.0,(1.0,.86,.72))
area('Fill',(1.3,-1.0,.7),420,1.6,(.72,.84,1.0))
area('Rim',(0,1.4,1.1),650,1.2,(.82,.88,1.0))

scene=bpy.context.scene
scene.render.engine='BLENDER_EEVEE'
scene.render.resolution_x=700;scene.render.resolution_y=900;scene.render.resolution_percentage=100
scene.render.image_settings.file_format='PNG';scene.render.film_transparent=False
scene.world.color=(.045,.045,.045)

scene.render.filepath=os.path.join(OUT,'blender-detail-front.png')
bpy.ops.render.render(write_still=True)

cam.data.ortho_scale=.31;cam.location=(0,-2.8,.37);look_at(cam,(0,0,.37))
scene.render.resolution_x=800;scene.render.resolution_y=800
scene.render.filepath=os.path.join(OUT,'blender-detail-face.png')
bpy.ops.render.render(write_still=True)

print('RENDERS_READY')
