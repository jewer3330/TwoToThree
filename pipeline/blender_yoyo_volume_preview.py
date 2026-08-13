import json
import os

import bpy
from mathutils import Vector

ROOT = r"C:\Users\vip\Documents\3d"
SOURCE = os.path.join(ROOT, "yoyo-blender", "yoyo-sf3d-base.blend")
OUT_DIR = os.path.join(ROOT, "yoyo-blender", "preview-v2-volume")
OUT_BLEND = os.path.join(ROOT, "yoyo-blender", "yoyo-volume-v2.blend")
OUT_GLB = os.path.join(ROOT, "public", "models", "yoyo-volume-v2.glb")
os.makedirs(OUT_DIR, exist_ok=True)

bpy.ops.wm.open_mainfile(filepath=SOURCE)
source = next((o for o in bpy.context.scene.objects if o.type == "MESH" and o.name.startswith("YOYO_SF3D")), None)
if source is None:
    raise RuntimeError("YOYO SF3D source mesh not found")
source.name = "YOYO_SF3D_TEXTURE_REFERENCE"
source.hide_render = True
source.hide_set(True)

body = source.copy()
body.data = source.data.copy()
body.name = "YOYO_VOLUME_V2"
bpy.context.scene.collection.objects.link(body)
body.hide_render = False
body.hide_set(False)
bpy.ops.object.select_all(action="DESELECT")
body.select_set(True)
bpy.context.view_layer.objects.active = body

# Uniform voxel reconstruction closes SF3D cracks and removes zero-thickness scraps.
# 0.006 is ~155 cells over character height: enough for the star, hands and boots
# while keeping the web review mesh manageable.
remesh = body.modifiers.new("Continuous_Volume", "REMESH")
remesh.mode = "VOXEL"
remesh.voxel_size = 0.006
remesh.use_smooth_shade = True
bpy.ops.object.modifier_apply(modifier=remesh.name)

relax = body.modifiers.new("Volume_Relax", "SMOOTH")
relax.factor = 0.22
relax.iterations = 3
bpy.ops.object.modifier_apply(modifier=relax.name)
for poly in body.data.polygons:
    poly.use_smooth = True

body.data.materials.clear()
gray = bpy.data.materials.get("YOYO_Clay") or bpy.data.materials.new("YOYO_Clay")
gray.diffuse_color = (0.47, 0.51, 0.57, 1.0)
gray.metallic = 0.0
gray.roughness = 0.7
body.data.materials.append(gray)
body["stage"] = "continuous-volume-v2"
body["changes"] = "Voxel-remeshed SF3D shell at 0.006 m and relaxed three iterations."
body["still_missing"] = "Identity parts remain fused; face, fingers, cape, bag and soles need separate authored meshes."

scene = bpy.context.scene
scene.render.engine = "BLENDER_EEVEE"
scene.render.resolution_x = 720
scene.render.resolution_y = 960
scene.render.resolution_percentage = 100
scene.render.image_settings.file_format = "PNG"
scene.world.color = (0.025, 0.028, 0.035)

corners = [body.matrix_world @ Vector(c) for c in body.bound_box]
mins = Vector(tuple(min(v[i] for v in corners) for i in range(3)))
maxs = Vector(tuple(max(v[i] for v in corners) for i in range(3)))
dims = maxs - mins
center = (mins + maxs) * 0.5
target = Vector((center.x, center.y, mins.z + dims.z * 0.51))
scale = max(dims)
camera = bpy.data.objects.get("Review_Camera")
scene.camera = camera
camera.data.type = "ORTHO"
camera.data.ortho_scale = dims.z * 1.13

views = {
    "front": (0, 1, 0.06),
    "three-quarter": (0.72, 1, 0.12),
    "side": (1, 0, 0.06),
    "back": (0, -1, 0.06),
}
for name, direction in views.items():
    camera.location = target + Vector(direction).normalized() * scale * 3.0
    camera.rotation_euler = (target - camera.location).to_track_quat("-Z", "Y").to_euler()
    scene.render.filepath = os.path.join(OUT_DIR, f"yoyo-volume-{name}.png")
    bpy.ops.render.render(write_still=True)

bpy.ops.wm.save_as_mainfile(filepath=OUT_BLEND)
bpy.ops.object.select_all(action="DESELECT")
body.select_set(True)
bpy.context.view_layer.objects.active = body
bpy.ops.export_scene.gltf(filepath=OUT_GLB, export_format="GLB", use_selection=True, export_apply=True, export_yup=True)

report = {
    "blend": OUT_BLEND,
    "glb": OUT_GLB,
    "vertices": len(body.data.vertices),
    "polygons": len(body.data.polygons),
    "pass": "continuous-volume-v2",
    "decision": "refine-code",
    "still_missing": body["still_missing"],
}
with open(os.path.join(OUT_DIR, "report.json"), "w", encoding="utf-8") as handle:
    json.dump(report, handle, ensure_ascii=False, indent=2)
print(json.dumps(report, ensure_ascii=False))
