import json
import math
import os

import bpy
from mathutils import Vector

ROOT = r"C:\Users\vip\Documents\3d"
GLB = os.path.join(ROOT, "public", "models", "yoyo-sf3d.glb")
OUT_DIR = os.path.join(ROOT, "yoyo-blender")
BLEND = os.path.join(OUT_DIR, "yoyo-sf3d-base.blend")

os.makedirs(OUT_DIR, exist_ok=True)
bpy.ops.object.select_all(action="SELECT")
bpy.ops.object.delete(use_global=False)
bpy.ops.import_scene.gltf(filepath=GLB)

meshes = [obj for obj in bpy.context.scene.objects if obj.type == "MESH"]
if not meshes:
    raise RuntimeError("SF3D GLB contains no mesh")

for index, obj in enumerate(meshes, 1):
    obj.name = "YOYO_SF3D" if len(meshes) == 1 else f"YOYO_SF3D_{index:02d}"
    obj.data.name = f"{obj.name}_Mesh"
    for polygon in obj.data.polygons:
        polygon.use_smooth = True

world_corners = [obj.matrix_world @ Vector(corner) for obj in meshes for corner in obj.bound_box]
mins = Vector(tuple(min(v[i] for v in world_corners) for i in range(3)))
maxs = Vector(tuple(max(v[i] for v in world_corners) for i in range(3)))
center = (mins + maxs) * 0.5
dimensions = maxs - mins

# Ground and center the imported result without applying destructive remeshing.
for obj in meshes:
    obj.location.x -= center.x
    obj.location.y -= center.y
    obj.location.z -= mins.z
bpy.context.view_layer.update()

scene = bpy.context.scene
scene.render.engine = "BLENDER_EEVEE"
scene.render.resolution_x = 720
scene.render.resolution_y = 960
scene.render.resolution_percentage = 100
scene.render.image_settings.file_format = "PNG"
scene.render.film_transparent = False
scene.world.color = (0.035, 0.035, 0.045)

floor_mat = bpy.data.materials.new("Baseline_Floor")
floor_mat.diffuse_color = (0.18, 0.17, 0.16, 1)
bpy.ops.mesh.primitive_plane_add(size=max(dimensions) * 5, location=(0, 0, -0.003))
floor = bpy.context.object
floor.name = "REVIEW_FLOOR"
floor.data.materials.append(floor_mat)

def area(name, location, energy, size, color):
    data = bpy.data.lights.new(name, "AREA")
    data.energy = energy
    data.shape = "DISK"
    data.size = size
    data.color = color
    obj = bpy.data.objects.new(name, data)
    scene.collection.objects.link(obj)
    obj.location = location
    obj.rotation_euler = (math.radians(25), 0, math.atan2(location[1], location[0]) + math.pi / 2)
    return obj

scale = max(dimensions)
area("Key", (scale * 2.2, -scale * 2.8, scale * 2.7), 1100, scale * 2.0, (1.0, 0.86, 0.72))
area("Fill", (-scale * 2.0, -scale * 1.8, scale * 1.7), 700, scale * 2.3, (0.66, 0.78, 1.0))
area("Rim", (0, scale * 2.5, scale * 2.2), 900, scale * 1.6, (0.72, 0.82, 1.0))

cam_data = bpy.data.cameras.new("Review_Camera")
camera = bpy.data.objects.new("Review_Camera", cam_data)
scene.collection.objects.link(camera)
scene.camera = camera
cam_data.type = "ORTHO"
cam_data.ortho_scale = dimensions.z * 1.16

target = Vector((0, 0, dimensions.z * 0.5))
def render_view(name, direction):
    camera.location = target + Vector(direction).normalized() * scale * 3.0
    camera.rotation_euler = (target - camera.location).to_track_quat("-Z", "Y").to_euler()
    scene.render.filepath = os.path.join(OUT_DIR, f"baseline-{name}.png")
    bpy.ops.render.render(write_still=True)

# glTF import uses Blender Z-up. Determine the textured front empirically from the source convention.
render_view("front", (0, -1, 0.10))
render_view("three-quarter", (1, -1, 0.18))
render_view("side", (1, 0, 0.10))
render_view("back", (0, 1, 0.10))

stats = {
    "source": GLB,
    "blend": BLEND,
    "objects": len(meshes),
    "vertices": sum(len(obj.data.vertices) for obj in meshes),
    "polygons": sum(len(obj.data.polygons) for obj in meshes),
    "dimensions": [dimensions.x, dimensions.y, dimensions.z],
    "materials": sorted({slot.material.name for obj in meshes for slot in obj.material_slots if slot.material}),
    "limitations": "Single-view SF3D base; hidden cape, bag back, hands and soles require Blender reconstruction."
}
scene["yoyo_sf3d_stats"] = json.dumps(stats)
bpy.ops.wm.save_as_mainfile(filepath=BLEND)
with open(os.path.join(OUT_DIR, "baseline-stats.json"), "w", encoding="utf-8") as handle:
    json.dump(stats, handle, ensure_ascii=False, indent=2)
print(json.dumps(stats, ensure_ascii=False))
