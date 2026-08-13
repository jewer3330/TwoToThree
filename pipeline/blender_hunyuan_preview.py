import json
import math
import os

import bpy
from mathutils import Vector


ROOT = r"C:\Users\vip\Documents\3d"
GLB = os.path.join(ROOT, "public", "models", "yoyo-hunyuan-shape-v1.glb")
OUT = os.path.join(ROOT, "yoyo-blender", "hunyuan-v1")
BLEND = os.path.join(ROOT, "yoyo-blender", "yoyo-hunyuan-shape-v1.blend")
os.makedirs(OUT, exist_ok=True)

bpy.ops.object.select_all(action="SELECT")
bpy.ops.object.delete(use_global=False)
bpy.ops.import_scene.gltf(filepath=GLB)
meshes = [o for o in bpy.context.scene.objects if o.type == "MESH"]
if not meshes:
    raise RuntimeError("Hunyuan GLB contains no mesh")

for index, obj in enumerate(meshes, 1):
    obj.name = f"YOYO_HUNYUAN_{index:02d}"
    for poly in obj.data.polygons:
        poly.use_smooth = True

corners = [o.matrix_world @ Vector(c) for o in meshes for c in o.bound_box]
mins = Vector(tuple(min(p[i] for p in corners) for i in range(3)))
maxs = Vector(tuple(max(p[i] for p in corners) for i in range(3)))
center = (mins + maxs) * 0.5
dims = maxs - mins
for obj in meshes:
    obj.location -= Vector((center.x, center.y, mins.z))
bpy.context.view_layer.update()

scene = bpy.context.scene
scene.render.engine = "BLENDER_EEVEE"
scene.render.resolution_x = 720
scene.render.resolution_y = 960
scene.render.resolution_percentage = 100
scene.render.image_settings.file_format = "PNG"
scene.world.color = (0.025, 0.028, 0.035)

mat = bpy.data.materials.new("Hunyuan_Clay")
mat.diffuse_color = (0.72, 0.76, 0.82, 1)
mat.roughness = 0.7
for obj in meshes:
    obj.data.materials.clear()
    obj.data.materials.append(mat)

floor_mat = bpy.data.materials.new("Review_Floor")
floor_mat.diffuse_color = (0.10, 0.11, 0.14, 1)
bpy.ops.mesh.primitive_plane_add(size=max(dims) * 5, location=(0, 0, -0.003))
bpy.context.object.data.materials.append(floor_mat)

scale = max(dims)
def area(name, location, energy, size, color):
    data = bpy.data.lights.new(name, "AREA")
    data.energy, data.shape, data.size, data.color = energy, "DISK", size, color
    light = bpy.data.objects.new(name, data)
    scene.collection.objects.link(light)
    light.location = location
    light.rotation_euler = (math.radians(25), 0, math.atan2(location[1], location[0]) + math.pi / 2)

area("Key", (scale * 2.2, -scale * 2.8, scale * 2.7), 1000, scale * 2, (1, .86, .72))
area("Fill", (-scale * 2, -scale * 1.8, scale * 1.7), 650, scale * 2.3, (.66, .78, 1))
area("Rim", (0, scale * 2.5, scale * 2.2), 850, scale * 1.6, (.72, .82, 1))

cam_data = bpy.data.cameras.new("Review_Camera")
cam = bpy.data.objects.new("Review_Camera", cam_data)
scene.collection.objects.link(cam)
scene.camera = cam
cam_data.type = "ORTHO"
cam_data.ortho_scale = dims.z * 1.16
target = Vector((0, 0, dims.z * .5))

for name, direction in {
    "front": (0, -1, .10),
    "three-quarter": (1, -1, .18),
    "side": (1, 0, .10),
    "back": (0, 1, .10),
}.items():
    cam.location = target + Vector(direction).normalized() * scale * 3
    cam.rotation_euler = (target - cam.location).to_track_quat("-Z", "Y").to_euler()
    scene.render.filepath = os.path.join(OUT, f"yoyo-hunyuan-{name}.png")
    bpy.ops.render.render(write_still=True)

stats = {
    "source": GLB,
    "blend": BLEND,
    "objects": len(meshes),
    "vertices": sum(len(o.data.vertices) for o in meshes),
    "faces": sum(len(o.data.polygons) for o in meshes),
    "dimensions": list(dims),
}
scene["hunyuan_preview_stats"] = json.dumps(stats)
bpy.ops.wm.save_as_mainfile(filepath=BLEND)
with open(os.path.join(OUT, "stats.json"), "w", encoding="utf-8") as f:
    json.dump(stats, f, ensure_ascii=False, indent=2)
print(json.dumps(stats, ensure_ascii=False))
